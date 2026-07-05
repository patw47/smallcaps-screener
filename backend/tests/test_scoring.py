"""
Tests offline du modèle de score v3 (Epic 3 S3) — model.py + scoring.py, aucun réseau.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_scoring.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import numpy as np

import model as model_mod
import scoring
from model import LogisticL2, Isotonic, ScoreModel


def test_model_self_check():
    model_mod._demo()   # signe/rétrécissement logistique, isotonic monotone, round-trip JSON


def test_scoring_self_check():
    scoring._demo()     # assemblage rang/booléen/manquant + scoring cohérent


def test_logistic_recovers_sign():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(3000, 2))
    y = (rng.uniform(size=3000) < 1 / (1 + np.exp(-(2.0 * X[:, 0] - 1.5 * X[:, 1])))).astype(float)
    coef = LogisticL2(lam=0.5).fit(X, y).coef_
    assert coef[1] > 0 and coef[2] < 0                 # signes corrects
    assert abs(coef[1]) > abs(coef[2]) * 0.7           # ordre de grandeur cohérent


def test_isotonic_is_monotone_and_clamps():
    iso = Isotonic().fit(np.array([0.1, 0.2, 0.3, 0.4]), np.array([0, 0, 1, 1]))
    assert np.all(np.diff(iso.y_) >= -1e-9)
    assert iso.predict(np.array([-5.0]))[0] == iso.y_[0]    # hors domaine bas → borne
    assert iso.predict(np.array([5.0]))[0] == iso.y_[-1]    # hors domaine haut → borne


def test_empty_universe_matrix_shape():
    X = scoring.assemble_matrix([])
    assert X.shape == (0, len(scoring.FEATURES))


def test_frozen_feature_count_matches_protocol():
    # 6 techniques + 7 survie = 13 features gelées (protocole v3 §3)
    assert len(scoring.FEATURES) == 13
    assert scoring.FEATURE_NAMES[:6] == [
        "pct_52w_high", "rs_strength", "change_1m", "atr_ratio", "vol_ratio", "close_vs_sma20"]


def test_model_json_round_trip():
    rng = np.random.default_rng(4)
    X = rng.uniform(size=(200, len(scoring.FEATURES)))
    y = (X[:, 0] > 0.5).astype(float)
    m = scoring.fit_model(X, y)
    m2 = ScoreModel.from_json(m.to_json())
    assert np.allclose(m.predict_proba(X), m2.predict_proba(X))
    assert m2.feature_names == scoring.FEATURE_NAMES
