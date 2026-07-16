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
    Les jours haussiers (ou benchmark manquant), la cohorte est vide (§8.4 : pas de
    bénéfice du doute) ; la pré-liste montre les titres passant les règles-titre seules
    (zéro appel EDGAR ces jours-là). EDGAR n'est interrogé que pour les candidats des
    fenêtres baissières (cache disque + mémos edgar existants — coût marginal ~nul).
    """
    bench = bench_close.dropna() if bench_close is not None else None
    ret3 = _ret(bench, CFG["flash_window"])
    out = {"windows": {}, "flash": bool(ret3 is not None and ret3 <= CFG["flash_thr"]),
           "flash_ret3": round(ret3, 4) if ret3 is not None else None}

    dil_cache: dict[str, bool | None] = {}

    def _dilution(tk: str) -> bool | None:
        if tk not in dil_cache:
            import edgar
            try:
                surv = edgar.survival_signals(tk)
            except Exception:
                surv = None
            dil_cache[tk] = surv.get("dilution_flag") if surv else None
        return dil_cache[tk]

    for w in CFG["windows"]:
        mkt = _ret(bench, w)
        if mkt is None:
            out["windows"][str(w)] = {"mkt": None, "cohort": [], "prelist": [],
                                      "note": "benchmark indisponible → cohorte vide (§8.4)"}
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
                "note": f"marché haussier (IWM {w}j {mkt:+.1%}) → variante en pause (§8.4)",
            }
            continue

        cohort = []
        for e in entries:
            if _dilution(e["ticker"]) is not False:  # §8.2 — EDGAR muet (None) ⇒ non qualifié
                continue
            cohort.append({**e, "mkt": round(mkt, 4)})
        out["windows"][str(w)] = {
            "mkt": round(mkt, 4), "cohort": cohort, "prelist": [],
            "note": f"marché baissier (IWM {w}j {mkt:+.1%}) → {len(cohort)} qualifiés",
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
                                      "chg": e.get("chg")}
    return first


def build_tracking(prices: dict, history_dir: Path) -> list[dict]:
    """Position de chaque titre de cohorte v5, par fenêtre — mêmes conventions que v4."""
    cp_day, cp_thr, horizon = CFG["checkpoint_day"], CFG["checkpoint_thr"], CFG["horizon"]
    out: list[dict] = []
    for (w, tk), ent in _load_entries(history_dir).items():
        row = {"ticker": tk, "window": w, **ent, "days_held": None, "ret": None,
               "checkpoint": None, "status": "données absentes (délisting ?)"}
        df = prices.get(tk)
        if df is not None and "Close" in df:
            close = df["Close"].dropna()
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
                    r63 = float(after.iloc[horizon - 1]) / ent["entry_price"] - 1
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
    out.sort(key=lambda r: (r["entry_date"], r["window"]), reverse=True)
    return out
