"""
SmallCaps Screener — Screener principal (entonnoir 2 passes)

Passe A — prix/volume en batch sur tout l'univers (yf.download groupé) :
           filtres durs prix / perf 1m / liquidité / tendance,
           calcul des signaux vol_ratio / compression / force relative.
Passe B — enrichissement `.info` uniquement sur les survivants :
           filtres durs market cap / exchange, signaux fondamentaux,
           scoring, génération de screener_data.json.

Découpler prix (batch, fiable) et fondamentaux (.info, coûteux) permet de
couvrir l'univers complet au coût d'un ancien scan partiel, et réduit le
nombre d'appels `.info` → moins de throttling Yahoo.
"""

import json
import os
import time
import math
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf
import pandas as pd

# ---------------------------------------------------------------------------
# FILTRES — tous les seuils configurables ici
# ---------------------------------------------------------------------------
FILTERS = {
    # Hard filters — tout ticker qui échoue est éliminé
    "market_cap_min_m": 50,        # millions USD
    "market_cap_max_m": 2000,
    "price_min": 2.0,              # USD
    "price_max": 25.0,             # fourchette resserrée 2-25$ (essai)
    "ipo_year_min": 2015,          # informatif uniquement (plus de points)
    "perf_1m_min": -0.35,
    "perf_1m_max": 0.25,           # garde-fou léger « pas déjà explosé » (le scoring gère le reste)
    "vol_window_short": 10,        # jours pour vol court
    "vol_window_long": 50,         # jours pour vol long (baseline)
    "compression_window": 20,      # jours pour range compressé
    "compression_baseline": 90,    # jours baseline range
    "compression_threshold": 0.70, # range 20j < 70% range 90j
    # --- Tendance (Palier 1) ---
    "ma_trend_window": 50,         # MA de tendance
    "ma_slope_lookback": 10,       # pente = MA(t) vs MA(t-10)
    "trend_require_above_ma": False, # prix > MA50 = SCORING (plus un filtre dur) → capte le début de hausse
    # --- Force relative ---
    "rs_benchmark": "IWM",         # ETF Russell 2000 (small caps US)
    "rs_return_window": 63,        # ~3 mois de bourse
    "rs_line_lookback": 21,        # pente RS-line sur ~1 mois
    "rs_require": False,           # RS = SCORING (plus un filtre dur) → ne pas exiger « déjà fort »
    # --- Liquidité (Palier 1) ---
    "dollar_vol_window": 20,
    "dollar_vol_min": 1_000_000,   # USD, plancher médian (hard) — §9 revue quant, vraie tradabilité
    # --- Signaux affinés (§9) ---
    "use_atr_compression": True,   # compression via True Range (High/Low) au lieu du Close-only
    "obv_lookback": 21,            # OBV en hausse sur ~1 mois → accumulation (vs distribution)
    # --- Capteurs v2 (Sprint 4) : compression & accumulation refondues ---
    "sensors_version": "v2",           # "v2" (défaut) | "v1" (ancien, conservé pour le backtest S6)
    # Compression v2 : percentile du ratio ATR20/ATR90 vs la propre distribution du TITRE
    # (« ce titre est-il inhabituellement calme PAR RAPPORT À LUI-MÊME ? » = vrai ressort VCP).
    "compression_pct_lookback": 252,   # fenêtre (jours) de la distribution auto-référencée
    "compression_pct_threshold": 0.25, # percentile < seuil → comprimé (indicatif)
    "compression_pct_min_obs": 60,     # nb min d'obs de ratio, sinon neutre (IPO récentes ; pas d'exception)
    # Accumulation v2 : Chaikin Money Flow 20j + ratio volume hausse/baisse 50j
    "cmf_window": 20,                  # fenêtre CMF (close-location × volume)
    "updown_vol_window": 50,           # fenêtre du ratio volume jours-hausse / jours-baisse
    "cmf_pos_threshold": 0.0,          # CMF > seuil → afflux net (accumulation)
    "updown_ratio_min": 1.0,           # ratio volume up/down > seuil → acheteurs dominants
    "high_window": 252,            # fenêtre plus-haut 52 sem. (informatif : pct_52w_high)
    "near_high_pct": 0.75,         # informatif
    "float_max": 50_000_000,       # float < 50M actions → petit float amplifie
    "rs_strong": 0.20,             # surperf RS ≥ 20% (informatif)
    # --- Inflexion précoce : capter le DÉBUT de hausse, pas le sommet ---
    "pivot_window": 50,            # plus-haut de la base RÉCENTE (~10 sem.) — le point de cassure
    "near_pivot_pct": 0.85,        # prix ≥ 85% du plus-haut récent → près du pivot de breakout
    "low_ext_pct": 0.12,           # prix ≤ MA50 × 1.12 → peu étiré (encore tôt)
    # --- Trigger (Sprint 3) : la cassure a lieu MAINTENANT (distinct du setup/score) ---
    "trigger_vol_window": 50,      # moyenne de volume (jours) servant de baseline à la cassure
    "trigger_vol_mult": 1.5,       # volume du jour > 1.5× la moyenne 50j → confirme la cassure
    # --- Alerte Telegram (Sprint 3) — secrets via .env, jamais en dur ---
    "alert_min_score": 7,          # setup_score minimal d'un NOUVEAU déclenché pour alerter
    "alert_dedup_days": 5,         # pas de re-notification d'un même ticker avant N jours
    # --- Mode de scoring : NON tranché tant que le backtest robuste n'a pas décidé ---
    # "binary"     : ancien score « cases à cocher » (connu/conservateur ; plafonne ~8)
    # "continuous" : facteurs continus → percentile → décile 0-10 (échelle pleine, non validé)
    "scoring_mode": "binary",
    # --- Poids de scoring (utilisés par les deux modes ; configurables pour le backtest) ---
    "score_weights": {
        "accumulation": 4,  # OBV↑ : l'argent rentre (LE meilleur signal pré-explosion)
        "compression": 2,   # base serrée — baissé 3→2 : signal quasi mort (0,8%), impact cosmétique (backtest)
        "near_pivot": 2,    # proche du point de cassure de la base récente
        "low_ext": 2,       # peu étiré : encore tôt
        "rs_turning": 2,    # la force relative repart à la hausse
        "above_ma": 1,      # au-dessus de la MA50
        "insider": 2, "cash": 1, "revenue": 1, "low_float": 1, "short": 1,
    },
    # --- Filet de sécurité : échantillon NON biaisé des survivants si trop nombreux ---
    "enrich_max": 150,             # borne dure du nb d'appels .info (coût + throttle Yahoo)
    # Soft filters — scoring uniquement
    "vol_ratio_min": 1.2,
    "vol_ratio_max": 3.0,
    "insider_pct_min": 5.0,         # % détention (AFFICHAGE informatif ; plus au scoring depuis S5)
    "revenue_growth_min": 0.10,
    "short_interest_high": 15.0,
    # --- Insiders EDGAR Form 4 (Sprint 5) : achats nets datés, point-in-time ---
    "insider_window_days": 180,     # fenêtre d'agrégation des achats nets (3-6 mois)
    "survival_window_days": 180,    # fenêtre des signaux de survie EDGAR (dilution, NT) — Epic 3 S2
    "edgar_cache_ttl_hours": 24,    # TTL cache des listes de filings (soumissions par CIK)
    "edgar_rate_limit_s": 0.12,     # ≥0.11 → ≤ ~9 req/s (SEC exige ≤ 10 req/s)
    "edgar_max_filings": 12,        # garde-fou : nb max de Form 4 parsés par ticker (récents ; ~3-6 mois d'activité)
    # --- Backtest study (Sprint 6) : l'instrument de mesure (aucun ajustement de poids ici) ---
    "study_cost_roundtrip": 0.01,   # décote aller-retour (1%) appliquée aux rendements nets
    "study_position_usd": 10_000,   # position notionnelle pour la contrainte de capacité
    "study_adv_max_frac": 0.01,     # position ≤ 1% du dollar-volume quotidien (sinon obs exclue)
    "study_step_days": 21,          # pas entre dates as-of (≈ mensuel)
    "study_horizons": (21, 63),     # horizons forward (jours de bourse)
    "study_ic_min_names": 5,        # nb min de survivants/date pour calculer une IC de date
    # Scoring
    "score_vol_ratio_min": 1.3,
    "score_vol_ratio_max": 2.5,
    "allowed_exchanges": {"NMS", "NYQ", "NGM", "NCM"},
    "rate_limit_s": 0.3,           # entre lots yf.download (Passe A)
    "cache_minutes": 30,
    # --- Découverte de l'univers (Sprint 1 : univers COMPLET et stable) ---
    "discovery_exchanges": ("nasdaq", "nyse", "amex"),  # 3 places US via l'API NASDAQ screener
    "discovery_marketcaps": ("Small", "Micro"),          # catégories cap pré-filtrées côté API
    "max_tickers": None,           # None → univers COMPLET (aucun échantillonnage) ; int → soupape (tests/debug)
    "download_chunk": 100,         # taille des lots yf.download
    "download_retries": 3,         # retries + backoff sur lot prix throttlé (429) — anti-perte silencieuse
    "history_period": "1y",        # 1 an : requis pour plus-haut 52 sem. + ATR90 (Palier 2)
    "enrich_workers": 2,           # threads .info en Passe B — BAS : Yahoo bannit l'IP au-delà
    "enrich_jitter_s": 0.5,        # jitter aléatoire par appel .info (anti-throttle Yahoo)
    "enrich_retries": 4,           # retries sur YFRateLimitError
    "enrich_backoff_s": 3.0,       # base du backoff exponentiel (3, 6, 12, 24s + jitter)
    "shuffle_seed": None,          # int → ordre de téléchargement reproductible ; None → ordre aléatoire
                                   # (n'affecte PLUS la composition de l'univers, seulement l'ordre)
    # --- Pivot Epic 2 (Sprint 2) : univers tradable + détecteurs de profils ---
    # "tradability" (défaut) : filtres durs réduits à prix ≥ price_min + dollar-volume ≥
    #     dollar_vol_min ; la SÉLECTION est faite par les DÉTECTEURS DE PROFILS (Fusée/Phénix),
    #     plus par le score. "legacy" : ancien entonnoir v1 (price_max, bande perf_1m, garde
    #     pente MA50) — conservé pour la reproductibilité du backtest v1 (régression).
    "pool_mode": "tradability",
    # Seuils des profils = PERCENTILES cross-sectionnels dans l'univers tradable, VERBATIM au
    # protocole v2 §3 (docs/backtest_protocol_v2.md). SOURCE UNIQUE partagée production ↔ étude ;
    # toute déviation exige d'abord une révision du protocole.
    "profiles": {
        "fusee":  {"rs63_pctile_min": 0.80, "perf_1m_pctile_min": 0.80},
        "phenix": {"pct_52w_pctile_max": 0.20, "atr_ratio_pctile_max": 0.40},
        "phenix_sma_window": 20,   # close ≥ SMA20 : garde de stabilisation (booléenne, pas un percentile)
    },
}

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_FILE = Path(DATA_DIR) / "screener_data.json"
HISTORY_DIR = Path(DATA_DIR) / "history"   # instantanés datés pour le suivi de performance

