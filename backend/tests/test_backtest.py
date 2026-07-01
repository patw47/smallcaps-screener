"""Tests offline du harnais de backtest (helpers purs, sans réseau)."""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import pandas as pd

from backtest import _forward_return, evaluate_ticker, _stats


def test_forward_return_basic():
    close = pd.Series([100.0, 105.0, 110.0, 120.0])
    # de l'indice 0 à 0+2 : 110/100 - 1 = +10%
    assert abs(_forward_return(close, 0, 2) - 0.10) < 1e-9


def test_forward_return_out_of_range():
    close = pd.Series([100.0, 110.0])
    assert _forward_return(close, 0, 5) is None       # pas assez de données forward


def test_stats_empty():
    assert _stats([]) == {"n": 0, "mean": None, "median": None, "hit": None}


def test_stats_hit_rate():
    s = _stats([0.1, -0.2, 0.3, 0.0])                 # 2 positifs sur 4
    assert s["n"] == 4
    assert s["hit"] == 0.5


def test_evaluate_ticker_uptrend_survives_and_measures_forward():
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series([5.0 + i * 0.05 for i in range(n)], index=idx)  # uptrend 5→~15, dans 2-25
    df = pd.DataFrame({
        "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": [300_000] * n,
    }, index=idx)
    res = evaluate_ticker(df, bench_close=None, forward_days=21)
    assert res is not None
    survived, fwd, rs = res
    assert survived is True          # uptrend liquide passe la Passe A (RS non exigée sans benchmark)
    assert fwd > 0                   # rendement forward positif sur un uptrend
