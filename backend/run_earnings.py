"""Evening job of the earnings alert (Epic 15 S4), run on the VPS by deploy/earnings-alert.timer.

1. ``detect`` on the last closed session; each Q5 release not yet in the journal
   gets one Telegram message and one line of ``data/earnings/alerts.jsonl``.
   Dedup = the journal itself, keyed on (CIK, period end).
2. Journal lines whose horizon (5 / 21 / 63 sessions after the first public
   close) has closed get their realized return and IWM's over the same period:
   open of the entry session to close of the horizon session, prices adjusted
   for splits and dividends (Yahoo chart API, no key).

``--bounds``: compute the quintile bounds of the current and previous quarter
ahead (deploy/earnings-bounds.timer, at night): a new quarter costs 7 to 9 min,
the evening alert then reads them from the cache.

Any error: one Telegram message, exit 1 (systemd marks the unit failed).

Usage (from backend/): python run_earnings.py [--session YYYY-MM-DD] [--bounds]
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

import pandas as pd
import requests

import earnings as er
import edgar
import lifecycle
from alerts import send_telegram

logger = logging.getLogger(__name__)

HORIZONS: Final[tuple[int, ...]] = (5, 21, 63)
BENCH: Final[str] = "IWM"
JOURNAL: Final[str] = "alerts.jsonl"
YAHOO_URL: Final[str] = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
FR_LABELS: Final[Path] = Path(__file__).resolve().parents[1] / "frontend" / "i18n" / "fr.json"


def journal_path() -> Path:
    return er.EARNINGS_DIR / JOURNAL


def read_journal() -> list[dict]:
    p = journal_path()
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def write_journal(lines: list[dict]) -> None:
    """Whole file rewritten through a temporary file: a crash never leaves half a journal."""
    p = journal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
    tmp.replace(p)


def prices(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Daily ``open`` and ``close`` from ``start`` to ``end``, adjusted (adjclose / close
    applied to the open), index = New York date. Empty when Yahoo has no bar."""
    span = {"period1": int(datetime(start.year, start.month, start.day, tzinfo=er.NY).timestamp()),
            "period2": int(datetime(end.year, end.month, end.day, 23, tzinfo=er.NY).timestamp()),
            "interval": "1d"}
    r = requests.get(YAHOO_URL.format(symbol=symbol.replace(".", "-")), params=span,
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    res = (r.json().get("chart", {}).get("result") or [{}])[0]
    if "timestamp" not in res:
        return pd.DataFrame(columns=["open", "close"])
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    day = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(er.NY).tz_localize(None).normalize()
    df = pd.DataFrame({"open": q["open"], "close": q["close"], "adj": adj}, index=day).dropna()
    return pd.DataFrame({"open": df["open"] * df["adj"] / df["close"], "close": df["adj"]})


def exit_session(first_close: date, h: int) -> date:
    """The ``h``-th session after ``first_close``."""
    return er.sessions(first_close, first_close + timedelta(days=2 * h + 15))[h].date()


def _ret(px: pd.DataFrame, entry: pd.Timestamp, out: pd.Timestamp) -> float | None:
    """Return in % from the open of ``entry`` to the close of ``out``; None if a bar is missing."""
    if entry not in px.index or out not in px.index:
        return None
    return round(100 * (px.at[out, "close"] / px.at[entry, "open"] - 1), 4)


def update_returns(lines: list[dict], session: date) -> int:
    """Fill ``ret_<h>`` / ``iwm_<h>`` of the lines whose horizon closed by ``session``.
    A missing price leaves the cell empty, retried at the next run. Returns cells filled."""
    filled = 0
    bench: dict[tuple, pd.DataFrame] = {}
    for line in lines:
        fc = date.fromisoformat(line["session"])
        due = [h for h in HORIZONS if line.get(f"ret_{h}") is None and exit_session(fc, h) <= session]
        if not due:
            continue
        entry = pd.Timestamp(line["entry"])
        end = exit_session(fc, max(due))
        try:
            px = prices(line["ticker"], entry.date(), end)
            key = (entry.date(), end)
            if key not in bench:
                bench[key] = prices(BENCH, entry.date(), end)
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.warning("prices %s: %s", line["ticker"], type(e).__name__)
            continue
        for h in due:
            out = pd.Timestamp(exit_session(fc, h))
            r, b = _ret(px, entry, out), _ret(bench[key], entry, out)
            if r is not None and b is not None:
                line[f"ret_{h}"], line[f"iwm_{h}"] = r, b
                filled += 1
    return filled


def _labels() -> dict:
    try:
        return json.loads(FR_LABELS.read_text())
    except (OSError, ValueError):
        return {}


def message(ev: pd.Series, risk: list[dict]) -> str:
    """Telegram text (HTML) of one Q5 release."""
    labels = _labels()
    net = er.CFG["net"]
    lines = [
        f"<b>{html.escape(ev['ticker'])}</b> — résultats publiés, surprise dans le quintile supérieur",
        f"Communiqué : {ev['release_t']:%Y-%m-%d %H:%M} New York · rapport {html.escape(ev['form'], quote=False)} : {ev['eps_t']:%Y-%m-%d %H:%M}",
        f"Surprise saisonnière (SUE) {ev['sue']:.2f} · quintile {int(ev['sue_q'])} · BPA {ev['eps']:g} $ "
        f"(trimestre clos le {ev['period_end']:%Y-%m-%d})",
        f"Entrée : ouverture du {ev['entry']:%Y-%m-%d}",
    ]
    if net:
        lines.append("Rendement net moyen mesuré sur l'historique : " + " · ".join(
            f"{v:+.2f} % à {h} séances" for h, v in sorted(net.items())))
    lines.append("Drapeaux de risque (information, aucun filtre) : " + (", ".join(
        html.escape(labels.get(f"risk.{m['code']}", m["code"]) + (f" ({m['date']})" if m.get("date") else ""), quote=False)
        for m in risk) or "aucun"))
    lines.append(f"https://finviz.com/quote.ashx?t={html.escape(ev['ticker'])}")
    return "\n".join(lines)


def run(session: date) -> dict:
    """Alerts of ``session`` then due returns; journal written before each send and at the end. Returns counts."""
    lines = read_journal()
    seen = {(x["cik"], x["period_end"]) for x in lines}
    ev = er.detect(session)
    q5 = ev[ev["sue_q"] == 5]
    sent = 0
    for _, e in q5.iterrows():
        key = (int(e["cik"]), f"{e['period_end']:%Y-%m-%d}")
        if key in seen:
            continue
        risk = lifecycle.current_risk_markers(None, edgar.survival_signals(e["ticker"]))
        seen.add(key)
        line = {
            "cik": key[0], "ticker": e["ticker"], "period_end": key[1], "form": e["form"],
            "release_t": e["release_t"].isoformat(), "eps_t": e["eps_t"].isoformat(),
            "session": f"{e['first_close']:%Y-%m-%d}", "entry": f"{e['entry']:%Y-%m-%d}",
            "eps": float(e["eps"]), "sue": float(e["sue"]), "sue_q": int(e["sue_q"]),
            "risk": risk, "telegram": False, "alerted_at": datetime.now(er.NY).isoformat(timespec="seconds"),
            **{f"{k}_{h}": None for h in HORIZONS for k in ("ret", "iwm")},
        }
        lines.append(line)
        write_journal(lines)  # journal before send: a crash after the send never re-alerts
        ok = send_telegram(message(e, risk))
        if not ok:
            logger.warning("Telegram not sent for %s (secrets absent or API error)", e["ticker"])
        line["telegram"] = bool(ok)
        sent += ok
    filled = update_returns(lines, session)
    write_journal(lines)
    if q5.empty and er.CFG["notify_empty"]:
        send_telegram(f"Séance du {session} : aucune publication de résultats dans le quintile supérieur.")
    return {"releases": len(ev), "q5": len(q5), "sent": sent, "journal": len(lines), "filled": filled}


def precompute_bounds(today: date) -> None:
    q = pd.Period(today, "Q")
    for k in (q - 1, q):
        er.quarter_bounds(k)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", type=date.fromisoformat)
    ap.add_argument("--bounds", action="store_true")
    a = ap.parse_args(argv)
    t0 = datetime.now()
    try:
        if a.bounds:
            precompute_bounds(datetime.now(er.NY).date())
            print(f"bornes à jour · durée {(datetime.now() - t0).seconds} s")
        else:
            session = a.session or er.last_session()
            n = run(session)
            print(f"séance {session} · {n['releases']} publication(s) · Q5 {n['q5']} · "
                  f"alertes envoyées {n['sent']} · journal {n['journal']} ligne(s) · "
                  f"rendements ajoutés {n['filled']} · durée {(datetime.now() - t0).seconds} s")
        return 0
    except Exception as e:  # noqa: BLE001 — any failure must reach the owner
        logger.exception("earnings job failed")
        send_telegram(f"⚠️ Job d'alerte résultats en échec ({os.uname().nodename}) : "
                      f"{html.escape(type(e).__name__)} : {html.escape(str(e)[:300])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
