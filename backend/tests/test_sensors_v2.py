"""
Tests offline des capteurs v2 (Sprint 4) : compression (percentile auto-référencé) et
accumulation (Chaikin Money Flow + ratio volume hausse/baisse).

Déterministes, sans réseau. Les fixtures CMF / up-down portent des valeurs calculées
À LA MAIN ; la compression est validée par des cas monotones (titre calme vs agité).

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_sensors_v2.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import pandas as pd

from screener_backend import (
    FILTERS, _cmf, _updown_vol_ratio, _compression_self_pct, _atr, analyze_prices,
)


# ---------------------------------------------------------------------------
# CMF — valeurs calculées à la main
# ---------------------------------------------------------------------------

def _hl_df(closes, vols, high, low):
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"High": [high] * n, "Low": [low] * n,
                         "Close": closes, "Volume": vols}, index=idx)


def test_cmf_hand_computed_mixed():
    # range constant 9..11 → MFM = close-10 (car ((c-9)-(11-c))/2 = (2c-20)/2 = c-10)
    # closes 11,11,9,10 → MFM 1,1,-1,0 ; vols 100 → MFV 100,100,-100,0 ; Σ=100 ; Σvol=400
    df = _hl_df([11.0, 11.0, 9.0, 10.0], [100, 100, 100, 100], high=11.0, low=9.0)
    assert abs(_cmf(df, 4) - 0.25) < 1e-9


def test_cmf_all_at_high_and_low():
    df_top = _hl_df([11.0] * 5, [100] * 5, high=11.0, low=9.0)   # clôture au plus haut → +1
    df_bot = _hl_df([9.0] * 5, [100] * 5, high=11.0, low=9.0)    # clôture au plus bas → -1
    assert abs(_cmf(df_top, 5) - 1.0) < 1e-9
    assert abs(_cmf(df_bot, 5) + 1.0) < 1e-9


def test_cmf_flat_day_contributes_zero():
    # high==low → MFM forcé à 0 (pas de division par zéro, pas d'exception)
    idx = pd.date_range("2025-01-01", periods=3, freq="B")
    df = pd.DataFrame({"High": [10.0, 10.0, 10.0], "Low": [10.0, 10.0, 10.0],
                       "Close": [10.0, 10.0, 10.0], "Volume": [100, 100, 100]}, index=idx)
    assert _cmf(df, 3) == 0.0


def test_cmf_volume_weighted():
    # même MFM mais pondéré : close 11 (MFM +1, vol 300), close 9 (MFM -1, vol 100)
    # Σ MFV = 300 - 100 = 200 ; Σ vol = 400 → CMF = 0.5
    df = _hl_df([11.0, 9.0], [300, 100], high=11.0, low=9.0)
    assert abs(_cmf(df, 2) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Ratio volume hausse/baisse — valeurs calculées à la main
# ---------------------------------------------------------------------------

def test_updown_vol_ratio_hand_computed():
    closes = pd.Series([10.0, 11.0, 10.0, 12.0, 11.0])   # diffs: _, +1, -1, +2, -1
    vols = pd.Series([999, 100, 200, 300, 400])          # window 4 → diffs[+1,-1,+2,-1] vols[100,200,300,400]
    # up (d>0) = 100 + 300 = 400 ; down (d<0) = 200 + 400 = 600 → 0.6667
    assert abs(_updown_vol_ratio(closes, vols, 4) - (400 / 600)) < 1e-9


def test_updown_vol_ratio_all_up_is_inf():
    closes = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])   # que des hausses
    vols = pd.Series([100] * 5)
    assert _updown_vol_ratio(closes, vols, 4) == float("inf")


def test_updown_vol_ratio_flat_is_none():
    closes = pd.Series([10.0] * 5)                        # aucune hausse ni baisse
    vols = pd.Series([100] * 5)
    assert _updown_vol_ratio(closes, vols, 4) is None


# ---------------------------------------------------------------------------
# Compression v2 — percentile auto-référencé (cas monotones)
# ---------------------------------------------------------------------------

def _band_df(widths):
    """Close constant à 10 ; range quotidien = 2×width[i]. TR = 2×width (close constant)."""
    n = len(widths)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = [10.0] * n
    return pd.DataFrame({"High": [10.0 + w for w in widths], "Low": [10.0 - w for w in widths],
                         "Close": close, "Volume": [100] * n}, index=idx)


def test_compression_self_pct_low_when_recently_quiet():
    # agité (width 1.0) longtemps puis calme sur ~20j (= fenêtre ATR20) : ATR20 s'effondre alors
    # que l'ATR90 reste élevé → ratio du jour au MINIMUM de sa propre distribution.
    df = _band_df([1.0] * 180 + [0.1] * 20)
    pct = _compression_self_pct(df, 20, 90, 252, 60)
    assert pct is not None
    assert pct < FILTERS["compression_pct_threshold"]   # comprimé : bas de sa propre distribution


def test_compression_self_pct_high_when_recently_volatile():
    # calme (0.1) longtemps puis agité sur ~20j → ratio du jour au HAUT de sa distribution
    df = _band_df([0.1] * 180 + [1.0] * 20)
    pct = _compression_self_pct(df, 20, 90, 252, 60)
    assert pct is not None
    assert pct > 0.75


def test_compression_self_pct_none_when_too_short():
    # historique trop court (ratio dispo ~10 obs < min_obs=60) → neutre, pas d'exception
    df = _band_df([1.0] * 100)
    assert _compression_self_pct(df, 20, 90, 252, 60) is None


# ---------------------------------------------------------------------------
# Intégration analyze_prices — v2 par défaut, v1 commutable
# ---------------------------------------------------------------------------

def _uptrend_ohlcv(n=200):
    closes = [10.0 + i * 0.05 for i in range(n)]
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"High": [c + 0.2 for c in closes], "Low": [c - 0.2 for c in closes],
                         "Close": closes, "Volume": [200_000] * n}, index=idx)


def test_analyze_prices_v2_exposes_sensor_fields():
    df = _uptrend_ohlcv()
    sig, reason = analyze_prices("V2", df, None)
    assert reason == "ok"
    for key in ("compression_pct", "cmf", "updown_vol_ratio", "atr_ratio"):
        assert key in sig
    assert isinstance(sig["compressed"], bool)
    assert isinstance(sig["accumulation"], bool)
    # les facteurs continus percentile suivent la v2
    assert sig["f_accum"] == _cmf(df, FILTERS["cmf_window"])
    assert sig["f_atr_ratio"] == _compression_self_pct(
        df, FILTERS["compression_window"], FILTERS["compression_baseline"],
        FILTERS["compression_pct_lookback"], FILTERS["compression_pct_min_obs"])


def test_analyze_prices_v1_switch():
    df = _uptrend_ohlcv()
    old = FILTERS["sensors_version"]
    try:
        FILTERS["sensors_version"] = "v1"
        sig, reason = analyze_prices("V1", df, None)
        assert reason == "ok"
        assert sig["compression_pct"] is None      # v1 : pas de percentile auto-référencé
        assert sig["cmf"] is None                  # v1 : pas de CMF
        atr_ratio = _atr(df, FILTERS["compression_window"]) / _atr(df, FILTERS["compression_baseline"])
        assert abs(sig["f_atr_ratio"] - atr_ratio) < 1e-9   # v1 : facteur = ATR20/ATR90
    finally:
        FILTERS["sensors_version"] = old


def test_score_weights_structure_unchanged():
    # garde-fou : aucun poids ajouté/retiré sans décision. Les VALEURS réelles ne
    # vivent plus dans le repo (Epic 6 S2 : defaults neutres, réel en config locale) —
    # leur gel est protégé par l'extraction + make check-edge, plus par ce test.
    w = FILTERS["score_weights"]
    assert set(w) == {"accumulation", "compression", "near_pivot", "low_ext",
                      "rs_turning", "above_ma", "insider", "cash", "revenue",
                      "low_float", "short"}
    assert all(isinstance(v, int) and v > 0 for v in w.values())
