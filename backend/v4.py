"""
Cohorte v4 — « washout reversion basket » (protocole v4, SIGNÉ 2026-07-06).

INSTRUMENTATION SEULE (Validation C, protocole §4) : à chaque scan on identifie les titres
qui passent les 4 règles gelées (§2) et on les CONSIGNE dans le snapshot daté. Aucun trade,
aucune prétention, aucun effet sur la sélection/le tri/les alertes existants — c'est la
comptabilité qui permettra le jugement forward (première lecture ≥ 12 mois).

Les constantes GELÉES ne vivent plus dans le code public (Epic 6 S2) : les defaults de
CFG sont des placeholders NEUTRES (price_max 0.0 ⇒ aucun titre ne qualifie, l'instrumen-
tation tourne à vide plutôt qu'avec des seuils faux). Les vraies valeurs — identiques bit
à bit au protocole signé, archivé hors repo — arrivent de config/local.yml (section v4:)
via l'overlay chargé au démarrage. Toute modification des valeurs réelles reste une
révision v4.1 + remise à zéro du chrono.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Defaults NEUTRES — les valeurs gelées réelles arrivent de config/local.yml (v4:).
# La structure des règles reste lisible ici (décision d'epic) ; seules les valeurs
# sont secrètes. display = textes/chiffres gelés servis au frontend via le payload.
CFG: dict = {
    "price_max": 0.0,       # §2.1  prix ≤ seuil — 0.0 ⇒ rien ne qualifie sans config
    "chg1m_max": 0.0,       # §2.3  chute 1 mois ≤ seuil
    "mkt_window": 21,       # §2.4  fenêtre (séances) de la règle marché IWM
    "beta_window": 126,     # §4    bêta/corrélation (~6 mois, observationnel)
    "beta_min_obs": 60,     # §4    minimum de rendements alignés pour un bêta honnête
    "checkpoint_day": 5,    # §A.6  checkpoint de trajectoire (affichage, jamais une vente)
    "checkpoint_thr": 0.0,  # §A.6  seuil du checkpoint
    "horizon": 63,          # §4    fenêtre de jugement fwd63
    "prelist_max": 12,      # taille max de la pré-liste affichée (jours haussiers)
    "display": {
        "depth_scale": 1.0,  # échelle de la jauge résidu du frontend
        "stats": {"esperance": "", "mediane": "", "p_explode": "", "p_crash": "", "t": ""},
        "gloss": {
            "regles": "", "research": "", "esperance": "", "p_explode": "", "p_crash": "",
            "tstat": "", "profondeur": "", "rule_price": "", "rule_chg": "", "rule_mkt": "",
            "checkpoint": "", "checkpoint_above": "", "checkpoint_below": "",
            "stops_footer": "", "first_pick": "",
        },
    },
}


def market_return_21d(bench_close: pd.Series | None) -> float | None:
    """Rendement du benchmark sur les CFG['mkt_window'] dernières séances ; None si insuffisant."""
    w = CFG["mkt_window"]
    if bench_close is None or len(bench_close) < w + 1:
        return None
    return float(bench_close.iloc[-1]) / float(bench_close.iloc[-(w + 1)]) - 1


def _beta_corr(close: pd.Series, bench_close: pd.Series) -> tuple[float | None, float | None]:
    """Bêta et corrélation des rendements quotidiens vs benchmark (fenêtre beta_window)."""
    joined = pd.concat([close.pct_change(), bench_close.pct_change()],
                       axis=1, join="inner").dropna().tail(CFG["beta_window"])
    if len(joined) < CFG["beta_min_obs"]:
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
    """Règles-titre §2.1 + §2.3 (prix, chute 1 mois) — sans EDGAR."""
    price, chg = sig.get("price"), sig.get("change_1m")
    return (price is not None and chg is not None
            and price <= CFG["price_max"] and chg <= CFG["chg1m_max"])


def build_cohort(tradables: list[tuple[str, dict]], prices: dict,
                 bench_close: pd.Series | None) -> tuple[list[dict], str, float | None, list[dict]]:
    """
    Cohorte v4 du jour sur le pool tradable complet (avant toute sélection de profil).
    Renvoie (cohorte, note lisible, mkt, pré-liste). Cohorte vide + note explicite si le
    marché monte ou si le benchmark manque (§2.4 : pas de bénéfice du doute). Les jours
    haussiers, la pré-liste donne les titres passant les règles-titre SEULES (dilution non
    vérifiée — zéro appel EDGAR ces jours-là), triés par chute, plafonnés à prelist_max.

    Coût réseau : EDGAR n'est interrogé que pour les titres passant déjà les règles prix,
    et uniquement les jours de marché baissier (cache disque + mémos edgar existants).
    """
    w = CFG["mkt_window"]
    mkt = market_return_21d(bench_close)
    if mkt is None:
        return [], "benchmark indisponible → cohorte vide (§2.4)", None, []
    if mkt >= 0:
        prelist = sorted((
            {"ticker": tk, "price": sig["price"], "change_1m": sig["change_1m"]}
            for tk, sig in tradables if _passes_price_rules(sig)
        ), key=lambda e: e["change_1m"])[:CFG["prelist_max"]]
        return ([], f"marché haussier (IWM {w}j {mkt:+.1%}) → la méthode ne s'applique pas (§2.4)",
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
                "price": round(CFG["price_max"] - price, 2),
                "change_1m": round(CFG["chg1m_max"] - chg, 4),
            },
        })

    # Ordre indicatif §A.5 : plus survendu d'abord (résidu le plus négatif) ; sans bêta → fin.
    cohort.sort(key=lambda e: (e["resid"] is None, e["resid"] if e["resid"] is not None else 0.0))
    return cohort, f"marché baissier (IWM {w}j {mkt:+.1%}) → {len(cohort)} qualifiés", mkt, []


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
    cp_day, cp_thr, horizon = CFG["checkpoint_day"], CFG["checkpoint_thr"], CFG["horizon"]
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
                if days >= horizon:
                    d63 = float(after.iloc[horizon - 1])
                    r63 = d63 / ent["entry_price"] - 1
                    row["checkpoint"] = f"fenêtre {horizon}j close"
                    row["status"] = ("explosion (≥ +100 %)" if r63 >= 1.0
                                     else "crash (≤ −50 %)" if r63 <= -0.5 else "close")
                    row["ret_63"] = round(r63, 4)
                elif days >= cp_day:
                    r5 = float(after.iloc[cp_day - 1]) / ent["entry_price"] - 1
                    row["checkpoint"] = f"1 semaine (seuil {cp_thr:+.0%})"
                    row["ret_5"] = round(r5, 4)
                    row["status"] = "au-dessus" if r5 >= cp_thr else "sous le seuil"
                else:
                    row["checkpoint"] = "trop tôt"
                    row["status"] = f"J+{days} — premier checkpoint à J+{cp_day}"
        out.append(row)
    out.sort(key=lambda r: r["entry_date"], reverse=True)
    return out
