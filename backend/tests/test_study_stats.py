"""
Tests offline des fonctions statistiques PURES de la study (Sprint 6) — valeurs calculées
à la main. IC de Spearman, t-stat, fenêtres non chevauchantes, spread décile, bootstrap.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_study_stats.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import math

from backtest import (
    _rank_avg, spearman_ic, mean_tstat, nonoverlapping_indices,
    decile_spread, bootstrap_mean_ci,
)


# ---------------------------------------------------------------------------
# Rangs & Spearman
# ---------------------------------------------------------------------------

def test_rank_avg_handles_ties():
    # 10 et 10 partagent les rangs 2 et 3 → rang moyen 2.5 chacun ; 30 → rang 4
    assert _rank_avg([5.0, 10.0, 10.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_monotone():
    x = [1, 2, 3, 4, 5]
    assert abs(spearman_ic(x, [10, 20, 30, 40, 50]) - 1.0) < 1e-9
    assert abs(spearman_ic(x, [50, 40, 30, 20, 10]) + 1.0) < 1e-9


def test_spearman_is_rank_not_pearson():
    # relation monotone NON linéaire (carré) → Spearman = 1 (Pearson serait < 1)
    x = [1, 2, 3, 4, 5, 6]
    y = [v * v for v in x]
    assert abs(spearman_ic(x, y) - 1.0) < 1e-9


def test_spearman_none_on_degenerate():
    assert spearman_ic([1, 2], [1, 2]) is None            # < 3 obs
    assert spearman_ic([1, 1, 1], [1, 2, 3]) is None       # variance nulle


# ---------------------------------------------------------------------------
# t-stat
# ---------------------------------------------------------------------------

def test_mean_tstat_known_value():
    m, t, n = mean_tstat([1.0, 2.0, 3.0])   # mean=2, sd=1 → t = 2/(1/√3) = 2√3
    assert n == 3 and abs(m - 2.0) < 1e-9
    assert abs(t - 2.0 * math.sqrt(3)) < 1e-9


def test_mean_tstat_zero_variance():
    m, t, n = mean_tstat([2.0, 2.0, 2.0])
    assert m == 2.0 and t is None          # sd=0 → pas de t-stat


# ---------------------------------------------------------------------------
# Fenêtres non chevauchantes
# ---------------------------------------------------------------------------

def test_nonoverlapping_indices():
    # pas 21j, horizon 63j → stride ⌈63/21⌉ = 3 → 1 date sur 3
    assert nonoverlapping_indices(9, 21, 63) == [0, 3, 6]
    # horizon = pas → toutes les dates (adjacentes, non chevauchantes)
    assert nonoverlapping_indices(5, 21, 21) == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Spread décile
# ---------------------------------------------------------------------------

def test_decile_spread_monotone():
    scores = list(range(20))
    returns = list(range(20))            # rendement croît avec le score
    d1, d10, spread = decile_spread(scores, returns, 10)
    assert d1 == 0.5 and d10 == 18.5     # moyennes des paires basse/haute
    assert spread == 18.0


def test_decile_spread_too_few():
    assert decile_spread([1, 2, 3], [1, 2, 3], 10) == (None, None, None)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def test_bootstrap_ci_brackets_mean():
    xs = [0.01, 0.02, 0.03, 0.04, 0.05]
    lo, hi = bootstrap_mean_ci(xs, n_boot=500, seed=1)
    assert lo <= sum(xs) / len(xs) <= hi
    assert lo < hi


def test_bootstrap_ci_empty():
    assert bootstrap_mean_ci([]) == (None, None)