scan_state = {
    "scanning": False,
    "progress": 0,
    "total": 0,
    "phase": "idle",  # idle | download | price_filter | enrich
}


# ---------------------------------------------------------------------------
# Découverte dynamique des tickers
# ---------------------------------------------------------------------------

def discover_tickers() -> list[str]:
    """
    Univers COMPLET des small/micro caps US via l'API NASDAQ screener, interrogée sur
    les trois places (NASDAQ + NYSE + AMEX) et les catégories Small + Micro cap, puis
    dédoublonnée.

    L'univers est STABLE d'un scan à l'autre : aucun échantillonnage aléatoire. Le
    mélange (`shuffle_seed`) ne change QUE l'ordre de téléchargement, pas la composition
    du vivier. `max_tickers` (None par défaut) ne tronque plus l'univers — c'est une
    soupape de sécurité optionnelle (int) réservée aux tests / au debug.

    Finviz a été retiré (Sprint 1) : sans pagination il n'apportait qu'une vingtaine de
    tickers d'une seule place (NASDAQ), désormais entièrement couverte par l'API NASDAQ.
    """
    tickers: set[str] = set()
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    # API NASDAQ screener — pré-filtrée small + micro cap, sur les 3 places US.
    for exchange in FILTERS["discovery_exchanges"]:
        for marketcap in FILTERS["discovery_marketcaps"]:
            try:
                resp = requests.get(
                    "https://api.nasdaq.com/api/screener/stocks"
                    f"?tableonly=true&limit=5000&exchange={exchange}&marketcap={marketcap}",
                    headers=headers,
                    timeout=20,
                )
                rows = resp.json().get("data", {}).get("table", {}).get("rows") or []
                before = len(tickers)
                for row in rows:
                    symbol = (row.get("symbol") or "").strip().upper()
                    if symbol and "." not in symbol and "/" not in symbol:
                        tickers.add(symbol)
                print(f"[discovery] NASDAQ {exchange}/{marketcap}: +{len(tickers) - before} "
                      f"(total {len(tickers)})")
            except Exception as e:
                print(f"[discovery] NASDAQ {exchange}/{marketcap} erreur: {e}")

    result = sorted(tickers)  # ordre déterministe → univers reproductible avant mélange
    if FILTERS["shuffle_seed"] is not None:
        random.seed(FILTERS["shuffle_seed"])  # ordre de téléchargement reproductible
    random.shuffle(result)  # n'affecte QUE l'ordre de téléchargement, pas la composition

    cap = FILTERS["max_tickers"]
    if cap is not None and len(result) > cap:
        print(f"[discovery] Pool total: {len(result)} tickers → tronqué à {cap} (soupape max_tickers)")
        return result[:cap]
    print(f"[discovery] Univers complet: {len(result)} tickers (NASDAQ+NYSE+AMEX, small+micro)")
    return result


# ---------------------------------------------------------------------------
# Helpers (fonctions pures, testables hors ligne)
# ---------------------------------------------------------------------------

def _safe_float(val, default=None):
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if series is None or len(series) < periods + 1:
        return None
    old = series.iloc[-periods - 1]
    new = series.iloc[-1]
    if old == 0:
        return None
    return (new - old) / old


def _range_pct(series: pd.Series, window: int) -> float | None:
    """Range (High-Low) sur `window` jours / dernier prix."""
    if series is None or len(series) < window:
        return None
    sl = series.iloc[-window:]
    rng = sl.max() - sl.min()
    ref = series.iloc[-1]
    if ref == 0:
        return None
    return rng / ref


def _sma(series: pd.Series, window: int) -> float | None:
    if series is None or len(series) < window:
        return None
    return float(series.iloc[-window:].mean())


