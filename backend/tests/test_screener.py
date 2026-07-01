"""
Tests unitaires offline du screener (Niveaux 1–2 du plan de validation).

Déterministes, sans réseau : on nourrit les helpers purs et la Passe A avec des
pd.Series/DataFrame synthétiques et on assert les sorties exactes.

Lancer : DATA_DIR=/tmp/screener_test pytest backend/tests/ -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")  # évite makedirs("/app/data")

import pandas as pd
import pytest

from screener_backend import (
    FILTERS,
    _sma, _ma_rising, _median_dollar_volume, _rs_metrics,
    _compute_score, _build_positives_flags, analyze_prices,
)


# ---------------------------------------------------------------------------
# Niveau 1 — helpers purs
# ---------------------------------------------------------------------------

def test_median_dollar_volume_robust_to_spike():
    close = pd.Series([10.0] * 20)
    volume = pd.Series([100] * 19 + [100_000])  # un spike de fin
    # médiane = 10 * 100 = 1000, non tirée par le pic (contrairement à la moyenne)
    assert _median_dollar_volume(close, volume, 20) == 1000.0


def test_ma_rising_uptrend():
    close = pd.Series(range(1, 101), dtype=float)  # strictement croissant
    assert _ma_rising(close, 50, 10) is True


def test_ma_rising_downtrend():
    close = pd.Series(range(100, 0, -1), dtype=float)  # strictement décroissant
    assert _ma_rising(close, 50, 10) is False


def test_ma_rising_insufficient_history():
    close = pd.Series(range(1, 40), dtype=float)  # < window + lookback
    assert _ma_rising(close, 50, 10) is None


def test_sma_last_window():
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _sma(close, 3) == 4.0  # mean(3,4,5)


def test_rs_metrics_outperformance():
    # titre ~+20% vs benchmark ~+5% sur la fenêtre → surperforme, RS-line monte
    stock = pd.Series([100 * (1.20 ** (i / 63)) for i in range(64)])
    bench = pd.Series([100 * (1.05 ** (i / 63)) for i in range(64)])
    outperf, rising = _rs_metrics(stock, bench, 63, 21)
    assert outperf is True
    assert rising is True


def test_rs_metrics_underperformance():
    stock = pd.Series([100 * (0.90 ** (i / 63)) for i in range(64)])  # baisse
    bench = pd.Series([100 * (1.05 ** (i / 63)) for i in range(64)])  # hausse
    outperf, rising = _rs_metrics(stock, bench, 63, 21)
    assert outperf is False
    assert rising is False


def test_rs_metrics_no_benchmark():
    assert _rs_metrics(pd.Series([1.0] * 100), None, 63, 21) == (None, None)


# ---------------------------------------------------------------------------
# Niveau 2 — régression sur les bugs corrigés
# ---------------------------------------------------------------------------

def test_cash_positive_none_no_debt_flag():
    """Donnée bilan absente → cash_positive None → PAS de faux flag dette."""
    stock = {"cash_positive": None}
    _, flags = _build_positives_flags(stock)
    assert not any("Dette" in f for f in flags)


def test_cash_positive_false_emits_flag():
    stock = {"cash_positive": False}
    _, flags = _build_positives_flags(stock)
    assert any("Dette" in f for f in flags)


def test_cash_positive_none_not_scored():
    assert _compute_score({"cash_positive": None}) == 0
    assert _compute_score({"cash_positive": True}) > 0


def test_score_perfect_is_10_not_capped():
    """Titre cochant toutes les règles → 10 pile (ancien bug : plafond dur ambigu)."""
    perfect = {
        "vol_ratio": 1.8,           # dans [1.3, 2.5]
        "compressed": True,
        "rs_signal": True,
        "insider_buying": True,
        "price_above_ma50": True,
        "cash_positive": True,
        "revenue_growth": 0.50,
        "short_interest_pct": 20.0,
    }
    assert _compute_score(perfect) == 10


def test_score_empty_is_zero():
    assert _compute_score({}) == 0


# ---------------------------------------------------------------------------
# Niveau 1/2 — Passe A intégrée (offline, DataFrame synthétique)
# ---------------------------------------------------------------------------

def _make_df(closes, volumes):
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


def test_pass_a_rejects_downtrend():
    # baisse douce 45 → 25 : reste dans la bande de prix et de perf 1m,
    # mais pente MA50 négative → rejet tendance
    closes = [45.0 - i * 0.1 for i in range(200)]
    df = _make_df(closes, [500_000] * len(closes))
    signals, reason = analyze_prices("DOWN", df, None)
    assert signals is None
    assert reason == "trend:down"


def test_pass_a_rejects_illiquid():
    # uptrend dans la bande de prix mais volume ridicule → rejet liquidité
    closes = [10.0 + i * 0.05 for i in range(200)]  # 10 → ~20
    volumes = [10] * 200  # ~15 * 10 = 150 USD/j « dollar-volume »
    df = _make_df(closes, volumes)
    signals, reason = analyze_prices("ILLIQ", df, None)
    assert signals is None
    assert reason.startswith("liquidity")


def test_pass_a_accepts_healthy_uptrend():
    # uptrend doux dans la bande de prix, liquide, perf 1m modérée
    closes = [10.0 + i * 0.05 for i in range(200)]  # ~10 → ~20, pente positive
    volumes = [200_000] * 200  # dollar-vol ~ 20*200k = 4M > seuil
    df = _make_df(closes, volumes)
    signals, reason = analyze_prices("UP", df, None)
    assert reason == "ok"
    assert signals is not None
    assert signals["price_above_ma50"] is True
    assert FILTERS["price_min"] <= signals["price"] <= FILTERS["price_max"]


def test_pass_a_rejects_price_below_rising_ma():
    # MA50 en hausse mais dernier prix sous la MA50 (pullback) → trend:below_ma
    closes = [10.0 + i * 0.1 for i in range(200)]  # uptrend franc
    closes[-1] = 22.0                              # dip final sous la MA50 (~27)
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("PB", df, None)
    assert signals is None
    assert reason == "trend:below_ma"


def test_pass_a_rejects_weak_rs_when_required():
    # uptrend valide mais sous-performe un benchmark plus fort → rs:weak (filtre dur)
    idx = pd.date_range("2025-01-01", periods=200, freq="B")
    closes = [10.0 + i * 0.01 for i in range(200)]        # uptrend mou, prix > MA50, pente +
    df = _make_df(closes, [300_000] * 200)                # liquide
    bench = pd.Series([100.0 * (1.6 ** (i / 199)) for i in range(200)], index=idx)  # benchmark fort
    signals, reason = analyze_prices("WEAKRS", df, bench)
    assert signals is None
    assert reason == "rs:weak"


def test_pass_a_no_benchmark_skips_rs_filter():
    # benchmark absent → RS non appliquée en dur (fallback gracieux) → passe
    closes = [10.0 + i * 0.05 for i in range(200)]
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("NOBENCH", df, None)
    assert reason == "ok"
    assert signals["rs_signal"] is False  # pas de benchmark → pas de signal, mais pas rejeté
