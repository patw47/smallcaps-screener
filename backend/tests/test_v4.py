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
from v4 import build_cohort, market_return_21d


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
    assert market_return_21d(_series([0.001] * (v4.CFG["mkt_window"] - 5))) is None


def test_market_up_gives_empty_cohort(edgar_stub):
    edgar_stub["AAA"] = False
    tradables = [("AAA", {"price": 5.0, "change_1m": -0.10})]
    cohort, note, mkt, prelist = build_cohort(tradables, {}, _bench(+0.002))
    assert cohort == []
    assert note == {"code": "market_bullish", "w": v4.CFG["mkt_window"],
                    "mkt": pytest.approx(mkt, abs=1e-4)}


def test_no_benchmark_gives_empty_cohort(edgar_stub):
    cohort, note, mkt, prelist = build_cohort([("AAA", {"price": 5.0, "change_1m": -0.10})], {}, None)
    assert cohort == []
    assert note == {"code": "benchmark_missing"}


def test_entry_rules(edgar_stub):
    bench = _bench(-0.002)  # marché baissier
    edgar_stub.update({"OK": False, "DIL": True, "MUTE_ABSENT": None})
    tradables = [
        ("OK", {"price": 5.0, "change_1m": -0.10}),        # qualifie
        ("PRICEY", {"price": 9.0, "change_1m": -0.10}),    # prix > seuil
        ("FLAT", {"price": 5.0, "change_1m": -0.01}),      # chute insuffisante
        ("DIL", {"price": 5.0, "change_1m": -0.10}),       # dilution pendante
        ("MUTE_ABSENT", {"price": 5.0, "change_1m": -0.10}),  # EDGAR renvoie flag None
        ("UNKNOWN", {"price": 5.0, "change_1m": -0.10}),   # EDGAR renvoie None (pas dans stub)
        ("NOPRICE", {"price": None, "change_1m": -0.10}),  # signal manquant
    ]
    cohort, note, mkt, prelist = build_cohort(tradables, {}, bench)
    assert [e["ticker"] for e in cohort] == ["OK"]
    assert note["code"] == "market_bearish" and note["n"] == 1
    e = cohort[0]
    assert e["margins"]["price"] == pytest.approx(v4.CFG["price_max"] - 5.0)
    assert e["margins"]["change_1m"] == pytest.approx(v4.CFG["chg1m_max"] - (-0.10))
    assert e["mkt21"] < 0


def test_beta_resid_and_sort(edgar_stub):
    n = 200
    rng = np.random.default_rng(7)
    bench_rets = rng.normal(-0.002, 0.01, n)
    bench_rets[-v4.CFG["mkt_window"]:] = -0.004   # fin baissière garantie (condition §2.4)
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
    cohort, _, _, _ = build_cohort(tradables, prices, bench)
    by = {e["ticker"]: e for e in cohort}
    assert by["HIBETA"]["beta"] == pytest.approx(2.0, abs=0.3)
    assert by["HIBETA"]["corr"] > 0.9
    assert abs(by["IDIO"]["beta"]) < 0.5
    # resid = chg1m − bêta × mkt21
    mkt = by["HIBETA"]["mkt21"]
    assert by["HIBETA"]["resid"] == pytest.approx(-0.08 - by["HIBETA"]["beta"] * mkt, abs=1e-3)
    # IDIO a chuté bien plus que son bêta n'explique → plus survendu → premier
    assert cohort[0]["ticker"] == "IDIO"