def _ma_rising(series: pd.Series, window: int, lookback: int) -> bool | None:
    """Pente de la MA >= 0 : MA(aujourd'hui) >= MA(il y a `lookback` jours)."""
    if series is None or len(series) < window + lookback:
        return None
    now = series.iloc[-window:].mean()
    past = series.iloc[-window - lookback:-lookback].mean()
    return bool(now >= past)


def _median_dollar_volume(close: pd.Series, volume: pd.Series, window: int) -> float | None:
    if close is None or volume is None or len(close) < window or len(volume) < window:
        return None
    dv = close.iloc[-window:] * volume.iloc[-window:]
    val = float(dv.median())
    return None if math.isnan(val) else val


def _atr(df: pd.DataFrame, window: int) -> float | None:
    """ATR (moyenne du True Range) sur `window` jours. Nécessite High/Low/Close."""
    if df is None or not {"High", "Low", "Close"}.issubset(df.columns) or len(df) < window + 1:
        return None
    high, low, prev_close = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    val = float(tr.iloc[-window:].mean())
    return None if math.isnan(val) else val


def _obv_rising(close: pd.Series, volume: pd.Series, lookback: int) -> bool | None:
    """
    On-Balance Volume en hausse sur `lookback` jours → accumulation (acheteurs > vendeurs).
    Distingue l'accumulation de la distribution, ce que le ratio de volume brut ne fait pas (§9).
    """
    if close is None or volume is None or len(close) < lookback + 2:
        return None
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * volume).cumsum()
    return bool(obv.iloc[-1] > obv.iloc[-lookback - 1])


def _accum_fraction(close: pd.Series, volume: pd.Series, lookback: int) -> float | None:
    """
    Accumulation CONTINUE : fraction de volume directionnel net sur `lookback` jours,
    dans [-1, 1] (comparable entre tickers). +1 = tout le volume est acheteur, -1 = vendeur.
    Version continue de l'OBV, pour le scoring en percentile.
    """
    if close is None or volume is None or len(close) < lookback + 1:
        return None
    d = close.diff().iloc[-lookback:]
    v = volume.iloc[-lookback:]
    signed = float((v * d.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).sum())
    total = float(v.sum())
    return signed / total if total else None


def _atr_series(df: pd.DataFrame, window: int) -> pd.Series | None:
    """Série ATR (moyenne mobile du True Range) sur `window` jours. Nécessite High/Low/Close."""
    if df is None or not {"High", "Low", "Close"}.issubset(df.columns) or len(df) < window + 1:
        return None
    high, low, prev_close = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _compression_self_pct(df: pd.DataFrame, short: int, long: int,
                          lookback: int, min_obs: int) -> float | None:
    """
    Compression v2 (Sprint 4) : percentile du ratio ATR`short`/ATR`long` du JOUR vs la
    distribution des `lookback` derniers jours de ce MÊME ratio, pour CE titre (série
    temporelle auto-référencée — PAS un percentile cross-sectionnel entre titres).

    Plus bas = titre inhabituellement calme par rapport à lui-même (ressort VCP armé).
    Retourne un percentile ∈ [0,1], ou None si trop peu d'observations (IPO récente) — jamais
    d'exception (bord fenêtre 252 j vs history_period≈250 barres → distribution réduite mais
    exploitable ; distribution quasi vide → None neutre).
    """
    atr_s = _atr_series(df, short)
    atr_l = _atr_series(df, long)
    if atr_s is None or atr_l is None:
        return None
    ratio = (atr_s / atr_l).replace([float("inf"), float("-inf")], float("nan")).dropna()
    if len(ratio) < min_obs:
        return None
    window = ratio.iloc[-lookback:]
    current = float(window.iloc[-1])
    return float((window <= current).sum() / len(window))


def _cmf(df: pd.DataFrame, window: int) -> float | None:
    """
    Chaikin Money Flow sur `window` jours (accumulation v2, Sprint 4).
    MFM = ((close-low) - (high-close)) / (high-low) ∈ [-1,1] (position de clôture dans le range) ;
    CMF = Σ(MFM × volume) / Σ(volume). > 0 = afflux net (acheteurs), < 0 = distribution.
    Jour où high==low → MFM=0 (pas d'information directionnelle).
    """
    if (df is None or not {"High", "Low", "Close", "Volume"}.issubset(df.columns)
            or len(df) < window):
        return None
    high, low, close, vol = df["High"], df["Low"], df["Close"], df["Volume"]
    rng = high - low
    mfm = ((close - low) - (high - close)) / rng.where(rng != 0)
    mfm = mfm.fillna(0.0)  # high==low → 0
    w_mfv = float((mfm * vol).iloc[-window:].sum())
    w_vol = float(vol.iloc[-window:].sum())
    if w_vol == 0:
        return None
    val = w_mfv / w_vol
    return None if math.isnan(val) else val


def _updown_vol_ratio(close: pd.Series, volume: pd.Series, window: int) -> float | None:
    """
    Ratio volume des jours HAUSSE / volume des jours BAISSE sur `window` jours (accumulation v2).
    > 1 = le volume se concentre les jours de hausse (acheteurs dominants).
    Aucun jour de baisse (down=0) : +inf si du volume haussier existe, sinon None.
    """
    if close is None or volume is None or len(close) < window + 1:
        return None
    d = close.diff().iloc[-window:]
    v = volume.iloc[-window:]
    up = float(v[d > 0].sum())
    down = float(v[d < 0].sum())
    if down == 0:
        return float("inf") if up > 0 else None
    return up / down


def _pct_of_high(close: pd.Series, window: int) -> float | None:
    """Dernier prix / plus-haut sur `window` jours (position dans le range 52 sem.)."""
    if close is None or len(close) == 0:
        return None
    w = min(window, len(close))
    hi = float(close.iloc[-w:].max())
    if hi == 0:
        return None
    return float(close.iloc[-1]) / hi


def _breakout(df: pd.DataFrame, close: pd.Series,
              volume: pd.Series) -> tuple[bool, int | None, float | None]:
    """
    Cassure EN COURS (Sprint 3) — fonction pure, hors ligne. Distincte du setup/score :
    le score dit « le ressort est armé », le trigger dit « la cassure a lieu maintenant ».

    Retourne (triggered, days_since_trigger, pivot_level) :
      - pivot = plus-haut des `pivot_window` jours PRÉCÉDENTS, séance courante EXCLUE
        (via High si dispo, sinon Close).
      - triggered = close > pivot ET volume du jour > `trigger_vol_mult` × moyenne du
        volume sur `trigger_vol_window` jours (séance courante exclue).
      - days_since_trigger = nb de séances depuis le franchissement du pivot (cassure = 0) ;
        None si le prix n'est pas au-dessus du pivot.
    """
    win = FILTERS["pivot_window"]
    if close is None or len(close) < win + 1:
        return False, None, None
    high = df["High"].dropna() if df is not None and "High" in df else close
    prior = high.iloc[-(win + 1):-1]  # exclut la séance courante
    if len(prior) == 0:
        return False, None, None
    pivot = float(prior.max())
    price = float(close.iloc[-1])
    price_ok = price > pivot

    vw = FILTERS["trigger_vol_window"]
    vbase = volume.iloc[-(vw + 1):-1] if volume is not None else None
    vol_avg = float(vbase.mean()) if vbase is not None and len(vbase) else None
    vol_ok = bool(vol_avg and float(volume.iloc[-1]) > FILTERS["trigger_vol_mult"] * vol_avg)

    triggered = bool(price_ok and vol_ok)

    # days_since_trigger : compté contre le pivot « tel qu'il était » CHAQUE jour
    # (rolling max des `win` jours PRÉCÉDENTS via .shift(1)). Comparer au pivot FIXE du jour
    # dégénérerait toujours à 0 : toute clôture passée ≤ son propre high ≤ pivot d'aujourd'hui.
    days_since = None
    if price_ok:
        pivot_asof = high.rolling(win).max().shift(1).reindex(close.index)
        above = (close > pivot_asof).tolist()
        count = 0
        for a in reversed(above):
            if a:
                count += 1
            else:
                break
        days_since = count - 1  # la séance de cassure elle-même = 0
    return triggered, days_since, round(pivot, 2)


