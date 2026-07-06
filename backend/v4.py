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

import pandas as pd

# §2 — règles d'entrée (gelées)
V4_PRICE_MAX = 8.0      # §2.1  prix ≤ 8 $
V4_CHG1M_MAX = -0.03    # §2.3  chute ≥ 3 % sur ~1 mois (change_1m ≤ −3 %)
V4_MKT_WINDOW = 21      # §2.4  tendance IWM sur 21 séances (< 0 requis)

# §4 — champs observationnels (jamais jugés, jamais des règles d'entrée)
V4_BETA_WINDOW = 126    # bêta/corrélation sur ~6 mois de séances
V4_BETA_MIN_OBS = 60    # minimum de rendements alignés pour un bêta honnête


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


def build_cohort(tradables: list[tuple[str, dict]], prices: dict,
                 bench_close: pd.Series | None) -> tuple[list[dict], str]:
    """
    Cohorte v4 du jour sur le pool tradable complet (avant toute sélection de profil).
    Renvoie (cohorte, note lisible). Cohorte vide + note explicite si le marché monte ou si
    le benchmark manque (§2.4 : pas de bénéfice du doute).

    Coût réseau : EDGAR n'est interrogé que pour les titres passant déjà les règles prix,
    et uniquement les jours de marché baissier (cache disque + mémos edgar existants).
    """
    mkt = market_return_21d(bench_close)
    if mkt is None:
        return [], "benchmark indisponible → cohorte vide (§2.4)"
    if mkt >= 0:
        return [], f"marché haussier (IWM 21j {mkt:+.1%}) → la méthode ne s'applique pas (§2.4)"

    import edgar

    cohort: list[dict] = []
    for tk, sig in tradables:
        price = sig.get("price")
        chg = sig.get("change_1m")
        if price is None or chg is None or price > V4_PRICE_MAX or chg > V4_CHG1M_MAX:
            continue
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
    return cohort, f"marché baissier (IWM 21j {mkt:+.1%}) → {len(cohort)} qualifiés"
