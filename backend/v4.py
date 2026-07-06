"""
Cohorte v4 — « washout reversion basket » (docs/backtest_protocol_v4.md, SIGNÉ 2026-07-06).

INSTRUMENTATION SEULE (Validation C, protocole §4) : à chaque scan on identifie les titres
qui passent les 4 règles gelées (§2) et on les CONSIGNE dans le snapshot daté. Aucun trade,
aucune prétention, aucun effet sur la sélection/le tri/les alertes existants — c'est la
comptabilité qui permettra le jugement forward (première lecture ≥ 12 mois).

Les constantes sont GELÉES par le protocole signé — hors FILTERS volontairement : un seuil
jugé n'est pas un réglage. Toute modification = révision v4.1 + remise à zéro du chrono.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# §2 — règles d'entrée (gelées)
V4_PRICE_MAX = 8.0      # §2.1  prix ≤ 8 $
V4_CHG1M_MAX = -0.03    # §2.3  chute ≥ 3 % sur ~1 mois (change_1m ≤ −3 %)
V4_MKT_WINDOW = 21      # §2.4  tendance IWM sur 21 séances (< 0 requis)

# §4 — champs observationnels (jamais jugés, jamais des règles d'entrée)
V4_BETA_WINDOW = 126    # bêta/corrélation sur ~6 mois de séances
V4_BETA_MIN_OBS = 60    # minimum de rendements alignés pour un bêta honnête

# §A.6 — checkpoint de trajectoire affiché (gelé : seuil +3 % à 1 semaine = 5 séances).
# Information uniquement — jamais une règle de vente (les stops détruisent le rendement, A.6).
V4_CHECKPOINT_DAY = 5
V4_CHECKPOINT_THR = 0.03
V4_HORIZON = 63         # fenêtre de jugement fwd63 (protocole §4)
PRELIST_MAX = 12        # taille max de la pré-liste affichée (jours haussiers)


def market_return_21d(bench_close: pd.Series | None) -> float | None:
    """Rendement du benchmark sur les V4_MKT_WINDOW dernières séances ; None si insuffisant."""
    if bench_close is None or len(bench_close) < V4_MKT_WINDOW + 1:
        return None
    return float(bench_close.iloc[-1]) / float(bench_close.iloc[-(V4_MKT_WINDOW + 1)]) - 1


def _beta_corr(close: pd.Series, bench_close: pd.Series) -> tuple[float | None, float | None]:
    """Bêta et corrélation des rendements quotidiens vs benchmark (fenêtre V4_BETA_WINDOW)."""
    joined = pd.concat([close.pct_change(), bench_close.pct_change()],
                       axis=1, join="inner").dropna().tail(V4_BETA_WINDOW)
    if len(joined) < V4_BETA_MIN_OBS:
        return None, None
    sv = joined.iloc[:, 0] - joined.iloc[:, 0].mean()
    bv = joined.iloc[:, 1] - joined.iloc[:, 1].mean()
    var_b = float((bv * bv).mean())
    var_s = float((sv * sv).mean())
    if var_b <= 0 or var_s <= 0:
        return None, None
    cov = float((sv * bv).mean())
    return cov / var_b, cov / (var_b * var_s) ** 0.5


def _passes_price_rules(sig: dict) -> bool:
    """Règles-titre §2.1 + §2.3 (prix ≤ 8 $, chute 1 mois ≤ −3 %) — sans EDGAR."""
    price, chg = sig.get("price"), sig.get("change_1m")
    return (price is not None and chg is not None
            and price <= V4_PRICE_MAX and chg <= V4_CHG1M_MAX)


def build_cohort(tradables: list[tuple[str, dict]], prices: dict,
                 bench_close: pd.Series | None) -> tuple[list[dict], str, float | None, list[dict]]:
    """
    Cohorte v4 du jour sur le pool tradable complet (avant toute sélection de profil).
    Renvoie (cohorte, note lisible, mkt21, pré-liste). Cohorte vide + note explicite si le
    marché monte ou si le benchmark manque (§2.4 : pas de bénéfice du doute). Les jours
    haussiers, la pré-liste donne les titres passant les règles-titre SEULES (dilution non
    vérifiée — zéro appel EDGAR ces jours-là), triés par chute, plafonnés à PRELIST_MAX.

    Coût réseau : EDGAR n'est interrogé que pour les titres passant déjà les règles prix,
    et uniquement les jours de marché baissier (cache disque + mémos edgar existants).
    """
    mkt = market_return_21d(bench_close)
    if mkt is None:
        return [], "benchmark indisponible → cohorte vide (§2.4)", None, []
    if mkt >= 0:
        prelist = sorted((
            {"ticker": tk, "price": sig["price"], "change_1m": sig["change_1m"]}
            for tk, sig in tradables if _passes_price_rules(sig)
        ), key=lambda e: e["change_1m"])[:PRELIST_MAX]
        return ([], f"marché haussier (IWM 21j {mkt:+.1%}) → la méthode ne s'applique pas (§2.4)",
                mkt, prelist)

    import edgar

    cohort: list[dict] = []
    for tk, sig in tradables:
        if not _passes_price_rules(sig):
            continue
        price, chg = sig["price"], sig["change_1m"]
        try:
            surv = edgar.survival_signals(tk)
        except Exception:
            surv = None
        dil = surv.get("dilution_flag") if surv else None
        if dil is not False:  # §2.2 — EDGAR muet (None) ⇒ non qualifié
            continue

        beta = corr = resid = None
        df = prices.get(tk)
        if df is not None and "Close" in df and bench_close is not None:
            beta, corr = _beta_corr(df["Close"].dropna(), bench_close)
            if beta is not None:
                resid = chg - beta * mkt

        cohort.append({
            "ticker": tk,
            "price": price,
            "change_1m": chg,
            "mkt21": round(mkt, 4),
            "beta": round(beta, 3) if beta is not None else None,
            "corr": round(corr, 3) if corr is not None else None,
            "resid": round(resid, 4) if resid is not None else None,
            "margins": {  # distance aux seuils — affichage §3, jamais un re-classement
                "price": round(V4_PRICE_MAX - price, 2),
                "change_1m": round(V4_CHG1M_MAX - chg, 4),
            },
        })

    # Ordre indicatif §A.5 : plus survendu d'abord (résidu le plus négatif) ; sans bêta → fin.
    cohort.sort(key=lambda e: (e["resid"] is None, e["resid"] if e["resid"] is not None else 0.0))
    return cohort, f"marché baissier (IWM 21j {mkt:+.1%}) → {len(cohort)} qualifiés", mkt, []


# ---------------------------------------------------------------------------
# Suivi des cohortes passées (affichage §3 — information, jamais un ordre de vente)
# ---------------------------------------------------------------------------

def _load_cohort_entries(history_dir: Path) -> dict[str, dict]:
    """
    Première entrée par ticker depuis les snapshots datés : {ticker: {entry_date, price,
    resid, beta}}. Les snapshots illisibles ou sans cohorte sont ignorés (jamais fatal).
    """
    first: dict[str, dict] = {}
    try:
        files = sorted(Path(history_dir).glob("*.json"))
    except Exception:
        return {}
    for f in files:  # ordre chronologique (nom = horodatage) → le premier vu gagne
        try:
            snap = json.loads(f.read_text())
        except Exception:
            continue
        day = (snap.get("scanned_at") or "")[:10]
        for e in snap.get("v4_cohort") or []:
            tk = e.get("ticker")
            if tk and tk not in first and e.get("price"):
                first[tk] = {"entry_date": day, "entry_price": e["price"],
                             "resid": e.get("resid"), "beta": e.get("beta")}
    return first


def build_tracking(prices: dict, history_dir: Path) -> list[dict]:
    """
    Position de chaque titre de cohorte vs les trajectoires historiques (protocole §A.6).
    Jours de bourse comptés sur l'index du titre lui-même (robuste aux jours fériés).
    Un titre sans données de prix aujourd'hui est signalé (délisting possible = information).
    """
    out: list[dict] = []
    for tk, ent in _load_cohort_entries(history_dir).items():
        row = {"ticker": tk, **ent, "days_held": None, "ret": None,
               "checkpoint": None, "status": "données absentes (délisting ?)"}
        df = prices.get(tk)
        if df is not None and "Close" in df:
            close = df["Close"].dropna()
            # Comparaison robuste : Timestamp explicite, aligné sur le fuseau de l'index
            # (yfinance renvoie parfois un index tz-aware — comparer à un naïf lèverait).
            try:
                entry_ts = pd.Timestamp(ent["entry_date"])
                tz = getattr(close.index, "tz", None)
                if tz is not None and entry_ts.tzinfo is None:
                    entry_ts = entry_ts.tz_localize(tz)
                after = close[close.index > entry_ts]
            except Exception:
                after = close.iloc[0:0]
            if len(after):
                days = len(after)
                cur = float(after.iloc[-1])
                row["days_held"] = days
                row["ret"] = round(cur / ent["entry_price"] - 1, 4)
                if days >= V4_HORIZON:
                    d63 = float(after.iloc[V4_HORIZON - 1])
                    r63 = d63 / ent["entry_price"] - 1
                    row["checkpoint"] = "fenêtre 63j close"
                    row["status"] = ("explosion (≥ +100 %)" if r63 >= 1.0
                                     else "crash (≤ −50 %)" if r63 <= -0.5 else "close")
                    row["ret_63"] = round(r63, 4)
                elif days >= V4_CHECKPOINT_DAY:
                    r5 = float(after.iloc[V4_CHECKPOINT_DAY - 1]) / ent["entry_price"] - 1
                    row["checkpoint"] = "1 semaine (seuil +3 %)"
                    row["ret_5"] = round(r5, 4)
                    row["status"] = "au-dessus" if r5 >= V4_CHECKPOINT_THR else "sous le seuil"
                else:
                    row["checkpoint"] = "trop tôt"
                    row["status"] = f"J+{days} — premier checkpoint à J+{V4_CHECKPOINT_DAY}"
        out.append(row)
    out.sort(key=lambda r: r["entry_date"], reverse=True)
    return out
