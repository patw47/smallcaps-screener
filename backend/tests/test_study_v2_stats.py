"""
Tests offline des fonctions de la STUDY v2 (Sprint 5) — chasse à la queue Fusée/Phénix.
Valeurs calculées À LA MAIN, sans réseau. Couvre : fréquences de queue, lift + IC bootstrap,
taux de délisting break-even (§5), espérance nette, verdict §6, fenêtrage, agrégat de fenêtre.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_study_v2_stats.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import pandas as pd

from backtest import (
    tail_frac, lift, bootstrap_lift_ci, break_even_delisting_rate,
    net_expectancy, study_verdict, _window_of, _study_v2_window,
    VALIDATION_A_WINDOW, EXPLORATION_WINDOW,
)


# ---------------------------------------------------------------------------
# Fréquence de queue (droite / gauche), None ignorés
# ---------------------------------------------------------------------------

def test_tail_frac_upper_and_lower():
    xs = [0.6, 1.2, -0.6, 0.1]
    assert tail_frac(xs, 0.50) == 0.5          # 0.6 et 1.2 ≥ 0.5 → 2/4
    assert tail_frac(xs, 1.00) == 0.25         # seul 1.2 ≥ 1.0 → 1/4
    assert tail_frac(xs, -0.50, upper=False) == 0.25   # seul -0.6 ≤ -0.5 → 1/4


def test_tail_frac_ignores_none_and_empty():
    assert tail_frac([None, 0.6, None], 0.5) == 1.0    # 1 seule valeur valide (0.6 ≥ 0.5) → 1/1
    assert tail_frac([], 0.5) is None
    assert tail_frac([None, None], 0.5) is None


# ---------------------------------------------------------------------------
# Lift
# ---------------------------------------------------------------------------

def test_lift_basic_and_guards():
    assert lift(0.5, 0.25) == 2.0
    assert lift(0.2, 0.2) == 1.0
    assert lift(0.5, 0.0) is None              # base nulle
    assert lift(None, 0.2) is None


# ---------------------------------------------------------------------------
# IC bootstrap du lift — cas déterministe (tous les membres franchissent)
# ---------------------------------------------------------------------------

def test_bootstrap_lift_ci_degenerate_is_point():
    # tous les membres à +1.2 → chaque rééchantillon franchit +1.0 (freq 1.0) ; /base 0.25 = 4.0
    lo, hi = bootstrap_lift_ci([1.2] * 5, p_base=0.25, threshold=1.0, n_boot=300, seed=1)
    assert lo == 4.0 and hi == 4.0


def test_bootstrap_lift_ci_brackets_point_lift():
    # membres mixtes : point lift = (3/5)/0.2 = 3.0 ; l'IC doit encadrer une valeur plausible
    m = [1.2, 1.5, 1.1, 0.0, 0.0]
    lo, hi = bootstrap_lift_ci(m, p_base=0.20, threshold=1.0, n_boot=500, seed=2)
    assert lo is not None and lo <= 3.0 <= hi


def test_bootstrap_lift_ci_empty_or_zero_base():
    assert bootstrap_lift_ci([], 0.2, 1.0) == (None, None)
    assert bootstrap_lift_ci([1.2], 0.0, 1.0) == (None, None)


# ---------------------------------------------------------------------------
# Break-even délisting (§5) = 1 − 1/lift, indépendant de la base
# ---------------------------------------------------------------------------

def test_break_even_delisting_rate_hand_values():
    assert break_even_delisting_rate(2.0) == 0.5
    assert abs(break_even_delisting_rate(1.4) - (1 - 1 / 1.4)) < 1e-12   # ≈ 0.2857
    assert break_even_delisting_rate(1.0) is None        # aucun lift à effacer
    assert break_even_delisting_rate(0.8) is None
    assert break_even_delisting_rate(None) is None


# ---------------------------------------------------------------------------
# Espérance nette
# ---------------------------------------------------------------------------

def test_net_expectancy_subtracts_cost():
    assert abs(net_expectancy([0.10, 0.20, 0.00], 0.01) - 0.09) < 1e-12   # moyenne 0.10 − 0.01
    assert net_expectancy([], 0.01) is None


# ---------------------------------------------------------------------------
# Verdict §6 (PASS / FAIL / CONDITIONAL)
# ---------------------------------------------------------------------------

def test_verdict_fusee_pass_phenix_conditional():
    assert study_verdict("fusee", 1.5, 1.1, 0.05, True) == "PASS"
    assert study_verdict("phenix", 1.5, 1.1, 0.05, True) == "CONDITIONAL"


def test_verdict_fail_paths():
    assert study_verdict("fusee", 1.5, 0.9, 0.05, True) == "FAIL"    # IC95 bas ≤ 1.0
    assert study_verdict("fusee", 1.3, 1.1, 0.05, True) == "FAIL"    # lift < 1.4
    assert study_verdict("fusee", 1.5, 1.1, -0.01, True) == "FAIL"   # espérance ≤ 0
    assert study_verdict("fusee", 1.5, 1.1, 0.05, False) == "FAIL"   # garde dépassée


# ---------------------------------------------------------------------------
# Fenêtrage protocolaire (bornes inclusives)
# ---------------------------------------------------------------------------

def test_window_of_buckets_and_boundaries():
    assert _window_of(pd.Timestamp("2022-01-15")) == "validation_a"
    assert _window_of(pd.Timestamp(VALIDATION_A_WINDOW[1])) == "validation_a"   # borne haute incluse
    assert _window_of(pd.Timestamp(EXPLORATION_WINDOW[0])) == "exploration"     # borne basse incluse
    assert _window_of(pd.Timestamp("2024-06-15")) == "exploration"
    assert _window_of(pd.Timestamp("2020-01-01")) is None                       # hors fenêtres


# ---------------------------------------------------------------------------
# Agrégat de fenêtre — lift, capacité, break-even sur rows construits à la main
# ---------------------------------------------------------------------------

def _row(fwd63, is_fusee=False, dv=2_000_000):
    return {"date": pd.Timestamp("2022-03-01"), "window": "validation_a",
            "fwd": {63: fwd63}, "dv": dv,
            "is_fusee": is_fusee, "fusee_event": False, "is_phenix": False}


def test_study_v2_window_lift_break_even_and_capacity_filter():
    # Base = 10 obs : 8 à 0.0, 2 doublers (+1.2). Membres Fusée = 2 doublers + 2 à 0.0.
    rows = [_row(0.0) for _ in range(6)]
    rows += [_row(0.0, is_fusee=True), _row(0.0, is_fusee=True)]       # membres non-doublers
    rows += [_row(1.2, is_fusee=True), _row(1.2, is_fusee=True)]       # membres doublers
    # Piège capacité : un doubler Fusée SOUS le seuil ADV (dv 0.5M < 1M) doit être EXCLU.
    rows.append(_row(5.0, is_fusee=True, dv=500_000))

    w = _study_v2_window("validation_a", rows, horizons=[63], seed=0)
    assert w["n_base"] == 10                    # le row sous-capacité est écarté (11 → 10)
    m = w["profiles"]["fusee"][63]
    assert m["n_base"] == 10 and m["n_member"] == 4
    # base P(≥+100%) = 2/10 = 0.2 ; membre = 2/4 = 0.5 → lift 2.5
    assert abs(m["lift_up100"] - 2.5) < 1e-9
    assert abs(m["lift_up50"] - 2.5) < 1e-9
    # break-even = 1 − 1/2.5 = 0.6 (robuste, pas fragile)
    assert abs(m["break_even_delisting"] - 0.6) < 1e-9
    # espérance nette membres = moyenne([0,0,1.2,1.2]) − 0.01 = 0.59
    assert abs(m["net_expectancy"] - 0.59) < 1e-9
    # aucun −50 % nulle part → garde OK, lift garde None
    assert m["guard_ok"] is True and m["guard_left_lift"] is None
    assert m["verdict"] in ("PASS", "FAIL")     # token valide (dépend de l'IC bootstrap n=4)
    # profil sans membre → lift None, n_member 0
    assert w["profiles"]["fusee_event"][63]["n_member"] == 0
    assert w["profiles"]["fusee_event"][63]["lift_up100"] is None