def _rs_metrics(close: pd.Series, bench_close: pd.Series,
                ret_window: int, line_lookback: int) -> tuple[bool | None, bool | None, float | None]:
    """
    Force relative vs benchmark. Aligne les deux séries sur leurs dates communes.
    Retourne (surperforme, RS-line en hausse, magnitude = surperf relative sur ret_window).
    """
    if close is None or bench_close is None:
        return None, None, None
    joined = pd.concat([close, bench_close], axis=1, join="inner").dropna()
    if len(joined) < max(ret_window, line_lookback) + 1:
        return None, None, None
    s, b = joined.iloc[:, 0], joined.iloc[:, 1]
    if s.iloc[-ret_window - 1] == 0 or b.iloc[-ret_window - 1] == 0:
        return None, None, None
    s_ret = s.iloc[-1] / s.iloc[-ret_window - 1] - 1
    b_ret = b.iloc[-1] / b.iloc[-ret_window - 1] - 1
    strength = float(s_ret - b_ret)          # magnitude continue (Palier 2 / #4)
    outperf = bool(s_ret > b_ret)
    rs_line = s / b
    rising = bool(rs_line.iloc[-1] > rs_line.iloc[-line_lookback - 1])
    return outperf, rising, strength


def _build_positives_flags(stock: dict) -> tuple[list[str], list[str]]:
    positives, flags = [], []

    vr = stock.get("vol_ratio")
    if vr and FILTERS["score_vol_ratio_min"] <= vr <= FILTERS["score_vol_ratio_max"]:
        positives.append(f"Volume en hausse x{vr:.1f} (zone idéale)")
    elif vr and vr > FILTERS["score_vol_ratio_max"]:
        flags.append(f"Volume très élevé x{vr:.1f} (possible spike)")

    if stock.get("accumulation"):
        positives.append("OBV en hausse : accumulation (acheteurs > vendeurs)")

    if stock.get("compressed"):
        positives.append("Base serrée (compression ATR) — ressort armé")

    if stock.get("near_pivot"):
        pct = (stock.get("pct_recent_high") or 0) * 100
        positives.append(f"Proche du pivot de sa base récente ({pct:.0f}%) — sur le point de casser")

    if stock.get("low_ext"):
        positives.append("Peu étiré (proche de la MA50) — début de mouvement, pas après")

    if stock.get("rs_turning"):
        positives.append("Force relative qui repart à la hausse (retournement)")

    if stock.get("price_above_ma50"):
        positives.append("Cours au-dessus de la MA50")

    if stock.get("change_1m") is not None and stock["change_1m"] * 100 < -15:
        flags.append(f"Correction forte 1 mois ({stock['change_1m']*100:+.1f}%)")

    if stock.get("insider_net_buying") and stock["insider_net_buying"] > 0:
        positives.append(
            f"Achats nets d'insiders +{stock['insider_net_buying']/1e3:.0f}k$ "
            f"(Form 4, {FILTERS['insider_window_days']}j)")
    if stock.get("insider_buying"):   # informatif : % de détention (n'est plus au scoring)
        positives.append(f"Insiders détiennent {stock.get('insider_pct', 0):.1f}% du capital")

    if stock.get("low_float"):
        positives.append(f"Petit float ({(stock.get('float_shares') or 0)/1e6:.0f}M actions) — mouvements amplifiés")

    # cash_positive : None = donnée absente → ni positif ni flag (ne pas pénaliser)
    if stock.get("cash_positive") is True:
        positives.append("Trésorerie > dette (bilan sain)")
    elif stock.get("cash_positive") is False:
        flags.append("Dette supérieure à la trésorerie")

    if stock.get("revenue_growth") and stock["revenue_growth"] > FILTERS["revenue_growth_min"]:
        positives.append(f"Croissance revenus +{stock['revenue_growth']*100:.0f}%")

    if stock.get("short_interest_pct") and stock["short_interest_pct"] > FILTERS["short_interest_high"]:
        positives.append(f"Short interest élevé {stock['short_interest_pct']:.1f}% → potentiel squeeze")

    if stock.get("ipo_year") and stock["ipo_year"] >= FILTERS["ipo_year_min"]:
        positives.append(f"IPO récente ({stock['ipo_year']})")

    return positives, flags


def _tech_rules(sig: dict) -> list[tuple[bool, int]]:
    """Règles TECHNIQUES (prix/volume, sans .info) — dispo dès la Passe A."""
    W = FILTERS["score_weights"]
    return [
        (bool(sig.get("accumulation")), W["accumulation"]),   # OBV↑ : l'argent rentre (pilier)
        (bool(sig.get("compressed")), W["compression"]),      # base serrée (pilier)
        (bool(sig.get("near_pivot")), W["near_pivot"]),       # près du pivot de breakout
        (bool(sig.get("low_ext")), W["low_ext"]),             # peu étiré : encore tôt
        (bool(sig.get("rs_turning")), W["rs_turning"]),       # force relative qui repart
        (bool(sig.get("price_above_ma50")), W["above_ma"]),   # au-dessus MA50
    ]


def _fundamental_rules(stock: dict) -> list[tuple[bool, int]]:
    """Règles FONDAMENTALES (via .info) — ajoutées en Passe B."""
    W = FILTERS["score_weights"]
    return [
        (bool(stock.get("insider_net_buying_pos")), W["insider"]),  # S5 : achats nets Form 4 (> 0)
        (stock.get("cash_positive") is True, W["cash"]),      # None ne compte pas
        (bool(stock.get("revenue_growth") and
              stock["revenue_growth"] > FILTERS["revenue_growth_min"]), W["revenue"]),
        (bool(stock.get("low_float")), W["low_float"]),
        (bool(stock.get("short_interest_pct") and
              stock["short_interest_pct"] > FILTERS["short_interest_high"]), W["short"]),
    ]


def _binary_price_score(sig: dict) -> int:
    """[Ancienne version binaire — conservée pour comparaison au backtest.]"""
    return sum(w for cond, w in _tech_rules(sig) if cond)


def _binary_score(stock: dict) -> int:
    """[Ancienne version binaire — conservée pour comparaison au backtest.]"""
    rules = _tech_rules(stock) + _fundamental_rules(stock)
    raw = sum(w for cond, w in rules if cond)
    raw_max = sum(w for _, w in rules)
    return round(10 * raw / raw_max) if raw_max else 0


