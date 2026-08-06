"""
Marqueurs de risque À L'ENTRÉE des listes de purge — v4.py / v5.py.

Le dossier de risque (scoring.risk_markers) est posé sur chaque entrée de cohorte au
moment où elle est construite (drapeaux prix de la Passe A + drapeaux EDGAR déjà payés
par la règle dilution), persiste dans le snapshot daté, et se propage aux lignes de
suivi via les loaders d'entrées. Entrées antérieures au dossier → liste vide.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_cohort_risk_markers.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import json

import numpy as np
import pandas as pd
import pytest

import v4
import v5


def _series(returns, start=10.0):
    idx = pd.bdate_range("2025-01-01", periods=len(returns) + 1)
    prices = start * np.cumprod([1.0] + [1 + r for r in returns])
    return pd.Series(prices, index=idx)


def _bench(daily, n=200):
    return _series([daily] * n)


def _stock_df(chg7=0.0, n=140):
    """Titre plat à 10 $, chute régulière sur les 7 dernières séances, volume constant."""
    idx = pd.bdate_range("2025-01-01", periods=n)
    closes = np.full(n, 10.0)
    closes[-7:] = np.linspace(10.0, 10.0 * (1 + chg7), 7)
    vols = np.full(n, 100_000.0)
    return pd.DataFrame({"Close": pd.Series(closes, index=idx),
                         "Volume": pd.Series(vols, index=idx)})


@pytest.fixture
def edgar_rich(monkeypatch):
    """survival_signals complet : dilution basse (l'entrée qualifie) + going concern levé."""
    surv = {"dilution_flag": False,
            "late_filing_flag": False,
            "going_concern_flag": True, "going_concern_date": "2026-06-30"}
    import edgar
    monkeypatch.setattr(edgar, "survival_signals",
                        lambda tk, now=None, window_days=None: dict(surv))
    return surv


def test_v4_entry_carries_risk_markers(edgar_rich):
    sig = {"price": 5.0, "change_1m": -0.10,
           "sub_dollar_flag": True, "sub_dollar_days": 7,
           "reverse_split_flag": False}
    cohort, note, _, _ = v4.build_cohort([("AAA", sig)], {}, _bench(-0.002))
    (e,) = cohort
    codes = [m["code"] for m in e["risk_markers"]]
    assert codes == ["going_concern", "sub_dollar"]   # ordre = gravité décroissante
    assert e["risk_markers"][0]["level"] == "high"
    assert e["risk_markers"][0]["date"] == "2026-06-30"
    assert e["risk_markers"][1]["days"] == 7


def test_v4_tracking_inherits_entry_markers(tmp_path):
    markers = [{"code": "sub_dollar", "level": "low", "days": 7}]
    snap = {"scanned_at": "2026-08-01T00:00:00+00:00",
            "v4_cohort": [{"ticker": "NEW", "price": 5.0, "risk_markers": markers},
                          {"ticker": "OLD", "price": 4.0}]}   # entrée antérieure au dossier
    (tmp_path / "20260801_000000.json").write_text(json.dumps(snap))
    entries = v4._load_cohort_entries(tmp_path)
    assert entries["NEW"]["risk_markers"] == markers
    assert entries["OLD"]["risk_markers"] == []


def test_v5_entry_carries_risk_markers(edgar_rich):
    sig = {"price": 5.0, "cmf": 0.1,
           "sub_dollar_flag": False,
           "reverse_split_flag": True, "reverse_split_date": "2026-07-15"}
    out = v5.build_cohorts([("AAA", sig)], {"AAA": _stock_df(chg7=-0.20)}, _bench(-0.002))
    (e,) = out["windows"]["7"]["cohort"]
    codes = [m["code"] for m in e["risk_markers"]]
    assert codes == ["going_concern", "reverse_split"]
    assert e["risk_markers"][1]["date"] == "2026-07-15"


def test_v5_tracking_inherits_entry_markers(tmp_path):
    markers = [{"code": "going_concern", "level": "high", "date": "2026-06-30"}]
    snap = {"scanned_at": "2026-08-01T00:00:00+00:00",
            "v5": {"windows": {"7": {"cohort": [
                {"ticker": "NEW", "price": 5.0, "risk_markers": markers},
                {"ticker": "OLD", "price": 4.0}]}}}}
    (tmp_path / "20260801_000000.json").write_text(json.dumps(snap))
    entries = v5._load_entries(tmp_path)
    assert entries[(7, "NEW")]["risk_markers"] == markers
    assert entries[(7, "OLD")]["risk_markers"] == []
