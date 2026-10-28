"""Earnings alert job (Epic 15 S4): dedup, Q5 only, due returns. No network.

Values are test values (SUE, prices, net returns), never the measured ones.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

import earnings as er
import run_earnings as rj

SESSION = date(2026, 10, 27)


def _event(sue_q: int) -> pd.DataFrame:
    return pd.DataFrame([{
        "ticker": "TEST", "cik": 222, "form": "10-Q", "period_end": pd.Timestamp("2026-09-30"),
        "eps": 0.3, "sue": 2.5, "sue_q": sue_q, "release_t": pd.Timestamp("2026-10-26 16:30"),
        "eps_t": pd.Timestamp("2026-10-27 08:00"), "first_close": pd.Timestamp("2026-10-27"),
        "entry": pd.Timestamp("2026-10-28"),
    }])


@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setattr(er, "EARNINGS_DIR", tmp_path / "earnings")
    monkeypatch.setitem(er.CFG, "net", {5: 0.11, 21: 0.22, 63: 0.33})
    monkeypatch.setattr(rj.edgar, "survival_signals", lambda t: {"dilution_flag": True, "dilution_date": "2026-09-01"})
    sent: list[str] = []
    monkeypatch.setattr(rj, "send_telegram", lambda text: sent.append(text) or True)
    monkeypatch.setattr(rj, "prices", lambda *a: pytest.fail("no line due"))
    return sent


def test_two_runs_on_the_same_fixture_send_one_alert(job, monkeypatch):
    monkeypatch.setattr(er, "detect", lambda s: _event(5))
    rj.run(SESSION)
    rj.run(SESSION)
    assert len(job) == 1
    assert "TEST" in job[0] and "quintile 5" in job[0] and "2026-10-28" in job[0]
    assert "+0.22 % à 21 séances" in job[0] and "Émission d'actions nouvelles" in job[0]
    lines = rj.read_journal()
    assert len(lines) == 1 and lines[0]["session"] == "2026-10-27" and lines[0]["ret_5"] is None


def test_q4_release_sends_nothing(job, monkeypatch):
    monkeypatch.setattr(er, "detect", lambda s: _event(4))
    assert rj.run(SESSION)["q5"] == 0
    assert job == [] and rj.read_journal() == []


def test_line_six_sessions_old_gets_its_5_session_return_only(job, monkeypatch):
    days = er.sessions(date(2026, 10, 19), date(2026, 11, 30))     # 19 Oct .. 30 Nov
    fc, entry, run_day = days[0], days[1], days[6]
    rj.write_journal([{"cik": 222, "ticker": "TEST", "period_end": "2026-09-30", "session": f"{fc:%Y-%m-%d}",
                       "entry": f"{entry:%Y-%m-%d}", **{f"{k}_{h}": None for h in rj.HORIZONS for k in ("ret", "iwm")}}])
    px = {"TEST": pd.DataFrame({"open": [9.0 + i for i in range(len(days))],
                                "close": [10.0 + i for i in range(len(days))]}, index=days),
          "IWM": pd.DataFrame({"open": 200.0, "close": 202.0}, index=days)}
    monkeypatch.setattr(rj, "prices", lambda sym, a, b: px[sym])
    monkeypatch.setattr(er, "detect", lambda s: _event(4).iloc[:0])
    assert rj.run(run_day.date())["filled"] == 1
    line = rj.read_journal()[0]
    assert line["ret_5"] == pytest.approx(100 * (15.0 / 10.0 - 1))   # open of entry (fc+1) -> close of fc+5
    assert line["iwm_5"] == pytest.approx(1.0)
    assert line["ret_21"] is None and line["ret_63"] is None and line["iwm_21"] is None


def test_last_session_is_today_after_the_close():
    ny = er.NY
    assert er.last_session(datetime(2026, 10, 28, 16, 15, tzinfo=ny)) == date(2026, 10, 28)   # Wednesday evening
    assert er.last_session(datetime(2026, 10, 28, 15, 0, tzinfo=ny)) == date(2026, 10, 27)
    assert er.last_session(datetime(2026, 10, 31, 12, 0, tzinfo=ny)) == date(2026, 10, 30)    # Saturday -> Friday


def test_job_failure_sends_a_telegram_error(job, monkeypatch):
    def boom(s):
        raise er.EarningsError("EDGAR unreadable")
    monkeypatch.setattr(er, "detect", boom)
    assert rj.main(["--session", "2026-10-27"]) == 1
    assert len(job) == 1 and "EarningsError" in job[0]
