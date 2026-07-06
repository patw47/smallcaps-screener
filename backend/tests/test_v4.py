"""
Tests offline de la cohorte v4 (Epic 4 S2) — v4.py, aucun réseau.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_v4.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import json

import numpy as np
import pandas as pd
import pytest

import v4
from v4 import build_cohort, market_return_21d, V4_MKT_WINDOW


def _series(returns, start=10.0):
    """Série de clôtures à partir de rendements quotidiens."""
    idx = pd.bdate_range("2025-01-01", periods=len(returns) + 1)
    prices = start * np.cumprod([1.0] + [1 + r for r in returns])
    return pd.Series(prices, index=idx)


def _bench(daily, n=200):
    return _series([daily] * n)


@pytest.fixture
def edgar_stub(monkeypatch):
    """survival_signals contrôlé par un dict ticker → dilution_flag."""
    flags = {}

    def fake(ticker, now=None, window_days=None):
        if ticker not in flags:
            return None
        return {"dilution_flag": flags[ticker]}

    import edgar
    monkeypatch.setattr(edgar, "survival_signals", fake)
    return flags


def test_market_return_none_if_short():
    assert market_return_21d(None) is None
    assert market_return_21d(_series([0.001] * (V4_MKT_WINDOW - 5))) is None


def test_market_up_gives_empty_cohort(edgar_stub):
    edgar_stub["AAA"] = False
    tradables = [("AAA", {"price": 5.0, "change_1m": -0.10})]
    cohort, note = build_cohort(tradables, {}, _bench(+0.002))
    assert cohort == []
    assert "haussier" in note


def test_no_benchmark_gives_empty_cohort(edgar_stub):
    cohort, note = build_cohort([("AAA", {"price": 5.0, "change_1m": -0.10})], {}, None)
    assert cohort == []
    assert "indisponible" in note


def test_entry_rules(edgar_stub):
    bench = _bench(-0.002)  # marché baissier
    edgar_stub.update({"OK": False, "DIL": True, "MUTE_ABSENT": None})
    tradables = [
        ("OK", {"price": 5.0, "change_1m": -0.10}),        # qualifie
        ("PRICEY", {"price": 9.0, "change_1m": -0.10}),    # prix > 8
        ("FLAT", {"price": 5.0, "change_1m": -0.01}),      # chute < 3 %
        ("DIL", {"price": 5.0, "change_1m": -0.10}),       # dilution pendante
        ("MUTE_ABSENT", {"price": 5.0, "change_1m": -0.10}),  # EDGAR renvoie flag None
        ("UNKNOWN", {"price": 5.0, "change_1m": -0.10}),   # EDGAR renvoie None (pas dans stub)
        ("NOPRICE", {"price": None, "change_1m": -0.10}),  # signal manquant
    ]
    cohort, note = build_cohort(tradables, {}, bench)
    assert [e["ticker"] for e in cohort] == ["OK"]
    assert "1 qualifiés" in note
    e = cohort[0]
    assert e["margins"]["price"] == pytest.approx(3.0)
    assert e["margins"]["change_1m"] == pytest.approx(0.07)
    assert e["mkt21"] < 0


def test_beta_resid_and_sort(edgar_stub):
    n = 200
    rng = np.random.default_rng(7)
    bench_rets = rng.normal(-0.002, 0.01, n)
    bench_rets[-V4_MKT_WINDOW:] = -0.004   # fin baissière garantie (condition §2.4)
    bench = _series(list(bench_rets))
    # HIBETA suit le marché ×2 ; IDIO chute indépendamment (bêta ~0)
    hib = _series(list(2.0 * bench_rets))
    idio = _series(list(rng.normal(-0.004, 0.02, n)))
    edgar_stub.update({"HIBETA": False, "IDIO": False})
    tradables = [
        ("HIBETA", {"price": 5.0, "change_1m": -0.08}),
        ("IDIO", {"price": 5.0, "change_1m": -0.30}),
    ]
    prices = {"HIBETA": pd.DataFrame({"Close": hib}), "IDIO": pd.DataFrame({"Close": idio})}
    cohort, _ = build_cohort(tradables, prices, bench)
    by = {e["ticker"]: e for e in cohort}
    assert by["HIBETA"]["beta"] == pytest.approx(2.0, abs=0.3)
    assert by["HIBETA"]["corr"] > 0.9
    assert abs(by["IDIO"]["beta"]) < 0.5
    # resid = chg1m − bêta × mkt21
    mkt = by["HIBETA"]["mkt21"]
    assert by["HIBETA"]["resid"] == pytest.approx(-0.08 - by["HIBETA"]["beta"] * mkt, abs=1e-3)
    # IDIO a chuté bien plus que son bêta n'explique → plus survendu → premier
    assert cohort[0]["ticker"] == "IDIO"


def test_snapshot_carries_cohort(tmp_path, monkeypatch, edgar_stub):
    import screener_backend as sb
    monkeypatch.setattr(sb, "HISTORY_DIR", tmp_path)
    out = {
        "scanned_at": "2026-07-06T12:00:00+00:00",
        "stocks": [],
        "v4_cohort": [{"ticker": "OK", "price": 5.0}],
        "v4_note": "marché baissier → 1 qualifiés",
    }
    sb._write_snapshot(out)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    snap = json.loads(files[0].read_text())
    assert snap["v4_cohort"][0]["ticker"] == "OK"
    assert "baissier" in snap["v4_note"]
