"""
Cohortes v5 — « washout multi-fenêtres » (protocole v5, SIGNÉ 2026-07-09).

INSTRUMENTATION SEULE (Validation D, protocole §9) : à chaque scan on identifie, pour
chacune des fenêtres pré-déclarées, les titres qui passent les 6 règles gelées (§8) et on
les CONSIGNE dans le snapshot daté. Aucun trade, aucun effet sur la sélection/le tri/les
alertes existants ni sur la cohorte v4 (qui continue, protocole distinct).

Les constantes GELÉES ne vivent plus dans le code public (Epic 6 S2) : les defaults de
CFG sont des placeholders NEUTRES (price_max 0.0 ⇒ aucun titre ne qualifie, flash_thr
−1.0 ⇒ drapeau ⚡ jamais levé). Les vraies valeurs — identiques bit à bit au protocole
signé, archivé hors repo — arrivent de config/local.yml (section v5:) via l'overlay
chargé au démarrage. Toute modification des valeurs réelles reste une révision v5.1 +
remise à zéro du chrono forward.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import lifecycle
from scoring import risk_markers

# Defaults NEUTRES — les valeurs gelées réelles arrivent de config/local.yml (v5:).
# Les fenêtres restent lisibles ici (structure affichée par le sélecteur de l'UI) ;
# seules les valeurs de règles sont secrètes. display = textes/chiffres gelés servis
# au frontend via le payload.
CFG: dict = {
    "price_max": 0.0,       # §8.1  prix ≤ seuil — 0.0 ⇒ rien ne qualifie sans config
    "chg_max": 0.0,         # §8.3  chute ≤ seuil sur la fenêtre (clôtures ajustées)
    "windows": [7, 14, 21],  # §8   variantes pré-déclarées
    "cmf_min": 0.0,         # §8.5  flux CMF(20) strictement au-dessus du seuil
    "volcalm_max": 0.0,     # §8.6  chute sans volume (ratio ≤ seuil)
    "volcalm_base": 60,     # §8.6  base de volume : séances précédant la fenêtre
    "flash_window": 3,      # §7    drapeau ⚡ (affichage seul, jamais une règle)
    "flash_thr": -1.0,      # §7    −1.0 = inatteignable ⇒ ⚡ jamais levé sans config
    "checkpoint_day": 5,    # §9    suivi (mêmes conventions que v4 : information)
    "checkpoint_thr": 0.0,  # §9
    "horizon": 63,          # §9    fenêtre de jugement fwd63
    "prelist_max": 12,      # taille max de la pré-liste affichée
    "display": {
        "primary_window": 0,  # variante primaire au jugement (0 = non configurée)
        "stats": {
            7: {"esperance": "", "mediane": "", "p_explode": "", "p_crash": "", "t": "", "n": 0},
            14: {"esperance": "", "mediane": "", "p_explode": "", "p_crash": "", "t": "", "n": 0},
            21: {"esperance": "", "mediane": "", "p_explode": "", "p_crash": "", "t": "", "n": 0},
        },
        "gloss": {
            "regles": "", "research": "", "mediane": "", "chg": "", "vol_calme": "",
            "cmf": "", "flash": "", "crash": "", "tracking": "", "mkt_switch": "",
            # Epic 8 S3 — infobulle : UNE phrase citant le seuil du drapeau ⚡.
            "tip_flash": "",
        },
    },
}



def _ret(close: pd.Series | None, w: int) -> float | None:
    """Rendement sur les w dernières séances ; None si historique insuffisant."""
    if close is None or len(close) < w + 1:
        return None
    return float(close.iloc[-1]) / float(close.iloc[-(w + 1)]) - 1


def _chg_w(df: pd.DataFrame | None, w: int) -> float | None:
    """Chute du titre sur la fenêtre, clôtures ajustées."""
    if df is None or "Close" not in df:
        return None
    return _ret(df["Close"].dropna(), w)


def _vol_calm(df: pd.DataFrame | None, w: int) -> float | None:
    """Volume moyen de la fenêtre / volume moyen des séances précédentes (§8.6)."""
    if df is None or "Volume" not in df:
        return None
    vol = df["Volume"].dropna()
    if len(vol) < w + 30:  # base minimale pour une moyenne honnête
        return None
    recent = vol.iloc[-w:]
    base = vol.iloc[-(w + CFG["volcalm_base"]):-w]
    b = float(base.mean())
    if b <= 0:
        return None
    return float(recent.mean()) / b


def _title_entry(tk: str, sig: dict, df: pd.DataFrame | None, w: int) -> dict | None:
    """Règles-titre §8.1 + §8.3 + §8.5 + §8.6 (tout sauf EDGAR). None si non qualifié."""
    price, cmf = sig.get("price"), sig.get("cmf")
    if price is None or price > CFG["price_max"]:
        return None
    chg = _chg_w(df, w)
    if chg is None or chg > CFG["chg_max"]:
        return None
    if cmf is None or cmf <= CFG["cmf_min"]:
        return None
    vc = _vol_calm(df, w)
    if vc is None or vc > CFG["volcalm_max"]:
        return None
    return {"ticker": tk, "price": price, "chg": round(chg, 4),
            "cmf": round(cmf, 3), "vol_calm": round(vc, 2)}


def build_cohorts(tradables: list[tuple[str, dict]], prices: dict,
                  bench_close: pd.Series | None) -> dict:
    """
    Les cohortes v5 du jour sur le pool tradable complet, plus le drapeau ⚡.
    Structure renvoyée (consignée telle quelle dans le snapshot) :
      {"windows": {"7": {"mkt", "note", "cohort", "prelist"}, ...},
       "flash": bool, "flash_ret3": float|None}
    `note` est un CODE + ses variables (Epic 8 S1), traduit par le frontend.
    Les jours haussiers (ou benchmark manquant), la cohorte est vide (pas de
    bénéfice du doute) ; la pré-liste montre les titres passant les règles-titre seules
    (zéro appel EDGAR ces jours-là). EDGAR n'est interrogé que pour les candidats des
    fenêtres baissières (cache disque + mémos edgar existants — coût marginal ~nul).
    """
    bench = bench_close.dropna() if bench_close is not None else None
    ret3 = _ret(bench, CFG["flash_window"])
    out = {"windows": {}, "flash": bool(ret3 is not None and ret3 <= CFG["flash_thr"]),
           "flash_ret3": round(ret3, 4) if ret3 is not None else None}

    sig_by = dict(tradables)                 # signaux Passe A par ticker (drapeaux prix)
    surv_cache: dict[str, dict | None] = {}  # signaux de survie EDGAR, un appel par ticker

    def _survival(tk: str) -> dict | None:
        if tk not in surv_cache:
            import edgar
            try:
                surv_cache[tk] = edgar.survival_signals(tk)
            except Exception:
                surv_cache[tk] = None
        return surv_cache[tk]

    for w in CFG["windows"]:
        mkt = _ret(bench, w)
        if mkt is None:
            out["windows"][str(w)] = {"mkt": None, "cohort": [], "prelist": [],
                                      "note": {"code": "benchmark_missing"}}
            continue

        entries = []
        for tk, sig in tradables:
            e = _title_entry(tk, sig, prices.get(tk), w)
            if e is not None:
                entries.append(e)
        entries.sort(key=lambda e: e["chg"])  # plus écrasé d'abord — affichage, pas une règle

        if mkt >= 0:
            out["windows"][str(w)] = {
                "mkt": round(mkt, 4), "cohort": [], "prelist": entries[:CFG["prelist_max"]],
                "note": {"code": "market_bullish", "w": w, "mkt": round(mkt, 4)},
            }
            continue

        cohort = []
        for e in entries:
            surv = _survival(e["ticker"])
            if (surv or {}).get("dilution_flag") is not False:  # §8.2 — EDGAR muet (None) ⇒ non qualifié
                continue
            # Dossier de risque À L'ENTRÉE — mêmes marqueurs que les sélections
            # (scoring.risk_markers) : drapeaux prix de la Passe A + drapeaux EDGAR
            # déjà payés par la règle dilution §8.2.
            cohort.append({**e, "mkt": round(mkt, 4),
                           "risk_markers": risk_markers({**sig_by[e["ticker"]], **surv})})
        out["windows"][str(w)] = {
            "mkt": round(mkt, 4), "cohort": cohort, "prelist": [],
            "note": {"code": "market_bearish", "w": w, "mkt": round(mkt, 4), "n": len(cohort)},
        }
    return out


# ---------------------------------------------------------------------------
# Suivi des cohortes passées (Validation D — information, jamais un ordre de vente)
# ---------------------------------------------------------------------------

def _load_entries(history_dir: Path) -> dict[tuple[int, str], dict]:
    """Première entrée par (fenêtre, ticker) depuis les snapshots datés — jamais fatal."""
    first: dict[tuple[int, str], dict] = {}
    try:
        files = sorted(Path(history_dir).glob("*.json"))
    except Exception:
        return {}
    for f in files:  # ordre chronologique (nom = horodatage) → la première vue gagne
        try:
            snap = json.loads(f.read_text())
        except Exception:
            continue
        day = (snap.get("scanned_at") or "")[:10]
        windows = (snap.get("v5") or {}).get("windows") or {}
        for w_str, block in windows.items():
            try:
                w = int(w_str)
            except (TypeError, ValueError):
                continue
            for e in block.get("cohort") or []:
                tk = e.get("ticker")
                if tk and (w, tk) not in first and e.get("price"):
                    first[(w, tk)] = {"entry_date": day, "entry_price": e["price"],
                                      "chg": e.get("chg"),
                                      # Entrées antérieures au dossier de risque → liste vide.
                                      "risk_markers": e.get("risk_markers") or []}
    return first


def build_tracking(prices: dict, history_dir: Path) -> list[dict]:
    """Position de chaque titre de cohorte v5, par fenêtre — mêmes conventions que v4
    (cycle de vie calculé par `lifecycle.track_row`, avec le cfg v5), y compris le
    complément de prix des titres sortis de l'univers du jour (Epic 9 S1)."""
    from screener_backend import backfill_tracked_prices

    entries = _load_entries(history_dir)
    backfill_tracked_prices(prices, ((tk, e["entry_date"]) for (w, tk), e in entries.items()))
    out = [lifecycle.track_row({"ticker": tk, "window": w}, ent, prices.get(tk), CFG)
           for (w, tk), ent in entries.items()]
    out.sort(key=lambda r: (r["entry_date"], r["window"]), reverse=True)
    return out
