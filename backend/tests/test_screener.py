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
    _atr, _obv_rising, _pct_of_high, _accum_fraction,
    _rank_pct, _factor_composite, TECH_FACTORS,
    _score_candidates, _build_positives_flags, analyze_prices,
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
    # titre ~+20% vs benchmark ~+5% sur la fenêtre → surperforme, RS-line monte, magnitude > 0
    stock = pd.Series([100 * (1.20 ** (i / 63)) for i in range(64)])
    bench = pd.Series([100 * (1.05 ** (i / 63)) for i in range(64)])
    outperf, rising, strength = _rs_metrics(stock, bench, 63, 21)
    assert outperf is True
    assert rising is True
    assert strength > 0.10          # ~+15% de surperf


def test_rs_metrics_underperformance():
    stock = pd.Series([100 * (0.90 ** (i / 63)) for i in range(64)])  # baisse
    bench = pd.Series([100 * (1.05 ** (i / 63)) for i in range(64)])  # hausse
    outperf, rising, strength = _rs_metrics(stock, bench, 63, 21)
    assert outperf is False
    assert rising is False
    assert strength < 0


def test_rs_metrics_no_benchmark():
    assert _rs_metrics(pd.Series([1.0] * 100), None, 63, 21) == (None, None, None)


# ---------------------------------------------------------------------------
# Palier 2 — ATR, OBV, position 52 semaines
# ---------------------------------------------------------------------------

def test_atr_needs_high_low():
    idx = pd.date_range("2025-01-01", periods=30, freq="B")
    df = pd.DataFrame({"Close": range(30), "Volume": [1] * 30}, index=idx)  # pas de High/Low
    assert _atr(df, 20) is None


def test_atr_constant_range():
    idx = pd.date_range("2025-01-01", periods=30, freq="B")
    close = pd.Series([10.0] * 30, index=idx)
    df = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close}, index=idx)
    # range quotidien constant = 2, pas de gap → ATR = 2
    assert abs(_atr(df, 20) - 2.0) < 1e-9


def test_obv_rising_on_uptrend():
    close = pd.Series([10.0 + i for i in range(30)])   # hausse continue
    volume = pd.Series([1000] * 30)
    assert _obv_rising(close, volume, 21) is True


def test_obv_falling_on_downtrend():
    close = pd.Series([40.0 - i for i in range(30)])   # baisse continue
    volume = pd.Series([1000] * 30)
    assert _obv_rising(close, volume, 21) is False


def test_pct_of_high():
    close = pd.Series([50.0, 80.0, 100.0, 90.0])       # dernier = 90, plus-haut = 100
    assert abs(_pct_of_high(close, 252) - 0.90) < 1e-9


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


# ---------------------------------------------------------------------------
# Scoring PERCENTILE de facteurs continus
# ---------------------------------------------------------------------------

def test_rank_pct_orders_and_neutral_none():
    p = _rank_pct([10.0, 30.0, 20.0])
    assert p[1] == 1.0 and p[0] == 0.0        # plus grand → 1, plus petit → 0
    assert 0.0 < p[2] < 1.0
    assert _rank_pct([5.0, None])[1] == 0.5   # None → neutre


def test_accum_fraction_sign():
    vol = pd.Series([1000] * 30)
    assert _accum_fraction(pd.Series([10.0 + i for i in range(30)]), vol, 21) > 0.9    # tout acheteur
    assert _accum_fraction(pd.Series([40.0 - i for i in range(30)]), vol, 21) < -0.9   # tout vendeur


def test_factor_composite_best_item_tops():
    # item 1 = meilleur sur TOUS les facteurs (accum/rs/pivot hauts ; atr_ratio/ext bas)
    items = [
        {"f_accum": 0.1, "f_atr_ratio": 0.9, "f_pct_recent": 0.5, "f_ext": 0.30, "f_rs": 0.0},
        {"f_accum": 0.9, "f_atr_ratio": 0.4, "f_pct_recent": 0.99, "f_ext": 0.01, "f_rs": 0.5},
        {"f_accum": 0.3, "f_atr_ratio": 0.7, "f_pct_recent": 0.70, "f_ext": 0.20, "f_rs": 0.1},
    ]
    comp = _factor_composite(items, TECH_FACTORS)
    assert comp[1] == max(comp)               # le meilleur sur tout → composite max
    assert comp[1] > comp[0]


