"""Live earnings detection (Epic 15 S3) on synthetic EDGAR data, no network.

Values are test values (bounds, tiers, EPS), never the measured ones.
"""
from __future__ import annotations

import json
import statistics
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

import earnings as er
import edgar
from screener_backend import LocalConfigError

CIK = 222
Q_ENDS = pd.date_range("2023-03-31", "2026-09-30", freq="QE")       # 15 quarters
EPS = [0.10, 0.12, 0.08, 0.15, 0.11, 0.16, 0.05, 0.20, 0.14, 0.13, 0.09, 0.25, 0.18, 0.10, 0.30]
TEN_Q = "0000222-26-000010"


def _eps_frame(values: list[float]) -> pd.DataFrame:
    ends = Q_ENDS[: len(values)]
    return pd.DataFrame({"cik": CIK, "period_end": ends, "eps": values, "filed": ends + pd.Timedelta(days=30)})


def _hand_sue(values: list[float], k: int) -> float:
    diffs = [values[i] - values[i - 4] for i in range(4, len(values))]
    j = k - 4                                    # index of quarter k's diff
    prev = diffs[max(0, j - 8):j]
    return diffs[j] / statistics.stdev(prev)


# ---------------------------------------------------------------------------
# SUE (Bernard & Thomas 1990), same formula as ta-patterns
# ---------------------------------------------------------------------------

def test_sue_equals_hand_computed_value():
    out = er.seasonal_sue(_eps_frame(EPS))
    last = len(EPS) - 1                          # 10 previous diffs: the last 8 are used
    assert out["n_prev"].iloc[last] == 8
    assert abs(out["sue"].iloc[last] - _hand_sue(EPS, last)) < 1e-9
    assert abs(out["sue"].iloc[8] - _hand_sue(EPS, 8)) < 1e-9    # 4 previous diffs: the minimum


def test_sue_absent_with_three_seasonal_differences():
    out = er.seasonal_sue(_eps_frame(EPS[:8]))   # diffs from quarter 5: 3 before quarter 8
    assert out["n_prev"].iloc[7] == 3
    assert np.isnan(out["sue"].iloc[7])


def test_quarterly_eps_derives_q4_from_the_year():
    facts = er.facts_frame([
        (CIK, "2025-01-01", "2025-03-31", 0.10, "2025-05-01", "10-Q", "a1"),
        (CIK, "2025-04-01", "2025-06-30", 0.20, "2025-08-01", "10-Q", "a2"),
        (CIK, "2025-07-01", "2025-09-30", 0.30, "2025-11-01", "10-Q", "a3"),
        (CIK, "2025-01-01", "2025-12-31", 1.00, "2026-02-20", "10-K", "a4"),
    ])
    q = er.quarterly_eps(facts)
    q4 = q[q["fp"] == "Q4"].iloc[0]
    assert q4["derived_q4"] and abs(q4["eps"] - 0.40) < 1e-12 and q4["accn"] == "a4"


# ---------------------------------------------------------------------------
# Dates: 16:00 New York rule, entry at the next open
# ---------------------------------------------------------------------------

def test_8k_accepted_at_1630_enters_at_the_open_after_the_next_session():
    d = er.entry_dates(pd.Series([pd.Timestamp("2026-10-23 16:30")]))   # Friday
    assert d["first_close"].iloc[0] == pd.Timestamp("2026-10-26")       # Monday close
    assert d["entry"].iloc[0] == pd.Timestamp("2026-10-27")             # Tuesday open


def test_filing_before_1600_enters_at_the_next_open():
    d = er.entry_dates(pd.Series([pd.Timestamp("2026-10-26 10:00")]))
    assert d["first_close"].iloc[0] == pd.Timestamp("2026-10-26")
    assert d["entry"].iloc[0] == pd.Timestamp("2026-10-27")


def test_nyse_holidays_are_not_sessions():
    s = er.sessions(date(2026, 11, 25), date(2026, 11, 30))
    assert pd.Timestamp("2026-11-26") not in s                          # Thanksgiving
    assert list(s.strftime("%m-%d")) == ["11-25", "11-27", "11-30"]


def test_acceptance_time_utc_to_new_york():
    raw = ["2026-10-26T20:30:00.000Z", "2026-10-20T14:00:00.000Z"]
    shift = er.file_shift(raw, ["2026-10-26", "2026-10-20"])
    assert er.new_york_times(raw, shift)[0].strftime("%H:%M") == "16:30"


# ---------------------------------------------------------------------------
# One event per (CIK, quarter end)
# ---------------------------------------------------------------------------