def test_cohort_selection_frozen(edgar_stub):
    """
    Non-régression de la sélection (Epic 8 S1) : sur une fixture de marché baissier,
    le JEU de tickers ET leur ORDRE sont figés. Rouge si un ticker entre, sort ou
    change de rang — le refactor des notes en codes ne doit rien déplacer.
    Bêta identique pour tous (même série de prix) ⇒ le résidu ordonne par chute.
    """
    n = 200
    rng = np.random.default_rng(11)
    bench_rets = rng.normal(-0.002, 0.01, n)
    bench_rets[-v4.CFG["mkt_window"]:] = -0.004      # fin baissière garantie
    bench = _series(list(bench_rets))
    market = _series(list(bench_rets))               # titres de bêta ~1

    edgar_stub.update({"SHALLOW": False, "DEEP": False, "MID": False,
                       "DIL": True, "PRICEY": False, "FLAT": False})
    tradables = [
        ("SHALLOW", {"price": 5.0, "change_1m": -0.12}),
        ("DEEP", {"price": 4.0, "change_1m": -0.40}),
        ("MID", {"price": 6.0, "change_1m": -0.25}),
        ("DIL", {"price": 5.0, "change_1m": -0.30}),     # dilution pendante → hors liste
        ("PRICEY", {"price": 99.0, "change_1m": -0.30}),  # prix > seuil → hors liste
        ("FLAT", {"price": 5.0, "change_1m": -0.01}),    # chute insuffisante → hors liste
        ("MUTE", {"price": 5.0, "change_1m": -0.35}),    # EDGAR muet → hors liste
    ]
    prices = {tk: pd.DataFrame({"Close": market}) for tk, _ in tradables}

    cohort, note, _, prelist = build_cohort(tradables, prices, bench)
    assert [e["ticker"] for e in cohort] == ["DEEP", "MID", "SHALLOW"]
    assert note["code"] == "market_bearish" and note["n"] == 3
    assert prelist == []   # jour baissier : la pré-liste reste vide


def test_snapshot_carries_cohort(tmp_path, monkeypatch, edgar_stub):
    import screener_backend as sb
    monkeypatch.setattr(sb, "HISTORY_DIR", tmp_path)
    out = {
        "scanned_at": "2026-07-06T12:00:00+00:00",
        "stocks": [],
        "v4_cohort": [{"ticker": "OK", "price": 5.0}],
        "v4_note": {"code": "market_bearish", "w": 21, "mkt": -0.03, "n": 1},
    }
    sb._write_snapshot(out)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    snap = json.loads(files[0].read_text())
    assert snap["v4_cohort"][0]["ticker"] == "OK"
    assert snap["v4_note"]["code"] == "market_bearish"


def test_prelist_on_market_up(edgar_stub):
    tradables = [
        ("A1", {"price": 5.0, "change_1m": -0.20}),
        ("A2", {"price": 5.0, "change_1m": -0.05}),
        ("BIG", {"price": 20.0, "change_1m": -0.20}),   # prix > 8 → exclu
    ]
    cohort, note, mkt, prelist = build_cohort(tradables, {}, _bench(+0.002))
    assert cohort == [] and mkt > 0
    # triée par chute (plus massacré d'abord), sans appel EDGAR (stub non consulté)
    assert [e["ticker"] for e in prelist] == ["A1", "A2"]


def test_tracking_checkpoint_and_window(tmp_path):
    from v4 import build_tracking

    # snapshot : entrée ENTRY à 10.0 le 2025-06-02 (lundi)
    snap = {"scanned_at": "2025-06-02T20:00:00+00:00",
            "v4_cohort": [{"ticker": "ENTRY", "price": 10.0, "resid": -0.12, "beta": 1.1},
                          {"ticker": "GONE", "price": 4.0}]}
    (tmp_path / "20250602_200000.json").write_text(json.dumps(snap))
    # doublon plus tardif : la PREMIÈRE entrée doit gagner
    snap2 = {"scanned_at": "2025-06-04T20:00:00+00:00",
             "v4_cohort": [{"ticker": "ENTRY", "price": 11.0}]}
    (tmp_path / "20250604_200000.json").write_text(json.dumps(snap2))

    # série de prix : 8 séances APRÈS l'entrée, r5 = +5 % (> seuil de test)
    idx = pd.bdate_range("2025-06-03", periods=8)
    closes = [10.2, 10.4, 10.3, 10.4, 10.5, 10.6, 10.4, 10.8]
    prices = {"ENTRY": pd.DataFrame({"Close": pd.Series(closes, index=idx)})}

    rows = build_tracking(prices, tmp_path)
    by = {r["ticker"]: r for r in rows}
    e = by["ENTRY"]
    assert e["entry_price"] == 10.0            # première entrée conservée
    assert e["days_held"] == 8
    assert e["ret"] == pytest.approx(0.08)
    assert e["checkpoint"] == {"code": "week_one"}
    assert e["ret_5"] == pytest.approx(0.05)
    assert e["status"] == {"code": "above"}
    # ticker sans données de prix → signalé, jamais fatal
    assert by["GONE"]["status"] == {"code": "no_data"}


