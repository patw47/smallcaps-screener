"""
scoring.py — Assemblage des features v3 (gelées, protocole §3) + application du modèle (Epic 3 S3).

SOURCE UNIQUE partagée par la production (`run_scan`) et l'étude walk-forward (S5) : la même
fonction assemble le vecteur de features, donc zéro dérive entre ce que le badge affiche et ce
que l'étude mesure (la leçon de v2). Standardisation = RANG PERCENTILE cross-sectionnel dans le
vivier de la date (invariant d'échelle → aucun scaler à persister) ; features booléennes en
1/0 ; valeur manquante → 0.5 (neutre).

Le modèle (`model.ScoreModel`) est ENTRAÎNÉ par l'étude (S5) et chargé tel quel en production ;
aucune ré-estimation en ligne. Sans modèle entraîné, `p_explode = None` (score indisponible —
honnête, on n'invente pas de probabilité).

Auto-vérification : `python3 backend/scoring.py`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from model import ScoreModel

# Features GELÉES au protocole v3 §3 : (clé_signal, type). NE PAS modifier sans révision protocole.
#   type "cont" → rang percentile cross-sectionnel ∈ (0,1] ; type "bool" → 1.0/0.0, None → 0.5.
FEATURES: list[tuple[str, str]] = [
    # A. Techniques / région (dérivées du prix)
    ("pct_52w_high", "cont"),        # T1 distance au plus-haut 52 sem.
    ("rs_strength", "cont"),         # T2 force relative 63j vs IWM
    ("change_1m", "cont"),           # T3 perf 1 mois
    ("atr_ratio", "cont"),           # T4 compression ATR20/ATR90
    ("vol_ratio", "cont"),           # T5 expansion de volume
    ("close_vs_sma20", "cont"),      # T6 close vs SMA20 (stabilisation)
    # B. Survie (EDGAR + prix) — l'information de queue gauche que le prix ne voit pas
    ("dilution_flag", "bool"),       # S1 registration/prospectus (S-1/S-3/424B)
    ("reverse_split_flag", "bool"),  # S2 (stub neutre pour l'instant — voir screener_backend)
    ("going_concern_flag", "bool"),  # S3 « substantial doubt » (ASC 205-40)
    ("cash_runway", "cont"),         # S4 (stub None → neutre — piste XBRL, protocole §3)
    ("sub_dollar_flag", "bool"),     # S5 a récemment touché < 1 $
    ("late_filing_flag", "bool"),    # S6 NT 10-Q/10-K
    ("insider_net_buying", "cont"),  # S7 achats nets Form 4 ($)
]
FEATURE_NAMES: list[str] = [k for k, _ in FEATURES]

# Drapeaux de risque affichés (le rouge du dashboard) — indépendants du modèle.
RISK_FLAGS = ("dilution_flag", "going_concern_flag", "reverse_split_flag",
              "late_filing_flag", "sub_dollar_flag")


def _pctile_ranks(vals: list) -> list[float]:
    """Rang percentile ∈ (0,1] des non-None ; valeur manquante → 0.5 (neutre)."""
    s = pd.Series([v if v is not None else float("nan") for v in vals], dtype="float64")
    ranks = s.rank(pct=True)
    return [0.5 if pd.isna(x) else float(x) for x in ranks]


def assemble_matrix(signals: list[dict]) -> np.ndarray:
    """
    Matrice (n × d) des features gelées, standardisées DANS CETTE cross-section (une date de scan).
    L'étude walk-forward assemble par date puis empile — ne JAMAIS passer plusieurs dates ici
    (le rang percentile n'a de sens qu'au sein d'un même vivier). Univers vide → shape (0, d).
    """
    d = len(FEATURES)
    n = len(signals)
    X = np.full((n, d), 0.5, dtype=float)
    if n == 0:
        return X
    for j, (key, kind) in enumerate(FEATURES):
        col = [s.get(key) for s in signals]
        if kind == "cont":
            X[:, j] = _pctile_ranks(col)
        else:  # bool : True→1, False→0, None→0.5 neutre
            X[:, j] = [0.5 if v is None else (1.0 if v else 0.0) for v in col]
    return X


def fit_model(X: np.ndarray, y, lam: float = 1.0) -> ScoreModel:
    """Entraîne un ScoreModel sur une matrice DÉJÀ assemblée+empilée (par l'étude S5)."""
    return ScoreModel(FEATURE_NAMES, lam=lam).fit(X, y)


def load_model(path: str) -> ScoreModel | None:
    """Charge un ScoreModel entraîné (JSON) depuis `path`, ou None si absent/illisible.

    La production charge ce fichier tel quel ; il est produit UNE FOIS par l'étude S5 (après
    sign-off du protocole). Absent → None → `p_explode` non calculé (honnête, pas de score).
    """
    try:
        with open(path, encoding="utf-8") as f:
            return ScoreModel.from_json(f.read())
    except (OSError, ValueError, KeyError):
        return None


def score_candidates(signals: list[dict], model: ScoreModel | None) -> None:
    """
    Pose `p_explode` (float|None) et `survival_risk` (bool) sur chaque signal (mutation en place).

    Sans modèle entraîné → `p_explode=None` (on n'invente pas de score). `survival_risk` reste
    calculé depuis les drapeaux → l'affichage du risque fonctionne même sans modèle.
    """
    for s in signals:
        s["survival_risk"] = any(bool(s.get(f)) for f in RISK_FLAGS)
        s["p_explode"] = None
    if model is None or not getattr(model, "fitted", False) or not signals:
        return
    p = model.predict_proba(assemble_matrix(signals))
    for s, pi in zip(signals, p):
        s["p_explode"] = round(float(pi), 4)


def _demo() -> None:
    """Auto-vérification : assemblage (rang/booléen/manquant) + cohérence du scoring."""
    sigs = [
        {"pct_52w_high": 0.2, "dilution_flag": True, "cash_runway": None, "insider_net_buying": 500},
        {"pct_52w_high": 0.9, "dilution_flag": False, "cash_runway": None, "insider_net_buying": None},
        {"pct_52w_high": None, "dilution_flag": None, "cash_runway": None, "insider_net_buying": -100},
    ]
    X = assemble_matrix(sigs)
    assert X.shape == (3, len(FEATURES))
    j52 = FEATURE_NAMES.index("pct_52w_high")
    assert X[0, j52] < X[1, j52]            # 0.2 rangé plus bas que 0.9
    assert X[2, j52] == 0.5                 # manquant → neutre
    jdil = FEATURE_NAMES.index("dilution_flag")
    assert X[0, jdil] == 1.0 and X[1, jdil] == 0.0 and X[2, jdil] == 0.5
    jcash = FEATURE_NAMES.index("cash_runway")
    assert np.all(X[:, jcash] == 0.5)       # feature entièrement manquante → colonne neutre

    # Sans modèle : p_explode None, survival_risk vrai là où un drapeau est levé
    score_candidates(sigs, None)
    assert sigs[0]["p_explode"] is None
    assert sigs[0]["survival_risk"] is True and sigs[1]["survival_risk"] is False

    # Avec modèle : entraîné pour AIMER le going_concern=0 (survie) → p plus haut pour le sain
    rng = np.random.default_rng(1)
    Xtr = rng.uniform(size=(400, len(FEATURES)))
    jgc = FEATURE_NAMES.index("going_concern_flag")
    ytr = (Xtr[:, jgc] < 0.5).astype(float)   # y=1 quand PAS de going concern
    m = fit_model(Xtr, ytr, lam=1.0)
    healthy = [{"going_concern_flag": False}]
    sick = [{"going_concern_flag": True}]
    score_candidates(healthy, m)
    score_candidates(sick, m)
    assert healthy[0]["p_explode"] > sick[0]["p_explode"], (healthy, sick)
    assert 0.0 <= healthy[0]["p_explode"] <= 1.0

    print("scoring.py demo OK — assemblage rang/booléen/manquant + scoring cohérent")


if __name__ == "__main__":
    _demo()