# ---------------------------------------------------------------------------
# Scoring PERCENTILE de facteurs continus (recommandation quant)
# Chaque facteur → valeur continue → percentile parmi les candidats → moyenne pondérée.
# (key_de_la_valeur, nom_du_poids, higher_is_better)
# ---------------------------------------------------------------------------
TECH_FACTORS = [
    ("f_accum",      "accumulation", True),   # fraction volume directionnel net
    ("f_atr_ratio",  "compression",  False),  # ATR20/ATR90 : plus bas = plus comprimé
    ("f_pct_recent", "near_pivot",   True),   # proximité du plus-haut récent
    ("f_ext",        "low_ext",      False),  # écart à la MA50 : plus bas = plus tôt
    ("f_rs",         "rs_turning",   True),   # magnitude de force relative
]
FUND_FACTORS = [
    ("insider_net_buying", "insider",   True),   # S5 : $ nets Form 4 (remplace le % détention)
    ("cash_bin",           "cash",      True),   # 1 / 0 / None(neutre)
    ("revenue_growth",     "revenue",   True),
    ("float_shares",       "low_float", False),  # plus petit float = mieux
    ("short_interest_pct", "short",     True),
]


def _rank_pct(values: list) -> list[float]:
    """Percentile [0,1] de chaque valeur (plus grand = plus proche de 1). None → 0.5 (neutre)."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out = [0.5] * len(values)
    n = len(present)
    if n <= 1:
        return out
    for rank, (i, _) in enumerate(sorted(present, key=lambda x: x[1])):
        out[i] = rank / (n - 1)
    return out


def _factor_composite(items: list[dict], factors: list[tuple]) -> list[float]:
    """Composite ∈ [0,1] par item = moyenne pondérée des percentiles de chaque facteur."""
    W = FILTERS["score_weights"]
    pct = {}
    for key, wname, higher in factors:
        vals = [it.get(key) for it in items]
        if not higher:
            vals = [(-v if v is not None else None) for v in vals]
        pct[wname] = _rank_pct(vals)
    total_w = sum(W[wname] for _, wname, _ in factors) or 1
    return [sum(W[wname] * pct[wname][i] for _, wname, _ in factors) / total_w
            for i in range(len(items))]


def _select_scores(signals_list: list[dict]) -> list[float]:
    """
    Score technique des survivants pour choisir qui enrichir (ordre seul).
    Suit FILTERS['scoring_mode'] pour rester cohérent avec le score final.
    """
    if FILTERS["scoring_mode"] == "continuous":
        return _factor_composite(signals_list, TECH_FACTORS)
    return [float(_binary_price_score(s)) for s in signals_list]


def _score_candidates(candidates: list[dict]) -> None:
    """
    Écrit `score` (0-10) dans chaque candidat, en place, selon FILTERS['scoring_mode'] :
      - "binary"     : ancien score « cases à cocher » (par ticker ; plafonne ~8).
      - "continuous" : moyenne pondérée de percentiles de facteurs continus, étalée en RANG
        DÉCILE (le meilleur du vivier du jour = 10). Le rang évite le tassement au milieu.
    """
    if FILTERS["scoring_mode"] == "continuous":
        comp = _factor_composite(candidates, TECH_FACTORS + FUND_FACTORS)
        ranks = _rank_pct(comp)
        for stock, r in zip(candidates, ranks):
            stock["score"] = round(10 * r)
    else:
        for stock in candidates:
            stock["score"] = _binary_score(stock)


# ---------------------------------------------------------------------------
# Téléchargement prix en batch
# ---------------------------------------------------------------------------

def _extract_symbol(data: pd.DataFrame, sym: str) -> pd.DataFrame | None:
    """Extrait le sous-DataFrame OHLCV d'un ticker depuis le résultat yf.download."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if sym not in data.columns.get_level_values(0):
                return None
            sub = data[sym].dropna(how="all")
        else:
            sub = data.dropna(how="all")  # chunk d'un seul symbole
        return sub if not sub.empty else None
    except Exception:
        return None


def _download_prices(tickers: list[str], bench_symbol: str,
                     period: str | None = None) -> dict[str, pd.DataFrame]:
    """Télécharge l'OHLCV de tous les tickers (+ benchmark) en lots groupés.
    `period` par défaut = FILTERS["history_period"] ; surchargé par le backtest (ex. 2y)."""
    prices: dict[str, pd.DataFrame] = {}
    all_syms = tickers + [bench_symbol]
    chunk = FILTERS["download_chunk"]
    n_chunks = (len(all_syms) + chunk - 1) // chunk
    period = period or FILTERS["history_period"]

    for idx in range(0, len(all_syms), chunk):
        part = all_syms[idx:idx + chunk]
        got = 0
        # Retry + backoff exponentiel sur lot vide/throttlé (429) : un lot throttlé NE DOIT PAS
        # être abandonné silencieusement — sinon l'univers du run jugé est tronqué (biais).
        for attempt in range(FILTERS["download_retries"] + 1):
            try:
                data = yf.download(
                    part, period=period, interval="1d",
                    group_by="ticker", auto_adjust=True, actions=True,
                    threads=True, progress=False,
                )
            except Exception as e:
                data = None
                print(f"[download] lot {idx // chunk + 1}/{n_chunks} tentative {attempt+1} erreur: {e}")
            if data is not None and len(data):
                for sym in part:
                    df = _extract_symbol(data, sym)
                    if df is not None:
                        prices[sym] = df
                        got += 1
                if got:
                    break
            if attempt < FILTERS["download_retries"]:      # throttlé/vide → pause avant retry
                time.sleep(FILTERS["enrich_backoff_s"] * (2 ** attempt) + random.uniform(0, 1.0))
        if got == 0:                                        # pas de perte silencieuse (§ no silent caps)
            print(f"[download] lot {idx // chunk + 1}/{n_chunks} PERDU après retries — {len(part)} tickers absents")
        else:
            print(f"[download] lot {idx // chunk + 1}/{n_chunks} → {len(prices)} séries")
        time.sleep(FILTERS["rate_limit_s"])
    return prices


# ---------------------------------------------------------------------------
# Passe A — filtres prix/volume (aucun réseau, pur calcul sur le DataFrame)
# ---------------------------------------------------------------------------