def test_v4_alert_dedup(tmp_path, monkeypatch):
    import alerts
    sent = []
    cohort = [{"ticker": "AAA", "price": 5.0, "change_1m": -0.10, "resid": -0.12}]
    state = tmp_path / "alerts_state.json"
    out1 = alerts.notify_new_v4_entries(cohort, state_path=state, dedup_days=5,
                                        send_fn=lambda t: sent.append(t) or True)
    assert out1 == ["AAA"] and "Cohorte v4" in sent[0] and "pas un conseil" in sent[0]
    # deuxième appel dans la fenêtre de dédup → silence
    out2 = alerts.notify_new_v4_entries(cohort, state_path=state, dedup_days=5,
                                        send_fn=lambda t: sent.append(t) or True)
    assert out2 == [] and len(sent) == 1
    # échec d'envoi → état non enregistré → retry possible
    cohort2 = [{"ticker": "BBB", "price": 3.0, "change_1m": -0.08, "resid": None}]
    out3 = alerts.notify_new_v4_entries(cohort2, state_path=state, dedup_days=5,
                                        send_fn=lambda t: False)
    assert out3 == []
    out4 = alerts.notify_new_v4_entries(cohort2, state_path=state, dedup_days=5,
                                        send_fn=lambda t: True)
    assert out4 == ["BBB"]


def test_tracking_below_threshold_too_early_and_tz(tmp_path):
    from v4 import build_tracking

    snap = {"scanned_at": "2025-06-02T20:00:00+00:00",
            "v4_cohort": [{"ticker": "SLOW", "price": 10.0},
                          {"ticker": "YOUNG", "price": 10.0}]}
    (tmp_path / "20250602_200000.json").write_text(json.dumps(snap))

    # SLOW : 6 séances, r5 = +1 % (< seuil de test) — index TZ-AWARE comme yfinance
    idx6 = pd.bdate_range("2025-06-03", periods=6, tz="UTC")
    slow = pd.Series([10.0, 10.05, 10.0, 10.05, 10.1, 10.0], index=idx6)
    # YOUNG : 2 séances seulement → trop tôt
    idx2 = pd.bdate_range("2025-06-03", periods=2)
    young = pd.Series([10.1, 10.2], index=idx2)

    rows = build_tracking({"SLOW": pd.DataFrame({"Close": slow}),
                           "YOUNG": pd.DataFrame({"Close": young})}, tmp_path)
    by = {r["ticker"]: r for r in rows}
    assert by["SLOW"]["status"] == {"code": "below"}
    assert by["SLOW"]["ret_5"] == pytest.approx(0.01)
    assert by["YOUNG"]["checkpoint"] == {"code": "too_early"}
    assert by["YOUNG"]["status"] == {"code": "too_early", "d": 2, "cp": v4.CFG["checkpoint_day"]}


def test_tracking_window_close_labels(tmp_path):
    from v4 import build_tracking
    horizon = v4.CFG["horizon"]

    snap = {"scanned_at": "2025-01-06T20:00:00+00:00",
            "v4_cohort": [{"ticker": "BOOM", "price": 10.0}, {"ticker": "BUST", "price": 10.0}]}
    (tmp_path / "20250106_200000.json").write_text(json.dumps(snap))

    idx = pd.bdate_range("2025-01-07", periods=horizon + 5)
    boom = pd.Series([10.0] * (horizon - 1) + [21.0] * 6, index=idx)   # ≥ +100 % au checkpoint
    bust = pd.Series([10.0] * (horizon - 1) + [4.0] * 6, index=idx)    # ≤ −50 % au checkpoint

    rows = build_tracking({"BOOM": pd.DataFrame({"Close": boom}),
                           "BUST": pd.DataFrame({"Close": bust})}, tmp_path)
    by = {r["ticker"]: r for r in rows}
    assert by["BOOM"]["checkpoint"] == {"code": "window_closed", "h": horizon}
    assert by["BOOM"]["status"] == {"code": "explosion"}
    assert by["BUST"]["status"] == {"code": "crash"}