def test_second_8k_202_on_the_same_quarter_is_not_an_event():
    eps = er.seasonal_sue(_eps_frame(EPS)).assign(accn="x", form="10-Q")
    rel = pd.DataFrame({
        "cik": [CIK, CIK],
        "t": pd.to_datetime(["2026-10-20 08:00", "2026-10-22 08:00"]),
        "accession": ["8k-first", "8k-repeat"],
    })
    ev = er.link_events(rel, eps.assign(filed=pd.Timestamp("2026-10-26")))
    assert list(ev["accession"]) == ["8k-first"]


# ---------------------------------------------------------------------------
# Live detection on synthetic EDGAR answers
# ---------------------------------------------------------------------------

def _facts_doc(cik: int = CIK, last_filed: str = "2026-10-26", last_accn: str = TEN_Q) -> dict:
    rows = []
    for i, (end, v) in enumerate(zip(Q_ENDS, EPS)):
        start = (end - pd.offsets.QuarterBegin(startingMonth=1)).normalize()
        last = i == len(EPS) - 1
        rows.append({"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "val": v,
                     "filed": last_filed if last else (end + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                     "form": "10-Q", "accn": last_accn if last else f"old-{i}"})
    for y in (2023, 2024, 2025):
        rows.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": 1.0, "filed": f"{y + 1}-02-20",
                     "form": "10-K", "accn": f"k-{y}"})
    return {"cik": cik, "facts": {"us-gaap": {"EarningsPerShareBasic": {"units": {"USD/shares": rows}}}}}


SUBMISSIONS = {"filings": {"recent": {
    "accessionNumber": [TEN_Q, "8k-repeat", "8k-first", "8k-old"],
    "filingDate": ["2026-10-26", "2026-10-26", "2026-10-26", "2026-07-20"],
    "acceptanceDateTime": ["2026-10-26T20:31:00.000Z", "2026-10-26T20:45:00.000Z",
                           "2026-10-26T20:30:00.000Z", "2026-07-20T12:00:00.000Z"],
    "form": ["10-Q", "8-K", "8-K", "8-K"],
    "items": ["", "2.02,9.01", "2.02,9.01", "2.02"],
}}}


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setitem(er.CFG, "tiers", ["small"])
    monkeypatch.setattr(er, "EARNINGS_DIR", tmp_path / "earnings")
    monkeypatch.setattr(er.finviz, "snapshot", lambda: {"TEST": {"marketCap": 500e6}, "BIG": {"marketCap": 50e9}})
    monkeypatch.setattr(edgar, "_load_cik_map", lambda: {"TEST": CIK, "BIG": 333})
    monkeypatch.setattr(edgar, "_USER_AGENT", "test contact@example.com")
    fil = pd.DataFrame({"cik": [CIK, 333], "accession": [TEN_Q, "big-10q"], "form": ["10-Q", "10-Q"],
                        "filed": pd.to_datetime(["2026-10-26", "2026-10-26"]), "items": ["", ""]})
    monkeypatch.setattr(er, "filings", lambda forms, a, b: fil)
    texts = {"submissions": json.dumps(SUBMISSIONS), "facts": json.dumps(_facts_doc())}
    monkeypatch.setattr(edgar, "_cached_text", lambda url, name, ttl: texts[name.split("_")[0]])
    monkeypatch.setattr(er, "quarter_bounds", lambda q, facts_zip=None: np.array([-1.0, -0.3, 0.3, 1.0]))


def test_detect_one_event_per_quarter_with_sue_quintile_and_entry(live):
    ev = er.detect(date(2026, 10, 27))
    assert len(ev) == 1                                         # BIG out of the tiers, repeat 8-K dropped
    r = ev.iloc[0]
    assert r["ticker"] == "TEST" and r["period_end"] == pd.Timestamp("2026-09-30")
    assert abs(r["sue"] - _hand_sue(EPS, len(EPS) - 1)) < 1e-9
    assert r["sue_q"] == 1 + int(np.searchsorted([-1.0, -0.3, 0.3, 1.0], r["sue"], side="right"))
    assert r["release_t"] == pd.Timestamp("2026-10-26 16:30")   # the first 8-K
    assert r["first_close"] == pd.Timestamp("2026-10-27") and r["entry"] == pd.Timestamp("2026-10-28")


def test_detect_other_session_is_empty(live):
    assert er.detect(date(2026, 10, 26)).empty                  # 10-Q at 16:31: next close


def test_no_tier_no_network(monkeypatch):
    monkeypatch.setitem(er.CFG, "tiers", [])
    monkeypatch.setattr(er.finviz, "snapshot", lambda: pytest.fail("network touched"))
    assert er.detect(date(2026, 10, 27)).empty


# ---------------------------------------------------------------------------
# Quintile bounds of the previous calendar quarter, cached
# ---------------------------------------------------------------------------