def analyze_prices(ticker: str, df: pd.DataFrame,
                   bench_close: pd.Series | None) -> tuple[dict | None, str]:
    """Filtres durs prix/volume + signaux techniques. Retourne (signaux, 'ok') ou (None, raison)."""
    if df is None or "Close" not in df or "Volume" not in df:
        return None, "history:cols"
    close = df["Close"].dropna()
    volume = df["Volume"].dropna()
    if len(close) < FILTERS["vol_window_long"] + FILTERS["ma_slope_lookback"]:
        return None, f"history:{len(close)}j"

    # --- Mode de pool (Epic 2) : "tradability" (défaut) réduit les filtres durs à
    #     prix ≥ price_min + liquidité (protocole v2 §2) ; "legacy" conserve l'entonnoir v1. ---
    legacy = FILTERS["pool_mode"] == "legacy"

    # --- Prix : plancher (les deux modes) ; plafond price_max seulement en legacy ---
    price = _safe_float(close.iloc[-1])
    if price is None:
        return None, "price:None"
    if price < FILTERS["price_min"]:
        return None, f"price:{price:.2f}"
    if legacy and price > FILTERS["price_max"]:
        return None, f"price:{price:.2f}"

    # --- Perf 1 mois (~21 jours de bourse) : informatif ; borne dure seulement en legacy ---
    change_1m = _pct_change(close, 21)
    if change_1m is None:
        return None, "change_1m:None"
    if legacy and not (FILTERS["perf_1m_min"] <= change_1m <= FILTERS["perf_1m_max"]):
        return None, f"change_1m:{change_1m*100:.1f}%"

    # --- Liquidité (hard, les deux modes — définit la tradabilité) ---
    dollar_vol = _median_dollar_volume(close, volume, FILTERS["dollar_vol_window"])
    if dollar_vol is None or dollar_vol < FILTERS["dollar_vol_min"]:
        return None, f"liquidity:{int(dollar_vol) if dollar_vol else 0}"

    # --- Tendance : MA50 toujours calculée (signaux) ; pente = filtre dur seulement en legacy ---
    ma50 = _sma(close, FILTERS["ma_trend_window"])
    ma50_rising = _ma_rising(close, FILTERS["ma_trend_window"], FILTERS["ma_slope_lookback"])
    if ma50 is None:
        return None, "trend:no_ma"
    if legacy:
        if not ma50_rising:
            return None, "trend:down"
        if FILTERS["trend_require_above_ma"] and price <= ma50:
            return None, "trend:below_ma"

    # --- SMA20 : garde de stabilisation Phénix (close ≥ SMA20, protocole v2 §3) ---
    sma20 = _sma(close, FILTERS["profiles"]["phenix_sma_window"])

    # --- Signaux de scoring (prix/volume) ---
    change_1d = _pct_change(close, 1)

    vol_recent = float(volume.iloc[-FILTERS["vol_window_short"]:].mean())
    baseline = volume.iloc[-FILTERS["vol_window_long"]:-FILTERS["vol_window_short"]]  # sans recouvrement
    vol_base = float(baseline.median()) if len(baseline) else None
    vol_ratio = vol_recent / vol_base if vol_base and vol_base > 0 else None

    # --- Compression (capteur v2 par défaut ; v1 conservée derrière FILTERS["sensors_version"]) ---
    # atr_ratio = ATR20/ATR90 courant (affichage, commun v1/v2 ; fallback range Close-only).
    atr_ratio = None
    if FILTERS["use_atr_compression"]:
        atr_s = _atr(df, FILTERS["compression_window"])
        atr_l = _atr(df, FILTERS["compression_baseline"])
        if atr_s is not None and atr_l is not None and atr_l > 0:
            atr_ratio = atr_s / atr_l
    else:
        range_20 = _range_pct(close, FILTERS["compression_window"])
        range_90 = _range_pct(close, FILTERS["compression_baseline"])
        if range_20 is not None and range_90 is not None and range_90 > 0:
            atr_ratio = range_20 / range_90

    if FILTERS["sensors_version"] == "v2":
        # v2 : percentile du ratio vs la propre distribution 252j du titre (vrai ressort VCP).
        compression_pct = _compression_self_pct(
            df, FILTERS["compression_window"], FILTERS["compression_baseline"],
            FILTERS["compression_pct_lookback"], FILTERS["compression_pct_min_obs"])
        compressed = bool(compression_pct is not None
                          and compression_pct < FILTERS["compression_pct_threshold"])
        f_compression = compression_pct           # facteur continu (plus bas = plus comprimé)
    else:
        # v1 : seuil brut sur le ratio ATR20/ATR90.
        compression_pct = None
        compressed = bool(atr_ratio is not None and atr_ratio < FILTERS["compression_threshold"])
        f_compression = atr_ratio

    # --- Accumulation (capteur v2 par défaut ; v1 = OBV en hausse) ---
    if FILTERS["sensors_version"] == "v2":
        cmf = _cmf(df, FILTERS["cmf_window"])
        updown_ratio = _updown_vol_ratio(close, volume, FILTERS["updown_vol_window"])
        accumulation = bool(
            cmf is not None and cmf > FILTERS["cmf_pos_threshold"]
            and updown_ratio is not None and updown_ratio > FILTERS["updown_ratio_min"])
        f_accum = cmf                              # facteur continu (plus haut = plus d'afflux)
    else:
        cmf = None
        updown_ratio = None
        accumulation = bool(_obv_rising(close, volume, FILTERS["obv_lookback"]))
        f_accum = _accum_fraction(close, volume, FILTERS["obv_lookback"])

    # Position dans le range 52 sem. (informatif) + proche du pivot de la base RÉCENTE (scoring)
    pct_52w = _pct_of_high(close, FILTERS["high_window"])
    near_high = bool(pct_52w is not None and pct_52w >= FILTERS["near_high_pct"])
    pct_recent = _pct_of_high(close, FILTERS["pivot_window"])
    near_pivot = bool(pct_recent is not None and pct_recent >= FILTERS["near_pivot_pct"])

    # Peu étiré : prix proche de la MA50 (encore tôt dans le mouvement, pas après)
    low_ext = bool(ma50 and price <= ma50 * (1 + FILTERS["low_ext_pct"]))

    rs_outperf, rs_line_rising, rs_strength = _rs_metrics(
        close, bench_close, FILTERS["rs_return_window"], FILTERS["rs_line_lookback"]
    )
    rs_signal = bool(rs_outperf and rs_line_rising)
    rs_turning = bool(rs_line_rising)  # la RS repart (retournement) — scoring
    # Filtre RS dur seulement en legacy si rs_require=True (par défaut False → RS = scoring).
    if legacy and FILTERS["rs_require"] and rs_outperf is not None and not rs_signal:
        return None, "rs:weak"

    # --- Trigger : la cassure a lieu MAINTENANT (Sprint 3), distinct du setup/score ---
    triggered, days_since_trigger, pivot_level = _breakout(df, close, volume)

    # --- Facteurs CONTINUS pour le scoring percentile ---
    # (f_accum et f_compression sont calculés plus haut selon sensors_version)
    f_ext = (price / ma50 - 1) if ma50 else None

    # --- Features v3 dérivées du prix (Epic 3 S3) : close vs SMA20, penny stock récent ---
    close_vs_sma20 = (price / sma20 - 1) if sma20 else None   # T6 (stabilisation)
    sub_dollar_flag = bool(float(close.tail(63).min()) < 1.0)  # S5 (a récemment touché < 1 $)
    # Reverse split récent (ratio ∈ ]0,1[) depuis la colonne d'actions yfinance — signal de
    # détresse / conformité de cotation (S2). Point-in-time : df est déjà tronqué à la date as-of.
    reverse_split_flag = None
    if "Stock Splits" in df.columns:
        sp = df["Stock Splits"].tail(FILTERS["high_window"])
        reverse_split_flag = bool(((sp > 0) & (sp < 1)).any())

    signals = {
        "price": round(price, 2),
        "change_1d": round(change_1d, 4) if change_1d is not None else None,
        "change_1m": round(change_1m, 4),
        "dollar_volume": round(dollar_vol),
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "compressed": compressed,
        "accumulation": accumulation,
        # Capteurs v2 (affichage/diagnostic) :
        "atr_ratio": round(atr_ratio, 3) if atr_ratio is not None else None,
        "compression_pct": round(compression_pct, 3) if compression_pct is not None else None,
        "cmf": round(cmf, 3) if cmf is not None else None,
        "updown_vol_ratio": _safe_float(updown_ratio),  # None si +inf (aucun jour de baisse)
        "pct_52w_high": round(pct_52w, 3) if pct_52w is not None else None,
        "near_high": near_high,
        "pct_recent_high": round(pct_recent, 3) if pct_recent is not None else None,
        "near_pivot": near_pivot,
        "low_ext": low_ext,
        "ma50": round(ma50, 2),
        "sma20": round(sma20, 2) if sma20 is not None else None,  # garde Phénix (close ≥ SMA20)
        "price_above_ma50": bool(price > ma50),
        "rs_outperf": bool(rs_outperf) if rs_outperf is not None else None,
        "rs_line_rising": bool(rs_line_rising) if rs_line_rising is not None else None,
        "rs_turning": rs_turning,
        "rs_strength": round(rs_strength, 4) if rs_strength is not None else None,
        "rs_signal": rs_signal,
        # Trigger (Sprint 3) : cassure en cours (distinct du score de setup)
        "triggered": triggered,
        "days_since_trigger": days_since_trigger,
        "pivot_level": pivot_level,
        # Facteurs continus (scoring percentile) — valeurs selon sensors_version :
        "f_accum": f_accum,                 # v2: CMF ; v1: fraction volume net
        "f_atr_ratio": f_compression,       # v2: percentile auto-référencé ; v1: ATR20/ATR90
        "f_pct_recent": pct_recent,
        "f_ext": f_ext,
        "f_rs": rs_strength,
        # Features v3 dérivées du prix (Epic 3 S3) :
        "close_vs_sma20": round(close_vs_sma20, 4) if close_vs_sma20 is not None else None,
        "sub_dollar_flag": sub_dollar_flag,
        "reverse_split_flag": reverse_split_flag,   # S2 (reverse split récent = détresse)
    }
    return signals, "ok"


