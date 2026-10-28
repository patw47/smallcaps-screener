"""Live earnings releases with their seasonal surprise (SUE), variant B of Epic 15.

For one session S: the 10-Q / 10-K whose first public close is S (16:00 New York
rule, ``study.earnings.first_close``) and that first carry the EPS of a quarter
released by an 8-K item 2.02 at most ``LINK_DAYS`` before (``link_eps``); one
event per (CIK, quarter end), the earliest 8-K (ta-patterns PR #70). Entry = open
of the session after that first close.

SUE (Bernard & Thomas 1990, Journal of Accounting and Economics 13(4)) = (EPS_q -
EPS_q-4) / standard deviation of the 8 previous seasonal differences, 4 at
least. Tags, Q4 derivation and formula are those of ta-patterns
(``tools/lake/edgar.quarterly_eps``, ``tools/rules/events.seasonal_sue``),
ported here because the job runs without the lake. Quintile against the bounds
of the previous calendar quarter's releases (``quarter_bounds``).

Universe: tiers of ``earnings.tiers`` in config/local.yml (default empty: nothing
enters), market cap read in the Finviz export.

Usage (from backend/): python earnings.py [--session YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yaml
from pandas.tseries.holiday import (
    AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday, sunday_to_monday,
)

import edgar
import finviz
from screener_backend import CONFIG_FILE, DATA_DIR, LocalConfigError
from study.earnings import LINK_DAYS, YEAR_TOLERANCE, first_close, link_eps

logger = logging.getLogger(__name__)

# Défaut NEUTRE : aucun tier, donc aucune publication n'entre. La liste réelle (verdict
# du Sprint 1) vit dans config/local.yml, section `earnings:`.
CFG: dict = {"tiers": []}

# Finviz screener bounds, millions USD, lower bound inclusive (ta-patterns tools/lake/universe.py).
TIER_BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "nano": (0, 50), "micro": (50, 300), "small": (300, 2_000),
    "mid": (2_000, 10_000), "large": (10_000, 200_000), "mega": (200_000, float("inf")),
}
# ta-patterns tools/lake/edgar.py and tools/rules/events.py
QUARTER_DAYS: Final[tuple[int, int]] = (80, 100)
YEAR_DAYS: Final[tuple[int, int]] = (350, 380)
MIN_DIFFS: Final[int] = 4
MAX_DIFFS: Final[int] = 8
MIN_SD: Final[float] = 1e-6  # USD per share; equal diffs give std ~1e-17
QUANTILES: Final[list[float]] = [0.2, 0.4, 0.6, 0.8]
ITEM_202: Final[str] = r"(?:^|,)\s*2\.02\s*(?:,|$)"  # ta-patterns tools/lake/edgar.releases
NY: Final[ZoneInfo] = ZoneInfo("America/New_York")
EPS_COLUMNS: Final[list[str]] = ["cik", "period_end", "fp", "eps", "filed", "form", "accn", "derived_q4"]

EFTS_URL: Final[str] = "https://efts.sec.gov/LATEST/search-index"
FACTS_ZIP_URL: Final[str] = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
# One query per day: the full-text search serves 10 000 hits per query at most, and some
# deep pages of a week window failed on every try (2024-10-01..07, from=900) where the
# daily windows of the same week answered.
WINDOW_DAYS: Final[int] = 1
TRIES: Final[int] = 6  # 10 + 20 + ... + 50 s: full-text search outages seen up to ~1 min
FRESH_S: Final[int] = 3_600      # submissions / companyfacts of the day: refetched after 1 h
BOUNDS_REFRESH_DAYS: Final[int] = 7
EARNINGS_DIR: Final[Path] = Path(DATA_DIR) / "earnings"


class EarningsError(RuntimeError):
    """EDGAR or Finviz unreadable: no list rather than a partial one."""


def load_config(path: Path = CONFIG_FILE) -> None:
    """Read the ``earnings:`` section; an unknown key or tier, or nano, stops the start."""
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except OSError:
        return
    section = (raw.get("earnings") if isinstance(raw, dict) else None) or {}
    unknown = set(section) - set(CFG)
    if unknown:
        raise LocalConfigError(f"config locale : clé inconnue 'earnings.{sorted(unknown)[0]}'")
    tiers = list(section.get("tiers") or [])
    bad = [t for t in tiers if t not in TIER_BOUNDS or t == "nano"]
    if bad:
        raise LocalConfigError(f"config locale : tier refusé dans earnings.tiers : {bad[0]}")
    CFG["tiers"] = tiers


load_config()


# ---------------------------------------------------------------------------
# EPS and SUE (ports of ta-patterns, pure)
# ---------------------------------------------------------------------------

def eps_rows(doc: dict) -> list[tuple]:
    """Duration facts of ``us-gaap:EarningsPerShareBasic`` in USD per share of one companyfacts JSON."""
    units = doc.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareBasic", {}).get("units", {})
    cik = int(doc.get("cik", 0))
    return [
        (cik, f["start"], f["end"], f["val"], f["filed"], f["form"], f["accn"])
        for f in units.get("USD/shares", []) if "start" in f
    ]


def facts_frame(rows: list[tuple]) -> pd.DataFrame:
    """``eps_rows`` output as the frame ``quarterly_eps`` reads (``read_eps`` of ta-patterns)."""
    df = pd.DataFrame(rows, columns=["cik", "start", "end", "val", "filed", "form", "accn"])
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df.astype({"cik": "int64"})


def quarterly_eps(facts: pd.DataFrame) -> pd.DataFrame:
    """Quarterly basic EPS per (CIK, period end), first filed value, Q4 derived.

    Port of ta-patterns ``quarterly_eps`` plus ``accn``, the filing that first
    carried the value (the annual one for a derived Q4): the live trigger.
    """
    if facts.empty:
        return pd.DataFrame(columns=EPS_COLUMNS)
    f = facts.assign(days=(facts["end"] - facts["start"]).dt.days)
    f = f.sort_values(["cik", "end", "filed", "accn"], kind="stable")
    q = f[f["days"].between(*QUARTER_DAYS)].drop_duplicates(["cik", "end"])
    a = f[f["days"].between(*YEAR_DAYS)].drop_duplicates(["cik", "end"])
    if q.empty:
        return pd.DataFrame(columns=EPS_COLUMNS)
    ends = a[["cik", "end"]].rename(columns={"end": "fy"}).sort_values("fy")
    q = q.sort_values("end")
    fwd = pd.merge_asof(q, ends, left_on="end", right_on="fy", by="cik", direction="forward")["fy"].to_numpy()
    back = pd.merge_asof(
        q, ends, left_on="end", right_on="fy", by="cik", direction="backward", allow_exact_matches=False
    )["fy"].to_numpy()
    n_fwd = 4 - np.round((fwd - q["end"].to_numpy()) / np.timedelta64(1, "D") / 91.3)
    n_back = np.round((q["end"].to_numpy() - back) / np.timedelta64(1, "D") / 91.3)
    use_fwd = (n_fwd >= 1) & (n_fwd <= 4)
    n = np.where(use_fwd, n_fwd, np.where((n_back >= 1) & (n_back <= 4), n_back, np.nan))
    q = q.assign(n=n, fy=np.where(use_fwd, fwd, np.datetime64("NaT", "ns")))
    q = q.dropna(subset=["n"])
    q["fp"] = "Q" + q["n"].astype(int).astype(str)
    has = q.dropna(subset=["fy"]).pivot_table(index=["cik", "fy"], columns="fp", values="val", aggfunc="first")
    has = has.reindex(columns=["Q1", "Q2", "Q3", "Q4"])
    ok = has[["Q1", "Q2", "Q3"]].notna().all(axis=1) & has["Q4"].isna()
    yr = a.set_index(["cik", "end"])[["val", "filed", "form", "accn"]]
    yr.index.names = ["cik", "fy"]
    d = has[ok].join(yr, how="inner")
    q4 = pd.DataFrame({
        "cik": d.index.get_level_values("cik"),
        "period_end": d.index.get_level_values("fy"),
        "fp": "Q4",
        "eps": d["val"].to_numpy() - d["Q1"].to_numpy() - d["Q2"].to_numpy() - d["Q3"].to_numpy(),
        "filed": d["filed"].to_numpy(),
        "form": d["form"].to_numpy(),
        "accn": d["accn"].to_numpy(),
        "derived_q4": True,
    })
    out = pd.DataFrame({
        "cik": q["cik"], "period_end": q["end"], "fp": q["fp"], "eps": q["val"],
        "filed": q["filed"], "form": q["form"], "accn": q["accn"], "derived_q4": False,
    })
    out = pd.concat([out, q4], ignore_index=True) if len(q4) else out
    out["cik"] = out["cik"].astype("int64")
    return out.sort_values(["cik", "period_end"], ignore_index=True)[EPS_COLUMNS]


def seasonal_sue(eps: pd.DataFrame) -> pd.DataFrame:
    """``eps`` plus ``diff``, ``n_prev``, ``sue`` (port of ta-patterns ``seasonal_sue``).

    ``diff`` = eps - eps of the quarter ended 365 +- 15 days before; ``sue`` =
    diff / standard deviation (ddof 1) of the previous non-NaN diffs (at most 8),
    NaN under 4 or under MIN_SD.
    """
    e = eps.sort_values(["cik", "period_end"], kind="stable").reset_index(drop=True)
    if e.empty:
        return e.assign(diff=pd.Series(dtype=float), n_prev=pd.Series(dtype=int), sue=pd.Series(dtype=float))
    back = e[["cik", "period_end", "eps"]].rename(columns={"period_end": "pe_4", "eps": "eps_4"})
    m = (
        pd.merge_asof(
            e.reset_index().assign(target=e["period_end"] - pd.Timedelta(days=365)).sort_values("target"),
            back.sort_values("pe_4"),
            left_on="target", right_on="pe_4", by="cik", direction="nearest", tolerance=YEAR_TOLERANCE,
        )
        .set_index("index")
        .sort_index()
    )
    e["diff"] = m["eps"] - m["eps_4"]
    h = e.dropna(subset=["diff"])
    roll = h.groupby("cik")["diff"].shift(1).groupby(h["cik"]).rolling(MAX_DIFFS, min_periods=1)
    e["n_prev"] = roll.count().droplevel(0).reindex(e.index).fillna(0).astype(int)
    sd = roll.std().droplevel(0).reindex(e.index)
    e["sue"] = (e["diff"] / sd).where((e["n_prev"] >= MIN_DIFFS) & (sd >= MIN_SD))
    return e


def link_events(releases: pd.DataFrame, eps: pd.DataFrame) -> pd.DataFrame:
    """Releases (``cik``, ``t``, ``accession``) linked to their quarter, one per (CIK, quarter end).

    A later 8-K 2.02 on a quarter already linked repeats a surprise public since
    the first one: dropped (ta-patterns ``repeat_quarter``, PR #70).
    """
    e, _ = link_eps(releases, eps)
    e = e.sort_values(["t", "accession"], kind="stable")
    return e.drop_duplicates(["cik", "period_end"]).reset_index(drop=True)


def quintile(sue: pd.Series, bounds: np.ndarray | None) -> np.ndarray:
    """Quintile 1..5 of ``sue`` against ``bounds`` (``QUANTILES``), 0 when NaN or no bounds."""
    s = sue.to_numpy("float64")
    if bounds is None:
        return np.zeros(len(s), np.int8)
    return np.where(np.isnan(s), 0, 1 + np.searchsorted(bounds, s, side="right")).astype(np.int8)


def tier_of(mcap_usd: float | None) -> str | None:
    """Finviz tier of a market cap in USD."""
    if mcap_usd is None:
        return None
    m = mcap_usd / 1e6
    return next((t for t, (lo, hi) in TIER_BOUNDS.items() if lo <= m < hi), None)


# ---------------------------------------------------------------------------
# Calendar and dates
# ---------------------------------------------------------------------------

class _NYSE(AbstractHolidayCalendar):
    # ponytail: fixed NYSE holidays only; an unscheduled closure (e.g. a national day
    # of mourning) is a session here: add it to rules if a run falls on one.
    rules = [
        Holiday("New Year", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def sessions(start: date, end: date) -> pd.DatetimeIndex:
    """NYSE sessions from ``start`` to ``end``."""
    return pd.bdate_range(start, end, freq="C", holidays=_NYSE().holidays(start, end)).astype("datetime64[ns]")


def entry_dates(t: pd.Series) -> pd.DataFrame:
    """``first_close`` after ``t`` (New York) and ``entry``: the open of the next session."""
    t = t.astype("datetime64[ns]")
    if t.empty:
        return pd.DataFrame({"first_close": t, "entry": t})
    cal = sessions(t.min().date() - timedelta(days=7), t.max().date() + timedelta(days=30))
    fc = first_close(pd.DataFrame({"symbol": "", "date": cal}), pd.Series("", index=t.index), t)
    nxt = np.searchsorted(cal.to_numpy(), fc.to_numpy(), side="right")
    return pd.DataFrame({"first_close": fc, "entry": cal.to_numpy()[np.minimum(nxt, len(cal) - 1)]}, index=t.index)


def new_york_times(raw: list[str], shift: int) -> list[datetime | None]:
    """``acceptanceDateTime`` strings -> naive New York times (port of ta-patterns)."""
    out: list[datetime | None] = []
    for t in raw:
        try:
            u = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            out.append(None)
            continue
        offset = -u.astimezone(NY).utcoffset()
        out.append(u.replace(tzinfo=None) - shift * offset)
    return out


def file_shift(raw: list[str], filing_dates: list[str]) -> int:
    """New York offsets one submissions file adds (0, 1 or 2), port of ta-patterns.

    EDGAR labels ``acceptanceDateTime`` UTC but files disagree; the shift is the
    one that puts most filings inside EDGAR hours on their ``filingDate``.
    """
    best, best_ok = 1, -1
    for shift in (1, 0, 2):
        ok = sum(
            d is not None and 6 <= d.hour < 22 and d.strftime("%Y-%m-%d") == f
            for d, f in zip(new_york_times(raw, shift), filing_dates)
        )
        if ok > best_ok:
            best, best_ok = shift, ok
    return best


# ---------------------------------------------------------------------------
# EDGAR
# ---------------------------------------------------------------------------

def _json(url: str, key: str | None = None) -> dict:
    """GET through ``edgar._get`` (User-Agent, <= 10 req/s), retried until it parses (and holds
    ``key``): the full-text search answers transient errors as JSON. Raises after TRIES."""
    if not edgar._USER_AGENT:
        raise EarningsError("EDGAR_USER_AGENT absent")
    for attempt in range(TRIES):
        resp = edgar._get(url)
        try:
            doc = json.loads(resp.text) if resp is not None else None
        except ValueError:
            doc = None
        if doc is not None and (key is None or key in doc):
            return doc
        logger.warning("EDGAR try %d/%d failed (%s): %s", attempt + 1, TRIES,
                       None if resp is None else resp.text[:120], url)
        if attempt < TRIES - 1:
            time.sleep(10 * (attempt + 1))
    raise EarningsError(f"EDGAR unreadable after {TRIES} tries: {url}")


def filings(forms: str, start: date, end: date) -> pd.DataFrame:
    """Filings of ``forms`` filed from ``start`` to ``end``: cik, accession, form, filed, items.

    Source: the EDGAR full-text search index, one row per (filer CIK, filing).
    """
    rows: dict[tuple[int, str], tuple] = {}
    a = start
    while a <= end:
        b = min(a + timedelta(days=WINDOW_DAYS - 1), end)
        frm = 0
        while True:
            q = urlencode({"forms": forms, "startdt": a.isoformat(), "enddt": b.isoformat(), "from": frm})
            page = _json(f"{EFTS_URL}?{q}", key="hits")
            hits = page["hits"]["hits"]
            for h in hits:
                s = h["_source"]
                for c in s.get("ciks", []):
                    rows[(int(c), s["adsh"])] = (int(c), s["adsh"], s["form"], s["file_date"], ",".join(s.get("items") or []))
            frm += len(hits)
            if not hits or frm >= page["hits"]["total"]["value"]:
                break
        a = b + timedelta(days=1)
    df = pd.DataFrame(list(rows.values()), columns=["cik", "accession", "form", "filed", "items"])
    return df.assign(filed=pd.to_datetime(df["filed"]).astype("datetime64[ns]"))


def zip_facts(path: Path, ciks: set[int]) -> pd.DataFrame:
    """EPS facts of ``ciks`` read in a bulk ``companyfacts.zip``."""
    rows: list[tuple] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for cik in sorted(ciks):
            name = f"CIK{cik:010d}.json"
            if name in names:
                rows += [(cik, *r[1:]) for r in eps_rows(json.loads(z.read(name)))]
    return facts_frame(rows)


def _download_zip(path: Path) -> Path:
    """Bulk ``companyfacts.zip`` (one request, ~1.4 GB) streamed to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    edgar._throttle()
    with requests.get(FACTS_ZIP_URL, headers={"User-Agent": edgar._USER_AGENT}, stream=True, timeout=60) as r:
        if r.status_code != 200:
            raise EarningsError(f"companyfacts.zip: HTTP {r.status_code}")
        with path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    return path


def quarter_bounds(quarter: pd.Period, facts_zip: Path | None = None) -> np.ndarray | None:
    """Quintile bounds for the releases of ``quarter``: SUE of the previous quarter's releases.

    Releases = 8-K item 2.02 filed in the previous calendar quarter (full-text
    search), EPS from the bulk companyfacts (``facts_zip``, else downloaded and
    deleted). Cached per quarter under DATA_DIR/earnings; recomputed weekly until
    LINK_DAYS after the previous quarter's end (its last 10-Q are filed by then).
    None when no release has a SUE.
    """
    prev = quarter - 1
    cache = EARNINGS_DIR / f"bounds_{quarter}.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        age = (datetime.now() - datetime.fromisoformat(c["computed"])).days
        if c["complete"] or age < BOUNDS_REFRESH_DAYS:
            return None if c["bounds"] is None else np.array(c["bounds"])
    rel = filings("8-K", prev.start_time.date(), prev.end_time.date())
    rel = rel[rel["items"].str.contains(ITEM_202)].rename(columns={"filed": "t"})
    tmp = None if facts_zip else EARNINGS_DIR / "companyfacts.zip"
    try:
        eps = seasonal_sue(quarterly_eps(zip_facts(facts_zip or _download_zip(tmp), set(rel["cik"]))))
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    sue = link_events(rel, eps)["sue"].dropna()
    bounds = np.quantile(sue, QUANTILES) if len(sue) else None
    now = datetime.now()
    EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "quarter": str(quarter), "n": int(len(sue)), "computed": now.isoformat(),
        "complete": now >= prev.end_time + timedelta(days=LINK_DAYS),
        "bounds": None if bounds is None else bounds.tolist(),
    }))
    logger.info("bounds %s: %d releases with a SUE", quarter, len(sue))
    return bounds


