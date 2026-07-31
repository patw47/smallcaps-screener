"""
scoring.py — Drapeaux de survie affichés au dashboard (Epic 3 S4, réduit Epic 7 S2).

Le modèle v3 (`model.py`, assemblage de features, `p_explode` calculé) a été SUPPRIMÉ :
la thèse v3 a échoué, `model_v3.json` n'a jamais été produit et ne le sera pas. Le champ
`p_explode` reste au contrat d'API, à `None` — on n'invente pas de probabilité.

Ce qui vit réellement ici : `RISK_FLAGS` → `survival_risk`, le rouge du dashboard.
"""
from __future__ import annotations

# Drapeaux de risque affichés (le rouge du dashboard).
RISK_FLAGS = ("dilution_flag", "going_concern_flag", "reverse_split_flag",
              "late_filing_flag", "sub_dollar_flag")


def score_candidates(signals: list[dict]) -> None:
    """Pose `survival_risk` (bool) et `p_explode` (toujours None) sur chaque signal, en place."""
    for s in signals:
        s["survival_risk"] = any(bool(s.get(f)) for f in RISK_FLAGS)
        s["p_explode"] = None
