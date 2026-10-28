"""
Dossier de risque actuel (`lifecycle`) — drapeaux prix, faits des dépôts officiels et
cadence du balayage EDGAR. Repris des tests du suivi (Epic 12 S1/S2), supprimé par
l'Epic 15 S2 : ils exercent désormais les fonctions gardées directement.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_lifecycle.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

import edgar
import lifecycle
import screener_backend as sb

FLOOR = sb.FILTERS["sub_dollar_price"]          # plancher de cotation
MIN_DAYS = sb.FILTERS["sub_dollar_min_days"]    # longueur de série qui fait mordre la règle
DAY = "2026-08-06"                              # jour calendaire simulé du balayage


@pytest.fixture(autouse=True)
def frozen_day(monkeypatch):
    monkeypatch.setattr(lifecycle, "_today", lambda: DAY)


def _df(closes, splits=None, start="2025-06-03"):
    idx = pd.bdate_range(start, periods=len(closes))
    data = {"Close": pd.Series(closes, index=idx)}
    if splits is not None:
        data["Stock Splits"] = pd.Series(splits, index=idx)
    return pd.DataFrame(data)


def _codes(markers):
    return [m["code"] for m in markers]


def _signals(ticker, **flags):
    """Retour de `survival_signals` : les trois drapeaux bas sauf ceux demandés."""
    out = {"ticker": ticker, "cik": 1,
           "dilution_flag": False, "late_filing_flag": False, "going_concern_flag": False,
           "dilution_date": None, "late_filing_date": None, "going_concern_date": None}
    out.update(flags)
    return out


@pytest.fixture
def edgar_log(monkeypatch):
    """Doublure des signaux de survie + journal des tickers interrogés."""
    calls = []

    def spy(ticker, *a, **k):
        calls.append(ticker)
        return _signals(ticker, going_concern_flag=True, going_concern_date="2026-07-15")

    monkeypatch.setattr(edgar, "survival_signals", spy)
    return calls


# ---------------------------------------------------------------------------
# Drapeaux prix
# ---------------------------------------------------------------------------

def test_sub_dollar_run_carries_its_length():
    n = MIN_DAYS + 10
    (m,) = lifecycle.current_risk_markers(_df([FLOOR - 0.5] * n))
    assert m == {"code": "sub_dollar", "level": "low", "days": n}


def test_short_run_under_the_floor_stays_silent():
    closes = [FLOOR + 4.0] * 10 + [FLOOR - 0.5] * (MIN_DAYS - 1)
    assert lifecycle.current_risk_markers(_df(closes)) == []


def test_reverse_split_is_flagged_high_and_dated():
    splits = [0.0] * 10
    splits[3] = 0.1                                  # regroupement 1 pour 10
    df = _df([FLOOR + 4.0] * 10, splits)
    (m,) = lifecycle.current_risk_markers(df)
    assert m == {"code": "reverse_split", "level": "high", "date": str(df.index[3].date())}


def test_no_split_column_is_neutral():
    assert lifecycle.reverse_split_marker(_df([FLOOR + 4.0] * 10)) == (None, None)


def test_no_prices_no_flags():
    assert lifecycle.current_risk_markers(None) == []


# ---------------------------------------------------------------------------
# Fusion — un seul dossier, ordonné par gravité décroissante
# ---------------------------------------------------------------------------

def test_filing_and_price_markers_merge_by_severity():
    n = MIN_DAYS + 10
    splits = [0.0] * n
    splits[2] = 0.05
    filings = _signals("AAA", going_concern_flag=True, going_concern_date="2026-07-15",
                       dilution_flag=True, dilution_date="2026-07-20",
                       late_filing_flag=True, late_filing_date="2026-07-25")
    markers = lifecycle.current_risk_markers(_df([FLOOR - 0.5] * n, splits), filings)
    assert _codes(markers) == ["going_concern", "reverse_split", "dilution",
                               "late_filing", "sub_dollar"]
    assert [m["level"] for m in markers] == ["high", "high", "medium", "low", "low"]


def test_a_marker_without_date_stays_listed():
    markers = lifecycle.risk_markers({"dilution_flag": True})
    assert markers == [{"code": "dilution", "level": "medium"}]


def test_a_line_without_prices_still_carries_its_filings():
    """Titre radié : plus de cotation, le dépôt reste la dernière information."""
    filings = _signals("GONE", going_concern_flag=True, going_concern_date="2026-07-15")
    assert _codes(lifecycle.current_risk_markers(None, filings)) == ["going_concern"]


# ---------------------------------------------------------------------------
# Cadence — au plus un balayage par jour calendaire et par titre
# ---------------------------------------------------------------------------

def test_second_sweep_same_day_asks_edgar_nothing(edgar_log):
    first = lifecycle.scan_filings(["AAA", "BBB"])
    second = lifecycle.scan_filings(["BBB", "AAA"])
    assert sorted(edgar_log) == ["AAA", "BBB"]          # tolérance zéro au second passage
    assert first == second


def test_next_day_triggers_the_sweep_again(edgar_log, monkeypatch):
    lifecycle.scan_filings(["AAA"])
    monkeypatch.setattr(lifecycle, "_today", lambda: "2026-08-07")   # lendemain
    lifecycle.scan_filings(["AAA"])
    assert edgar_log == ["AAA", "AAA"]


def test_a_new_ticker_is_swept_even_after_a_first_sweep(edgar_log):
    lifecycle.scan_filings(["AAA"])
    lifecycle.scan_filings(["AAA", "BBB"])
    assert edgar_log == ["AAA", "BBB"]


def test_memo_survives_a_module_reload(edgar_log, monkeypatch):
    """Redémarrage simulé : seul le fichier daté évite un second balayage."""
    lifecycle.scan_filings(["AAA"])
    memo = lifecycle._memo_path()
    assert memo.parent == Path(sb.DATA_DIR)
    assert json.loads(memo.read_text())["day"] == DAY

    importlib.reload(lifecycle)
    monkeypatch.setattr(lifecycle, "_today", lambda: DAY)
    out = lifecycle.scan_filings(["AAA"])
    assert edgar_log == ["AAA"]
    assert out["AAA"]["going_concern_flag"] is True


def test_an_unreadable_memo_just_sweeps_again(edgar_log):
    lifecycle.scan_filings(["AAA"])
    lifecycle._memo_path().write_text("{ pas du json")
    lifecycle.scan_filings(["AAA"])
    assert edgar_log == ["AAA", "AAA"]


def test_a_raising_or_silent_edgar_is_memorised_as_none(monkeypatch):
    calls = []

    def boom(ticker, *a, **k):
        calls.append(ticker)
        if ticker == "AAA":
            raise RuntimeError("EDGAR indisponible")
        return None

    monkeypatch.setattr(edgar, "survival_signals", boom)
    assert lifecycle.scan_filings(["AAA", "BBB"]) == {"AAA": None, "BBB": None}
    lifecycle.scan_filings(["AAA", "BBB"])
    assert calls == ["AAA", "BBB"]                      # l'absence de réponse est un résultat