def test_quarter_bounds_from_previous_quarter_releases(monkeypatch, tmp_path):
    monkeypatch.setattr(er, "EARNINGS_DIR", tmp_path / "earnings")
    z = tmp_path / "companyfacts.zip"
    sues = []
    with zipfile.ZipFile(z, "w") as f:
        for i, cik in enumerate(range(500, 510)):
            vals = [v + 0.01 * i * (k % 3) for k, v in enumerate(EPS[:14])]
            doc = _facts_doc(cik, last_filed="2026-08-10", last_accn=f"q-{cik}")
            rows = doc["facts"]["us-gaap"]["EarningsPerShareBasic"]["units"]["USD/shares"]
            for r, v in zip(rows, vals):
                r["val"] = v
            rows[13]["filed"] = "2026-08-10"
            f.writestr(f"CIK{cik:010d}.json", json.dumps(doc))
            sues.append(_hand_sue(vals, 13))
    rel = pd.DataFrame({"cik": range(500, 510), "accession": [f"r-{c}" for c in range(500, 510)],
                        "form": "8-K", "filed": pd.Timestamp("2026-08-05"), "items": "2.02,9.01"})
    calls = []
    monkeypatch.setattr(er, "filings", lambda forms, a, b: calls.append((forms, a, b)) or rel)
    b = er.quarter_bounds(pd.Period("2026Q4", "Q"), facts_zip=z)
    assert calls == [("8-K", date(2026, 7, 1), date(2026, 9, 30))]
    assert np.allclose(b, np.quantile(sues, er.QUANTILES), rtol=1e-12)
    assert np.array_equal(er.quarter_bounds(pd.Period("2026Q4", "Q"), facts_zip=z), b)
    assert len(calls) == 1                                      # second call served by the cache


def test_quintile_zero_without_sue_or_bounds():
    assert list(er.quintile(pd.Series([np.nan, 2.0]), np.array([-1.0, 0.0, 0.5, 1.0]))) == [0, 5]
    assert list(er.quintile(pd.Series([2.0]), None)) == [0]


# ---------------------------------------------------------------------------
# EDGAR full-text search: pages, co-registrants, transient errors
# ---------------------------------------------------------------------------

def test_filings_pages_and_retries(monkeypatch):
    def hit(adsh, ciks):
        return {"_source": {"adsh": adsh, "ciks": ciks, "form": "8-K", "file_date": "2026-10-26", "items": ["2.02"]}}
    pages = [
        {"errorType": "ConnectionError"},                                     # transient, retried
        {"hits": {"total": {"value": 3}, "hits": [hit("a", ["0000000001", "0000000002"]), hit("b", ["0000000003"])]}},
        {"hits": {"total": {"value": 3}, "hits": [hit("c", ["0000000004"])]}},
    ]

    class R:
        def __init__(self, doc):
            self.text = json.dumps(doc)

    seen = []
    monkeypatch.setattr(edgar, "_USER_AGENT", "test contact@example.com")
    monkeypatch.setattr(edgar, "_get", lambda url: seen.append(url) or R(pages[len(seen) - 1]))
    monkeypatch.setattr(er.time, "sleep", lambda s: None)
    df = er.filings("8-K", date(2026, 10, 26), date(2026, 10, 26))
    assert sorted(zip(df["cik"], df["accession"])) == [(1, "a"), (2, "a"), (3, "b"), (4, "c")]
    assert "from=2" in seen[-1]


# ---------------------------------------------------------------------------
# Config: earnings.tiers (neutral default, nano refused)
# ---------------------------------------------------------------------------

def test_config_tiers_read_and_checked(monkeypatch, tmp_path):
    monkeypatch.setitem(er.CFG, "tiers", [])
    f = tmp_path / "local.yml"
    f.write_text("earnings:\n  tiers: [small]\n")
    er.load_config(f)
    assert er.CFG["tiers"] == ["small"]
    for bad in ("earnings:\n  tiers: [nano]\n", "earnings:\n  tiers: [tiny]\n", "earnings:\n  tier: [small]\n"):
        f.write_text(bad)
        with pytest.raises(LocalConfigError):
            er.load_config(f)


def test_backend_accepts_earnings_section(tmp_path):
    import screener_backend as sb
    f = tmp_path / "local.yml"
    f.write_text("earnings:\n  tiers: [small]\n")
    sb.load_local_config(path=f, filters=dict(sb.FILTERS))


def test_tier_bounds_follow_finviz():
    assert er.tier_of(49.9e6) == "nano" and er.tier_of(50e6) == "micro"
    assert er.tier_of(300e6) == "small" and er.tier_of(2e9) == "mid" and er.tier_of(None) is None