# ---------------------------------------------------------------------------
# Passe B — enrichissement fondamental (.info, un appel réseau par survivant)
# ---------------------------------------------------------------------------

def _fetch_info(ticker: str) -> dict:
    """
    Fetch .info avec retries + backoff exponentiel sur rate-limit Yahoo.
    Yahoo throttle agressivement l'endpoint .info : sans backoff, un scan complet
    fait bannir l'IP (YFRateLimitError sur tous les appels suivants).
    """
    last_exc = None
    for attempt in range(FILTERS["enrich_retries"] + 1):
        try:
            return yf.Ticker(ticker).info or {}
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "rate" in msg or "too many" in msg or "429" in msg:
                # backoff exponentiel + jitter : laisse Yahoo respirer
                time.sleep(FILTERS["enrich_backoff_s"] * (2 ** attempt) + random.uniform(0, 1.0))
                continue
            raise
    raise last_exc


def enrich_ticker(ticker: str, signals: dict) -> tuple[dict | None, str]:
    """Fetch .info, filtres market cap / exchange, signaux fondamentaux, scoring."""
    # Jitter aléatoire : désynchronise les threads pour éviter les rafales → throttle Yahoo
    if FILTERS["enrich_jitter_s"]:
        time.sleep(random.uniform(0, FILTERS["enrich_jitter_s"]))
    try:
        info = _fetch_info(ticker)
    except Exception as e:
        return None, f"exception:{type(e).__name__}"

    # --- Bourse autorisée ---
    exchange = info.get("exchange", "")
    if exchange not in FILTERS["allowed_exchanges"]:
        return None, f"exchange:{exchange or 'N/A'}"

    # --- Market cap ---
    mc_raw = _safe_float(info.get("marketCap"))
    if mc_raw is None:
        return None, "market_cap:None"
    mc_m = mc_raw / 1e6
    if not (FILTERS["market_cap_min_m"] <= mc_m <= FILTERS["market_cap_max_m"]):
        return None, f"market_cap:{mc_m:.0f}M"

    # --- IPO year — informatif ---
    ipo_epoch = info.get("firstTradeDateEpochUtc")
    ipo_year = datetime.fromtimestamp(ipo_epoch, tz=timezone.utc).year if ipo_epoch else None

    # --- Bilan : None si donnée absente (ne pas pénaliser l'absence) ---
    total_cash = _safe_float(info.get("totalCash"), None)
    total_debt = _safe_float(info.get("totalDebt"), None)
    cash_positive = None if (total_cash is None or total_debt is None) else bool(total_cash > total_debt)

    # --- Insiders / short / revenus / float ---
    # insider_pct (% détention) : AFFICHAGE informatif seulement — plus au scoring depuis S5.
    insider_pct = (_safe_float(info.get("heldPercentInsiders"), 0) or 0) * 100
    insider_buying = bool(insider_pct > FILTERS["insider_pct_min"])

    # Achats nets d'insiders (EDGAR Form 4) — remplace le % au scoring. None = neutre (jamais fatal).
    insider_net = None
    try:
        from edgar import net_insider_buying
        edgar_info = net_insider_buying(ticker)
        if edgar_info is not None:
            insider_net = edgar_info.get("net_buying")
    except Exception as e:
        print(f"[edgar] {ticker} erreur (ignorée) : {type(e).__name__}")
    insider_net_buying_pos = bool(insider_net is not None and insider_net > 0)

    short_interest_pct = (_safe_float(info.get("shortPercentOfFloat"), 0) or 0) * 100
    revenue_growth = _safe_float(info.get("revenueGrowth"))
    float_shares = _safe_float(info.get("floatShares"), None)
    low_float = bool(float_shares is not None and float_shares < FILTERS["float_max"])

    stock = {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": exchange,
        "market_cap_m": round(mc_m, 1),
        "insider_pct": round(insider_pct, 2),
        "insider_buying": insider_buying,          # informatif (basé sur le % détention)
        "insider_net_buying": insider_net,         # $ nets EDGAR Form 4 (P−S) ; None = neutre
        "insider_net_buying_pos": insider_net_buying_pos,  # bool utilisé au scoring (achats nets > 0)
        "short_interest_pct": round(short_interest_pct, 2),
        "revenue_growth": round(revenue_growth, 4) if revenue_growth is not None else None,
        "float_shares": int(float_shares) if float_shares is not None else None,
        "low_float": low_float,
        "cash_positive": cash_positive,
        "cash_bin": (1.0 if cash_positive is True else (0.0 if cash_positive is False else None)),
        "ipo_year": ipo_year,
        "catalyst_type": None,
        "catalyst_date": None,
        **signals,  # inclut les facteurs continus f_accum / f_atr_ratio / f_pct_recent / f_ext / f_rs
    }
    # Le score (percentile) est calculé sur l'ENSEMBLE des candidats dans run_scan,
    # pas ici (un percentile n'a de sens que par rapport au vivier). On pose positives/flags.
    stock["positives"], stock["flags"] = _build_positives_flags(stock)
    return stock, "ok"


# ---------------------------------------------------------------------------
# Scan complet (orchestration 2 passes)
# ---------------------------------------------------------------------------

