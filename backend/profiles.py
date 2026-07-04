"""
profiles.py — Détecteurs de profils tail-hunting « Fusée » & « Phénix » (Epic 2).

SOURCE UNIQUE DE VÉRITÉ partagée par la production (badges, alertes, `run_scan`) et
l'étude v2 (Sprint 5). Les appartenances reposent sur des PERCENTILES cross-sectionnels
calculés par date de scan dans l'univers tradable, définis VERBATIM au protocole v2 §3
(`docs/backtest_protocol_v2.md`). Toute déviation exige d'abord une révision du protocole.

- Fusée (extrême de momentum) : `rs63 ≥ P80` ET `perf_1m ≥ P80`.
  Variant ÉVÉNEMENT (`fusee_event`) : membre Fusée ET cassure le jour même (`triggered`).
- Phénix (massacré, comprimé, en stabilisation) : `pct_52w ≤ P20` ET `atr_ratio ≤ P40`
  ET `close ≥ SMA20`.

Les seuils de percentile vivent dans `FILTERS["profiles"]` (aucun nombre en dur ici).
L'appartenance est booléenne ; une force continue par profil (moyenne des percentiles
membres) sert UNIQUEMENT au classement d'affichage — pas au jugement pass/fail.
"""
from __future__ import annotations

import pandas as pd

from screener_backend import FILTERS


def _quantile(values: list[float | None], q: float) -> float | None:
    """Quantile `q` des valeurs non-None ; None si la population est vide."""
    xs = [v for v in values if v is not None]
    if not xs:
        return None
    return float(pd.Series(xs, dtype="float64").quantile(q))


def _pctile_ranks(values: list[float | None]) -> list[float | None]:
    """Rang percentile ∈ (0,1] de chaque valeur (moyenne sur les ex-æquo). None reste None."""
    s = pd.Series([v if v is not None else float("nan") for v in values], dtype="float64")
    ranks = s.rank(pct=True)
    return [None if pd.isna(x) else float(x) for x in ranks]


def profile_thresholds(signals: list[dict]) -> dict[str, float | None]:
    """Seuils de percentile cross-sectionnels Fusée & Phénix pour un vivier donné."""
    P = FILTERS["profiles"]
    return {
        "rs63_min": _quantile([s.get("rs_strength") for s in signals], P["fusee"]["rs63_pctile_min"]),
        "perf_1m_min": _quantile([s.get("change_1m") for s in signals], P["fusee"]["perf_1m_pctile_min"]),
        "pct_52w_max": _quantile([s.get("pct_52w_high") for s in signals], P["phenix"]["pct_52w_pctile_max"]),
        "atr_ratio_max": _quantile([s.get("atr_ratio") for s in signals], P["phenix"]["atr_ratio_pctile_max"]),
    }


def detect_profiles(signals: list[dict]) -> None:
    """
    Étiquette CHAQUE signal (mutation en place) avec son appartenance aux profils, à partir
    des percentiles cross-sectionnels du vivier tradable fourni. Robuste à l'univers vide et
    aux valeurs manquantes (un champ requis manquant → non-membre). Ne renvoie rien.

    Champs posés : `is_fusee`, `is_phenix` (bool), `fusee_strength`, `phenix_strength`
    (float|None, membres seulement), `fusee_event` (bool), `profiles` (liste), `profile`
    ("fusee"|"phenix"|"both"|None), `profile_strength` (float, pour le classement).
    """
    if not signals:
        return

    thr = profile_thresholds(signals)
    rs_rank = _pctile_ranks([s.get("rs_strength") for s in signals])
    perf_rank = _pctile_ranks([s.get("change_1m") for s in signals])
    p52_rank = _pctile_ranks([s.get("pct_52w_high") for s in signals])
    atr_rank = _pctile_ranks([s.get("atr_ratio") for s in signals])

    for i, s in enumerate(signals):
        rs, perf = s.get("rs_strength"), s.get("change_1m")
        p52, atr = s.get("pct_52w_high"), s.get("atr_ratio")
        price, sma20 = s.get("price"), s.get("sma20")

        is_fusee = bool(
            rs is not None and perf is not None
            and thr["rs63_min"] is not None and thr["perf_1m_min"] is not None
            and rs >= thr["rs63_min"] and perf >= thr["perf_1m_min"])

        is_phenix = bool(
            p52 is not None and atr is not None and price is not None and sma20 is not None
            and thr["pct_52w_max"] is not None and thr["atr_ratio_max"] is not None
            and p52 <= thr["pct_52w_max"] and atr <= thr["atr_ratio_max"]
            and price >= sma20)

        # Force = moyenne des percentiles MEMBRES, orientée « plus profond = plus fort ».
        # Fusée : rang brut (haut = extrême de momentum). Phénix : 1 − rang (bas = plus massacré /
        # plus comprimé). La garde close ≥ SMA20 est booléenne → hors du calcul de force (§3).
        fusee_strength = None
        if is_fusee and rs_rank[i] is not None and perf_rank[i] is not None:
            fusee_strength = round((rs_rank[i] + perf_rank[i]) / 2, 4)
        phenix_strength = None
        if is_phenix and p52_rank[i] is not None and atr_rank[i] is not None:
            phenix_strength = round(((1 - p52_rank[i]) + (1 - atr_rank[i])) / 2, 4)

        s["is_fusee"] = is_fusee
        s["is_phenix"] = is_phenix
        s["fusee_strength"] = fusee_strength
        s["phenix_strength"] = phenix_strength
        s["fusee_event"] = bool(is_fusee and s.get("triggered"))
        s["profiles"] = [p for p, ok in (("fusee", is_fusee), ("phenix", is_phenix)) if ok]
        s["profile"] = ("both" if is_fusee and is_phenix
                        else "fusee" if is_fusee else "phenix" if is_phenix else None)
        s["profile_strength"] = round(max(fusee_strength or 0.0, phenix_strength or 0.0), 4)


def rank_members(survivors: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """
    Ne garde que les (ticker, signals) membres d'un profil, triés par force de profil
    décroissante (dollar-volume en départage). `detect_profiles` doit avoir été appelé au
    préalable sur les `signals`.
    """
    members = [(tk, sig) for tk, sig in survivors
               if sig.get("is_fusee") or sig.get("is_phenix")]
    members.sort(key=lambda x: (x[1].get("profile_strength") or 0.0,
                                x[1].get("dollar_volume") or 0.0), reverse=True)
    return members