def _company(cik: int) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, datetime | None]]:
    """(8-K 2.02 releases, quarterly EPS with SUE, acceptance time per accession) of one CIK."""
    cik10 = f"{cik:010d}"
    subs = edgar._cached_text(edgar._SUBMISSIONS_URL.format(cik10=cik10), f"submissions_{cik10}.json", FRESH_S)
    facts = edgar._cached_text(edgar._COMPANYFACTS_URL.format(cik10=cik10), f"facts_{cik10}.json", FRESH_S)
    if subs is None or facts is None:
        raise EarningsError(f"EDGAR unreadable for CIK {cik}")
    r = json.loads(subs)["filings"]["recent"]
    raw = r["acceptanceDateTime"]
    times = new_york_times(raw, file_shift(raw, r["filingDate"]))
    accepted = dict(zip(r["accessionNumber"], times))
    items = list(r.get("items") or []) + [""] * len(r["form"])
    rel = pd.DataFrame(
        [(cik, t, acc) for f, acc, it, t in zip(r["form"], r["accessionNumber"], items, times)
         if f in ("8-K", "8-K/A") and t is not None and re.search(ITEM_202, it or "")],
        columns=["cik", "t", "accession"],
    )
    eps = seasonal_sue(quarterly_eps(facts_frame(eps_rows(json.loads(facts)))))
    return rel.astype({"cik": "int64", "t": "datetime64[ns]"}), eps, accepted


