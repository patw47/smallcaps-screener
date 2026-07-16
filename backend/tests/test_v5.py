"""
Tests offline des cohortes v5 (Epic 5) — v5.py, aucun réseau.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_v5.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import json

import numpy as np
import pandas as pd
import pytest

import v5
from v5 import build_cohorts, build_tracking


def _series(returns, start=10.0):
    idx = pd.bdate_range("2025-01-01", periods=len(returns) + 1)
    prices = start * np.cumprod([1.0] + [1 + r for r in returns])
    return pd.Series(prices, index=idx)


def _bench(daily, n=200, tail=None):
    """Benchmark ; tail = rendements imposés sur les dernières séances."""
    rets = [daily] * n
    if tail:
        rets[-len(tail):] = tail
    return _series(rets)


def _stock_df(chg7=0.0, vol_mult=1.0, n=140):
    """Titre plat à 10 $, chute régulière sur les 7 dernières séances jusqu'à 10×(1+chg7).
    Volume constant 100k, multiplié par vol_mult sur les 7 dernières séances."""
    idx = pd.bdate_range("2025-01-01", periods=n)
    closes = np.full(n, 10.0)
    closes[-7:] = np.linspace(10.0, 10.0 * (1 + chg7), 7)
    vols = np.full(n, 100_000.0)
    vols[-7:] *= vol_mult
    return pd.DataFrame({"Close": pd.Series(closes, index=idx),
                         "Volume": pd.Series(vols, index=idx)})


@pytest.fixture
def edgar_stub(monkeypatch):
    flags = {}

    def fake(ticker, now=None, window_days=None):
        if ticker not in flags:
            return None
        return {"dilution_flag": flags[ticker]}

    import edgar
    monkeypatch.setattr(edgar, "survival_signals", fake)
    return flags


def test_three_windows_present_and_market_up_pause(edgar_stub):
    out = build_cohorts([("AAA", {"price": 5.0, "cmf": 0.1})],
                        {"AAA": _stock_df(chg7=-0.20)}, _bench(+0.002))
    assert set(out["windows"]) == {str(w) for w in v5.CFG["windows"]}
    for w in v5.CFG["windows"]:
        block = out["windows"][str(w)]
        assert block["cohort"] == []
        assert "haussier" in block["note"]
    # règles-titre passées sur 7 j → pré-liste, SANS appel EDGAR (stub vide non consulté)
    assert [e["ticker"] for e in out["windows"]["7"]["prelist"]] == ["AAA"]
    assert out["flash"] is False


def test_no_benchmark(edgar_stub):
    out = build_cohorts([("AAA", {"price": 5.0, "cmf": 0.1})], {}, None)
    for w in v5.CFG["windows"]:
        assert "indisponible" in out["windows"][str(w)]["note"]
    assert out["flash"] is False and out["flash_ret3"] is None


def test_entry_rules_bear_market(edgar_stub):
    bench = _bench(-0.002)
    edgar_stub.update({"OK": False, "DIL": True, "MUTE": None})
    tradables = [
        ("OK",      {"price": 5.0, "cmf": 0.10}),   # qualifie (7 j)
        ("PRICEY",  {"price": 9.0, "cmf": 0.10}),   # prix > seuil
        ("SHALLOW", {"price": 5.0, "cmf": 0.10}),   # chute 7 j insuffisante
        ("CMFBAD",  {"price": 5.0, "cmf": -0.30}),  # CMF ≤ seuil
        ("LOUD",    {"price": 5.0, "cmf": 0.10}),   # chute SUR volume (2×)
        ("DIL",     {"price": 5.0, "cmf": 0.10}),   # dilution pendante
        ("MUTE",    {"price": 5.0, "cmf": 0.10}),   # EDGAR muet ⇒ non qualifié
    ]
    prices = {
        "OK": _stock_df(chg7=-0.20), "PRICEY": _stock_df(chg7=-0.20),
        "SHALLOW": _stock_df(chg7=-0.05), "CMFBAD": _stock_df(chg7=-0.20),
        "LOUD": _stock_df(chg7=-0.20, vol_mult=2.0),
        "DIL": _stock_df(chg7=-0.20), "MUTE": _stock_df(chg7=-0.20),
    }
    out = build_cohorts(tradables, prices, bench)
    b7 = out["windows"]["7"]
    assert b7["mkt"] < 0
    assert [e["ticker"] for e in b7["cohort"]] == ["OK"]
    e = b7["cohort"][0]
    assert e["chg"] == pytest.approx(-0.20, abs=1e-3)
    assert e["vol_calm"] == pytest.approx(1.0, abs=0.05)
    # la chute de 7 séances (−20 %) qualifie aussi sur 14 et 21 j (fenêtres englobantes)
    assert [x["ticker"] for x in out["windows"]["14"]["cohort"]] == ["OK"]
    assert [x["ticker"] for x in out["windows"]["21"]["cohort"]] == ["OK"]


def test_cohort_sorted_deepest_first(edgar_stub):
    edgar_stub.update({"DEEP": False, "LESS": False})
    tradables = [("LESS", {"price": 5.0, "cmf": 0.1}), ("DEEP", {"price": 5.0, "cmf": 0.1})]
    prices = {"LESS": _stock_df(chg7=-0.18), "DEEP": _stock_df(chg7=-0.40)}
    out = build_cohorts(tradables, prices, _bench(-0.002))
    assert [e["ticker"] for e in out["windows"]["7"]["cohort"]] == ["DEEP", "LESS"]


def test_flash_flag(edgar_stub):
    # 3 dernières séances à −3 % chacune → ret3 ≈ −8,7 % ≤ seuil de test
    out = build_cohorts([], {}, _bench(+0.001, tail=[-0.03, -0.03, -0.03]))
    assert out["flash"] is True
    assert out["flash_ret3"] <= v5.CFG["flash_thr"]
    # baisse ordinaire → pas de drapeau
    out2 = build_cohorts([], {}, _bench(-0.002))
    assert out2["flash"] is False


def test_tracking_per_window(tmp_path):
    snap = {"scanned_at": "2025-06-02T20:00:00+00:00",
            "v5": {"windows": {
                "7": {"cohort": [{"ticker": "ENTRY", "price": 10.0, "chg": -0.2}]},
                "14": {"cohort": [{"ticker": "ENTRY", "price": 10.0, "chg": -0.18}]},
                "21": {"cohort": []},
            }}}
    (tmp_path / "20250602_200000.json").write_text(json.dumps(snap))
    # doublon plus tardif : la PREMIÈRE entrée gagne
    snap2 = {"scanned_at": "2025-06-04T20:00:00+00:00",
             "v5": {"windows": {"7": {"cohort": [{"ticker": "ENTRY", "price": 11.0}]}}}}
    (tmp_path / "20250604_200000.json").write_text(json.dumps(snap2))

    idx = pd.bdate_range("2025-06-03", periods=8)
    closes = [10.2, 10.4, 10.3, 10.4, 10.5, 10.6, 10.4, 10.8]
    prices = {"ENTRY": pd.DataFrame({"Close": pd.Series(closes, index=idx)})}

    rows = build_tracking(prices, tmp_path)
    assert {(r["window"], r["ticker"]) for r in rows} == {(7, "ENTRY"), (14, "ENTRY")}
    for r in rows:
        assert r["entry_price"] == 10.0
        assert r["ret"] == pytest.approx(0.08)
        assert r["status"] == "au-dessus"


def test_snapshot_carries_v5(tmp_path, monkeypatch):
    import screener_backend as sb
    monkeypatch.setattr(sb, "HISTORY_DIR", tmp_path)
    out = {
        "scanned_at": "2026-07-09T12:00:00+00:00", "stocks": [],
        "v5": {"windows": {"7": {"mkt": -0.02, "note": "baissier → 1 qualifiés",
                                 "cohort": [{"ticker": "OK", "price": 5.0}],
                                 "prelist": [{"ticker": "DROP_ME"}]}},
               "flash": True, "flash_ret3": -0.09, "tracking": [{"ticker": "DROP_ME"}]},
    }
    sb._write_snapshot(out)
    snap = json.loads(next(tmp_path.glob("*.json")).read_text())
    b7 = snap["v5"]["windows"]["7"]
    assert b7["cohort"][0]["ticker"] == "OK" and b7["mkt"] == -0.02
    assert snap["v5"]["flash"] is True
    # pré-liste et tracking dérivables → jamais dans le snapshot ; display non plus
    # (les paramètres d'affichage — l'edge — ne sont jamais persistés dans l'historique)
    assert "prelist" not in b7 and "tracking" not in snap["v5"]
    assert "display" not in snap


def test_tracking_ignores_snapshots_without_v5(tmp_path):
    (tmp_path / "20250602_200000.json").write_text(json.dumps(
        {"scanned_at": "2025-06-02T20:00:00+00:00", "v4_cohort": [{"ticker": "X", "price": 5.0}]}))
    assert build_tracking({}, tmp_path) == []


def test_v5_alert_merge_and_dedup(tmp_path):
    import alerts
    sent = []
    windows = {
        "7":  {"cohort": [{"ticker": "AAA", "price": 5.0, "chg": -0.20, "vol_calm": 0.8}]},
        "14": {"cohort": [{"ticker": "AAA", "price": 5.0, "chg": -0.18, "vol_calm": 0.9},
                          {"ticker": "BBB", "price": 3.0, "chg": -0.16, "vol_calm": 1.1}]},
        "21": {"cohort": []},
    }
    state = tmp_path / "alerts_state.json"
    out1 = alerts.notify_new_v5_entries(windows, state_path=state, dedup_days=5,
                                        send_fn=lambda t: sent.append(t) or True)
    assert sorted(out1) == ["AAA", "BBB"]
    assert "Cohorte v5" in sent[0] and "pas un conseil" in sent[0]
    assert "fenêtre(s) 7/14 j" in sent[0]          # AAA agrégé sur ses deux fenêtres
    # deuxième scan dans la fenêtre de dédup → silence
    out2 = alerts.notify_new_v5_entries(windows, state_path=state, dedup_days=5,
                                        send_fn=lambda t: sent.append(t) or True)
    assert out2 == [] and len(sent) == 1
    # échec d'envoi → état non enregistré → retry possible
    windows2 = {"7": {"cohort": [{"ticker": "CCC", "price": 2.0, "chg": -0.30, "vol_calm": 0.5}]}}
    assert alerts.notify_new_v5_entries(windows2, state_path=state, dedup_days=5,
                                        send_fn=lambda t: False) == []
    assert alerts.notify_new_v5_entries(windows2, state_path=state, dedup_days=5,
                                        send_fn=lambda t: True) == ["CCC"]
