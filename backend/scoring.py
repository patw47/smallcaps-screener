"""
scoring.py — Dossier de risque affiché au dashboard (Epic 3 S4, réduit Epic 7 S2,
détaillé Epic 10 S1).

Le modèle v3 (`model.py`, assemblage de features, `p_explode` calculé) a été SUPPRIMÉ :
la thèse v3 a échoué, `model_v3.json` n'a jamais été produit et ne le sera pas. Le champ
`p_explode` reste au contrat d'API, à `None` — on n'invente pas de probabilité.

Ce qui vit réellement ici :
  - `RISK_FLAGS` → `survival_risk` : le booléen agrégé, conservé tel quel au contrat ;
  - `MARKER_LEVELS` → `risk_markers` : le DÉTAIL de ce qui est reproché au titre, en
    codes + variables, sur le modèle des drapeaux de contexte et des statuts de suivi.
    Aucune chaîne d'affichage n'est fabriquée ici : le frontend traduit.
"""
from __future__ import annotations

# Niveau de gravité de chaque marqueur — émis comme DONNÉE, au même titre que le code et
# les variables. Le backend ne décide d'aucune couleur, il qualifie un fait :
#   haut         — faits structurels (doute sur la continuité d'exploitation, regroupement
#                  d'actions) ;
#   intermédiaire — émission d'actions à venir ;
#   faible       — retard de dépôt, cours sous le plancher de cotation.
# L'ordre de ce dictionnaire est celui de la liste servie : gravité décroissante.
MARKER_LEVELS = {
    "going_concern": "high",
    "reverse_split": "high",
    "dilution": "medium",
    "late_filing": "low",
    "sub_dollar": "low",
}

# Drapeaux de risque (le booléen agrégé du dashboard). Dérivés des marqueurs : une famille
# ajoutée d'un côté ne peut pas être oubliée de l'autre.
RISK_FLAGS = tuple(f"{code}_flag" for code in MARKER_LEVELS)


def risk_markers(s: dict) -> list[dict]:
    """
    Liste des marqueurs effectivement levés, en CODES + variables — jamais de texte
    d'affichage. Aucun marqueur → liste VIDE (pas d'absence de clé : le frontend n'a pas
    à distinguer « rien à signaler » de « champ oublié »).

    Variables portées quand elles existent :
      - `date` : date du fait, uniquement si elle est déjà disponible (dépôt officiel,
        opération sur le titre). Un marqueur sans date reste dans la liste.
      - `days` : longueur de la série sous le plancher de cotation — c'est elle qui porte
        la gravité, qu'un booléen jetterait.
    """
    out = []
    for code, level in MARKER_LEVELS.items():
        if not s.get(f"{code}_flag"):
            continue
        marker = {"code": code, "level": level}
        date = s.get(f"{code}_date")
        if date:
            marker["date"] = date
        if code == "sub_dollar" and s.get("sub_dollar_days") is not None:
            marker["days"] = s["sub_dollar_days"]
        out.append(marker)
    return out


def score_candidates(signals: list[dict]) -> None:
    """Pose `survival_risk` (bool), `risk_markers` (liste) et `p_explode` (toujours None)
    sur chaque signal, en place. Le détail S'AJOUTE au booléen, il ne le remplace pas."""
    for s in signals:
        s["survival_risk"] = any(bool(s.get(f)) for f in RISK_FLAGS)
        s["risk_markers"] = risk_markers(s)
        s["p_explode"] = None