def universe() -> dict[int, str]:
    """CIK -> ticker of the Finviz export rows whose tier is in ``earnings.tiers``."""
    if not CFG["tiers"]:
        return {}
    snap = finviz.snapshot()
    ciks = edgar._load_cik_map()
    if snap is None or not ciks:
        raise EarningsError("Finviz export or EDGAR ticker map unreadable: universe unknown")
    out: dict[int, str] = {}
    for ticker, row in sorted(snap.items()):
        cik = ciks.get(ticker)
        if cik is not None and tier_of(row.get("marketCap")) in CFG["tiers"]:
            out.setdefault(cik, ticker)
    return out


def detect(session: date) -> pd.DataFrame:
    """Releases of ``session`` in the universe, with SUE, quintile and entry date."""
    univ = universe()
    cols = ["ticker", "cik", "form", "period_end", "eps", "sue", "sue_q", "release_t",
            "eps_t", "first_close", "entry"]
    if not univ:
        return pd.DataFrame(columns=cols)
    prev = sessions(session - timedelta(days=10), session - timedelta(days=1))[-1].date()
    fil = filings("10-Q,10-K", prev, session)
    fil = fil[fil["cik"].isin(univ)]
    logger.info("10-Q/10-K filed %s..%s in the universe: %d CIK", prev, session, fil["cik"].nunique())
    parts = []
    for cik, g in fil.groupby("cik"):
        rel, eps, accepted = _company(int(cik))
        if rel.empty or eps.empty:
            continue
        ev = link_events(rel, eps)
        ev = ev[ev["accn"].isin(set(g["accession"]))]
        if ev.empty:
            continue
        parts.append(ev.assign(eps_t=ev["accn"].map(accepted)))
    if not parts:
        return pd.DataFrame(columns=cols)
    ev = pd.concat(parts, ignore_index=True).astype({"eps_t": "datetime64[ns]"})
    ev = ev.join(entry_dates(ev["eps_t"]))
    ev = ev[ev["first_close"] == pd.Timestamp(session)].reset_index(drop=True)
    drift = entry_dates(ev["t"])["first_close"]
    ev["sue_q"] = 0
    for k in drift.dt.to_period("Q").dropna().unique():
        at = (drift.dt.to_period("Q") == k).to_numpy()
        ev.loc[at, "sue_q"] = quintile(ev.loc[at, "sue"], quarter_bounds(k))
    ev["ticker"] = ev["cik"].map(univ)
    return ev.rename(columns={"t": "release_t"})[cols]


def main(argv: list[str] | None = None) -> int:
    """CLI: print the releases of one session (default: the previous one) and the duration."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", type=date.fromisoformat)
    a = ap.parse_args(argv)
    today = datetime.now(NY).date()
    session = a.session or sessions(today - timedelta(days=10), today - timedelta(days=1))[-1].date()
    t0 = time.time()
    ev = detect(session)
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(ev.to_string(index=False) if len(ev) else "aucune publication")
    print(f"séance {session} · {len(CFG['tiers'])} tier(s) configuré(s) · {len(ev)} publication(s) · Q5 {int((ev['sue_q'] == 5).sum())} · durée {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