def run_scan(tickers: list[str] | None = None) -> dict:
    """
    Lance le scan. Si tickers est None, découverte dynamique via discover_tickers().
    Passe A (batch prix) → survivants → Passe B (.info) → JSON trié par score.
    """
    watchlist = tickers if tickers is not None else discover_tickers()
    total = len(watchlist)

    scan_state.update({"scanning": True, "progress": 0, "total": total, "phase": "download"})
    rejection_counts: dict[str, int] = {}

    print(f"\n{'='*55}")
    print(f"  SmallCaps Screener — univers de {total} tickers")
    print(f"{'='*55}")

    # --- Téléchargement prix en batch (+ benchmark) ---
    prices = _download_prices(watchlist, FILTERS["rs_benchmark"])
    bench_df = prices.pop(FILTERS["rs_benchmark"], None)
    bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None
    if bench_close is None:
        print(f"[benchmark] {FILTERS['rs_benchmark']} indisponible → force relative ignorée ce scan")

    # --- Passe A : filtres prix/volume sur tout l'univers ---
    scan_state["phase"] = "price_filter"
    survivors: list[tuple[str, dict]] = []
    for ticker in watchlist:
        df = prices.get(ticker)
        if df is None:
            rejection_counts["no_data"] = rejection_counts.get("no_data", 0) + 1
            continue
        signals, reason = analyze_prices(ticker, df, bench_close)
        if signals:
            survivors.append((ticker, signals))
        else:
            cat = reason.split(":")[0]
            rejection_counts[cat] = rejection_counts.get(cat, 0) + 1

    # --- Sélection des survivants à enrichir (Passe B coûteuse) ---
    # Epic 2, mode "tradability" : la sélection est faite par les DÉTECTEURS DE PROFILS
    # (Fusée/Phénix, percentiles cross-sectionnels du protocole v2 §3) — seuls les MEMBRES
    # sont affichés/enrichis, classés par force de profil. Mode "legacy" : ancien classement
    # par score technique percentile (reproductibilité du backtest v1).
    n_tradable = len(survivors)
    if FILTERS["pool_mode"] == "legacy":
        tech_scores = _select_scores([sig for _, sig in survivors])
        ranked = sorted(zip(survivors, tech_scores),
                        key=lambda x: (x[1], x[0][1].get("dollar_volume") or 0), reverse=True)
        survivors = [s for s, _ in ranked]
    else:
        from profiles import detect_profiles, rank_members
        detect_profiles([sig for _, sig in survivors])
        survivors = rank_members(survivors)
        rejection_counts["not_profiled"] = n_tradable - len(survivors)

    n_all = len(survivors)
    capped = survivors[:FILTERS["enrich_max"]]
    if n_all > len(capped):
        rejection_counts["below_cutoff"] = n_all - len(capped)
    label = "top score technique" if FILTERS["pool_mode"] == "legacy" else "membres de profil"
    print(f"\n[Passe A] {n_tradable} tradables / {total} tickers → {n_all} {label} → "
          f"{len(capped)} enrichis")

    # --- Passe B : enrichissement .info sur les survivants retenus (parallèle, borné) ---
    scan_state.update({"phase": "enrich", "progress": 0, "total": len(capped)})
    candidates = []
    n_surv = len(capped)
    with ThreadPoolExecutor(max_workers=FILTERS["enrich_workers"]) as pool:
        futures = {pool.submit(enrich_ticker, tk, sig): tk for tk, sig in capped}
        for i, fut in enumerate(as_completed(futures), 1):
            scan_state["progress"] = i
            bar_len = 40
            filled = int(bar_len * i / max(n_surv, 1))
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r[{bar}] {i}/{n_surv}  {futures[fut]:<8}", end="", flush=True)

            stock, reason = fut.result()
            if stock:
                candidates.append(stock)
            else:
                cat = reason.split(":")[0]
                rejection_counts[cat] = rejection_counts.get(cat, 0) + 1

    print(f"\n{'='*55}")
    print(f"  {len(candidates)} candidats trouvés sur {total} tickers de l'univers")
    print(f"{'='*55}")
    print("\n  Rejections par filtre :")
    for cat, count in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<20} {count:>4} tickers")
    print()

    # Score PERCENTILE final (technique + fondamental) calculé sur l'ENSEMBLE des candidats,
    # puis tri décroissant (magnitude RS en départage).
    _score_candidates(candidates)
    # Sprint 3 : setup_score = nom canonique du score de setup (technique + fondamental).
    # `score` est CONSERVÉ tel quel (l'UI actuelle le lit) ; setup_score en est l'alias.
    for s in candidates:
        s["setup_score"] = s["score"]

    # Epic 3 (S4) : score de survie v3 — pose p_explode (None tant qu'aucun modèle entraîné n'est
    # présent) + survival_risk sur CHAQUE candidat. Additif : ne touche ni aux profils ni au score.
    from scoring import score_candidates, load_model
    model = load_model(str(Path(DATA_DIR) / "model_v3.json"))
    score_candidates(candidates, model)

    if model is not None:
        # v3 : le modèle pilote l'ordre (dormant tant que S5 n'a pas produit model_v3.json).
        candidates.sort(key=lambda x: (x.get("p_explode") or 0.0,
                                       x.get("profile_strength") or 0.0), reverse=True)
    elif FILTERS["pool_mode"] == "legacy":
        candidates.sort(key=lambda x: (x["score"], x.get("rs_strength") or 0), reverse=True)
    else:
        # Epic 2 : affichage classé par FORCE DE PROFIL. setup_score reste calculé pour
        # continuité mais ne pilote plus ni la sélection ni l'ordre.
        candidates.sort(key=lambda x: (x.get("profile_strength") or 0.0,
                                       x.get("rs_strength") or 0), reverse=True)

    output = {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "universe_size": total,
        "total_scanned": total,
        "survivors_price_filter": n_tradable,   # ont passé les filtres durs (univers tradable)
        "profile_members": n_all,               # membres Fusée/Phénix retenus (== tradables en legacy)
        "pool_mode": FILTERS["pool_mode"],
        "v3_model": model is not None,   # True → p_explode pilote l'ordre (Epic 3)
        "enriched": n_surv,
        "candidates": len(candidates),
        "stocks": candidates,
        "rejection_stats": rejection_counts,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    _write_snapshot(output)   # historique daté pour le suivi de performance

    # --- Alerte Telegram sur les NOUVEAUX déclenchés (Sprint 3) — jamais fatal ---
    # Import paresseux : évite un cycle d'import (alerts importe FILTERS d'ici).
    try:
        from alerts import notify_new_triggers
        alerted = notify_new_triggers(candidates)
        if alerted:
            print(f"[alert] {len(alerted)} déclenché(s) notifié(s) : {', '.join(alerted)}")
    except Exception as e:
        print(f"[alert] erreur (ignorée) : {e}")

    scan_state.update({"scanning": False, "phase": "idle"})
    return output


def _write_snapshot(output: dict) -> None:
    """
    Enregistre un instantané daté des candidats dans data/history/ pour le suivi de
    performance dans le temps. Chaque scan = un fichier. Ne fait jamais échouer le scan.
    """
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        picks = [
            {
                "ticker": s["ticker"], "score": s["score"], "price": s["price"],
                "setup_score": s.get("setup_score", s.get("score")),
                "triggered": s.get("triggered"),
                "days_since_trigger": s.get("days_since_trigger"),
                "sector": s.get("sector"),
                "accumulation": s.get("accumulation"), "compressed": s.get("compressed"),
                "near_pivot": s.get("near_pivot"), "rs_strength": s.get("rs_strength"),
                # Profils tail-hunting (Epic 2) — nécessaires aux sleeves du tracker (Sprint 4)
                "profile": s.get("profile"),
                "is_fusee": s.get("is_fusee"), "is_phenix": s.get("is_phenix"),
                "fusee_event": s.get("fusee_event"),
                "fusee_strength": s.get("fusee_strength"),
                "phenix_strength": s.get("phenix_strength"),
                "profile_strength": s.get("profile_strength"),
            }
            for s in output.get("stocks", [])
        ]
        snap = {
            "scanned_at": output["scanned_at"],
            "candidates": len(picks),
            "picks": picks,
        }
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        (HISTORY_DIR / f"{ts}.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False))
        print(f"[snapshot] {len(picks)} sélections → history/{ts}.json")
    except Exception as e:
        print(f"[snapshot] erreur (ignorée): {e}")


if __name__ == "__main__":
    run_scan()
