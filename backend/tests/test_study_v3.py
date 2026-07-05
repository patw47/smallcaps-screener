"""
Tests offline de la plomberie statistique de la STUDY v3 (Epic 3 S5) — AUCUN réseau.
On teste les fonctions PURES (purged CV, out-of-fold, décile, value-of-survival) sur des
données synthétiques ; l'orchestration réseau (download/analyze/EDGAR) est couverte par les
fonctions déjà testées et n'est exercée que par le run jugé (après sign-off du protocole).

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_study_v3.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import numpy as np

import backtest as bt


def test_purged_folds_partition_and_embargo():
    # 6 dates uniques × 2 obs ; embargo = 5 positions.
    pos = np.array([0, 0, 10, 10, 20, 20, 30, 30, 40, 40, 50, 50])
    folds = bt.purged_fold_masks(pos, k=6, embargo=5)
    assert len(folds) == 6
    # test sets = partition exacte de toutes les obs
    all_test = np.sort(np.concatenate([te for _, te in folds]))
    assert np.array_equal(all_test, np.arange(len(pos)))
    for tr, te in folds:
        assert set(tr).isdisjoint(set(te))                 # train ∩ test = ∅
        lo, hi = pos[te].min(), pos[te].max()
        # aucune obs d'entraînement dans [lo-embargo, hi+embargo] (purge des deux côtés)
        assert np.all((pos[tr] < lo - 5) | (pos[tr] > hi + 5))


def test_oof_predictions_rank_signal():
    rng = np.random.default_rng(0)
    n_dates = 12
    pos = np.repeat(np.arange(n_dates) * 21, 60)           # 12 dates × 60 obs
    X0 = rng.uniform(size=len(pos))
    X = np.column_stack([X0, rng.uniform(size=len(pos))])
    y = (rng.uniform(size=len(pos)) < 1 / (1 + np.exp(-(4 * X0 - 2)))).astype(float)
    folds = bt.purged_fold_masks(pos, k=4, embargo=21)
    oof = bt.oof_predictions(X, y, pos, folds)
    m = ~np.isnan(oof)
    assert m.sum() > 0.5 * len(y)                          # la plupart des obs prédites
    assert oof[m][y[m] == 1].mean() > oof[m][y[m] == 0].mean()   # sépare les classes


def test_decile_metrics_lift_positive():
    # oof aligné avec fwd : le haut de p_hat contient les gros gains → lift > 1
    rng = np.random.default_rng(1)
    p = rng.uniform(size=2000)
    fwd = np.where(rng.uniform(size=2000) < 0.02 + 0.20 * (p > 0.9), 1.5, -0.1)
    d = bt.decile_metrics(p, fwd, cost=0.01, seed=0)
    assert d is not None and d["lift100"] is not None
    assert d["lift100"] > 1.0                              # concentre les +100 %


def test_value_of_survival_detects_added_value():
    # +100 % piloté par une feature technique (col 0) ; les CRASHS pilotés par une feature de
    # survie (col 6, hors des 6 techniques). Le modèle COMPLET voit la survie → évite les crashs
    # → meilleure espérance nette que le modèle technique-seul.
    rng = np.random.default_rng(3)
    n_dates, per = 20, 120
    pos = np.repeat(np.arange(n_dates) * 21, per)
    n = len(pos)
    tech0 = rng.uniform(size=n)
    surv6 = (rng.uniform(size=n) < 0.30).astype(float)
    noise = rng.normal(scale=0.15, size=n)
    fwd = 1.6 * tech0 - 3.0 * surv6 + noise                 # up par tech0, crash par surv6
    y = (fwd >= 1.0).astype(float)
    cols = [tech0] + [rng.uniform(size=n) for _ in range(5)] + [surv6] + [rng.uniform(size=n) for _ in range(6)]
    X = np.column_stack(cols)                               # 13 features (6 tech + 7 survie)
    folds = bt.purged_fold_masks(pos, k=5, embargo=21)
    vos = bt.value_of_survival(X, y, pos, fwd, folds, cost=0.01)
    assert vos["ne_full"] is not None and vos["ne_tech"] is not None
    assert vos["ne_full"] > vos["ne_tech"]                  # la survie ajoute de la valeur
    assert vos["delta"] > 0


def test_study_v3_verdict_branches():
    strong = {"lift100": 2.0, "lift100_ci": (1.2, 3.0), "guard_ok": True, "net_expectancy": 0.05}
    low_base = (-0.02, 0.0, 0.01)   # random / best-feature / phenix, tous < 0.05
    # tous critères OK → pass provisoire
    v = bt.study_v3_verdict(strong, {"adds_value": True}, *low_base)
    assert v["verdict"] == "PROVISIONAL_PASS"
    # mode A : le veto n'ajoute rien mais espérance positive → FAIL_SURVIVAL_NO_VALUE
    v = bt.study_v3_verdict(strong, {"adds_value": False}, *low_base)
    assert v["verdict"] == "FAIL_SURVIVAL_NO_VALUE"
    # mode A terminal : espérance ≤ 0 ET veto n'aide pas → TERMINAL_FAIL
    dead = {**strong, "net_expectancy": -0.03}
    v = bt.study_v3_verdict(dead, {"adds_value": False}, *low_base)
    assert v["verdict"] == "TERMINAL_FAIL"
    # mode B : le veto aide mais espérance ≤ 0 (signal étouffé) → FAIL
    v = bt.study_v3_verdict(dead, {"adds_value": True}, *low_base)
    assert v["verdict"] == "FAIL"
    # données insuffisantes
    assert bt.study_v3_verdict(None, {}, None, None, None)["verdict"] == "INCONCLUSIVE"


def test_module_imports_and_constants_frozen():
    # constantes §4/§7 gelées (hors FILTERS)
    assert bt.STUDY_V3_K == 5 and bt.STUDY_V3_EMBARGO == 73
    assert bt.STUDY_V3_LAM_GRID == (0.03, 0.1, 0.3, 1.0)
    assert bt.N_TECH_FEATURES == 6