def test_scoring_mode_switch():
    # le fort > le faible dans les deux modes ; en continu, décile sur 2 items → 10 et 0
    strong = {
        "accumulation": True, "compressed": True, "near_pivot": True, "low_ext": True,
        "rs_turning": True, "price_above_ma50": True, "insider_buying": True,
        "cash_positive": True, "revenue_growth": 0.5, "low_float": True, "short_interest_pct": 20.0,
        "f_accum": 0.9, "f_atr_ratio": 0.4, "f_pct_recent": 0.99, "f_ext": 0.01, "f_rs": 0.5,
        "cash_bin": 1.0, "insider_pct": 30.0, "float_shares": 1e6,
    }
    weak = {
        "f_accum": 0.1, "f_atr_ratio": 0.9, "f_pct_recent": 0.4, "f_ext": 0.3, "f_rs": 0.0,
        "cash_bin": None, "insider_pct": 0.0, "float_shares": 9e8,
    }
    old = FILTERS["scoring_mode"]
    try:
        FILTERS["scoring_mode"] = "binary"
        c = [dict(strong), dict(weak)]
        _score_candidates(c)
        assert c[0]["score"] > c[1]["score"]

        FILTERS["scoring_mode"] = "continuous"
        c2 = [dict(strong), dict(weak)]
        _score_candidates(c2)
        assert c2[0]["score"] == 10 and c2[1]["score"] == 0   # rang décile sur 2 items
    finally:
        FILTERS["scoring_mode"] = old


# ---------------------------------------------------------------------------
# Niveau 1/2 — Passe A intégrée (offline, DataFrame synthétique)
# ---------------------------------------------------------------------------

def _make_df(closes, volumes):
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


def test_pass_a_rejects_downtrend():
    # baisse douce 35 → 15 : reste dans la bande de prix (2-25),
    # mais pente MA50 négative → rejet tendance (garde-fou couteau qui tombe)
    closes = [35.0 - i * 0.1 for i in range(200)]
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


def test_pass_a_accepts_price_below_rising_ma():
    # MA50 en hausse, prix repassé sous la MA50 (pullback tôt) : DÉSORMAIS accepté
    # (prix>MA50 n'est plus un filtre dur → on capte le début, pas seulement le déjà-reparti)
    closes = [10.0 + i * 0.1 for i in range(200)]  # uptrend franc
    closes[-1] = 22.0                              # dip final sous la MA50 (~27), dans 2-25
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("PB", df, None)
    assert reason == "ok"
    assert signals["price_above_ma50"] is False    # sous la MA50, mais gardé


def test_pass_a_weak_rs_not_rejected():
    # RS n'est plus un filtre dur (rs_require=False) → un titre qui sous-performe passe,
    # avec rs_turning=False (la RS ne repart pas) → il sera juste moins bien classé
    idx = pd.date_range("2025-01-01", periods=200, freq="B")
    closes = [10.0 + i * 0.01 for i in range(200)]        # uptrend mou
    df = _make_df(closes, [300_000] * 200)
    bench = pd.Series([100.0 * (1.6 ** (i / 199)) for i in range(200)], index=idx)  # benchmark fort
    signals, reason = analyze_prices("WEAKRS", df, bench)
    assert reason == "ok"
    assert signals["rs_turning"] is False


def test_pass_a_no_benchmark_ok():
    # benchmark absent → RS neutralisée, titre gardé
    closes = [10.0 + i * 0.05 for i in range(200)]
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("NOBENCH", df, None)
    assert reason == "ok"


def test_pass_a_near_pivot_and_low_ext_signals():
    # uptrend doux, dernier prix proche du plus-haut récent et proche de la MA50
    closes = [10.0 + i * 0.03 for i in range(200)]  # ~10 → ~16, dans 2-25
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("EARLY", df, None)
    assert reason == "ok"
    # dernier prix = plus-haut récent (série croissante) → près du pivot
    assert signals["near_pivot"] is True
    # pente douce → prix reste proche de la MA50 → peu étiré
    assert signals["low_ext"] is True