# ---------------------------------------------------------------------------
# Cycle de vie (Epic 8 S4) — trois phases exclusives : en observation, clôturée,
# sans données. Le classement de l'écran se lit dans `phase`, jamais dans le texte.
# ---------------------------------------------------------------------------

def _entry_snapshot(tmp_path, tickers):
    snap = {"scanned_at": "2025-01-06T20:00:00+00:00",
            "v4_cohort": [{"ticker": tk, "price": 10.0} for tk in tickers]}
    (tmp_path / "20250106_200000.json").write_text(json.dumps(snap))


def _flat(n_sessions, price=10.0):
    """Série plate de n séances de bourse APRÈS le 2025-01-06 (date d'entrée)."""
    return pd.DataFrame({"Close": pd.Series(
        [price] * n_sessions, index=pd.bdate_range("2025-01-07", periods=n_sessions))})


def test_tracking_phase_partition(tmp_path):
    """Classement : au-delà de l'horizon = clôturée, plus jeune = en observation,
    sans données de prix = ni l'une ni l'autre. Aucune ligne perdue ni dupliquée."""
    from v4 import build_tracking
    horizon = v4.CFG["horizon"]
    _entry_snapshot(tmp_path, ["OLD", "YOUNG", "GONE"])

    rows = build_tracking({"OLD": _flat(horizon + 8), "YOUNG": _flat(horizon - 20)}, tmp_path)
    by_phase = {p: sorted(r["ticker"] for r in rows if r["phase"] == p)
                for p in ("open", "closed", "no_data")}
    assert by_phase == {"open": ["YOUNG"], "closed": ["OLD"], "no_data": ["GONE"]}
    assert sum(len(v) for v in by_phase.values()) == len(rows) == 3

    by = {r["ticker"]: r for r in rows}
    assert by["OLD"]["days_left"] == 0                 # clôturée : plus rien à attendre
    assert by["YOUNG"]["days_left"] == 20              # séances restantes avant clôture
    assert by["GONE"]["days_held"] is None and by["GONE"]["days_left"] is None
    assert by["GONE"]["status"] == {"code": "no_data"}  # code dédié, toujours affiché


def test_tracking_phase_boundary_exact(tmp_path):
    """Frontière : pile à l'horizon la fenêtre est close, une séance avant elle court."""
    from v4 import build_tracking
    horizon = v4.CFG["horizon"]
    _entry_snapshot(tmp_path, ["EXACT", "ONE_LESS"])

    rows = build_tracking({"EXACT": _flat(horizon), "ONE_LESS": _flat(horizon - 1)}, tmp_path)
    by = {r["ticker"]: r for r in rows}
    assert by["EXACT"]["days_held"] == horizon
    assert by["EXACT"]["phase"] == "closed"
    assert by["EXACT"]["checkpoint"] == {"code": "window_closed", "h": horizon}
    assert by["ONE_LESS"]["days_held"] == horizon - 1
    assert by["ONE_LESS"]["phase"] == "open"
    assert by["ONE_LESS"]["days_left"] == 1


def test_checkpoint_is_not_an_exit(tmp_path):
    """Un titre sous le seuil au point de contrôle reste en observation : couper
    les retardataires détruirait le rendement mesuré du panier."""
    from v4 import build_tracking
    _entry_snapshot(tmp_path, ["LATE"])
    n = v4.CFG["checkpoint_day"] + 3
    falling = pd.DataFrame({"Close": pd.Series(
        [9.0] * n, index=pd.bdate_range("2025-01-07", periods=n))})

    row = build_tracking({"LATE": falling}, tmp_path)[0]
    assert row["status"] == {"code": "below"}
    assert row["phase"] == "open"
