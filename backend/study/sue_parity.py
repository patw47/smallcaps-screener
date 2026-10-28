"""Parity of backend/earnings.py with ta-patterns on one year of releases of the lake (Epic 15 S3).

The 8-K 2.02 releases of the lake (``edgar_earnings.parquet``) go through the
live code: EPS of the lake's ``companyfacts.zip`` (``zip_facts``,
``quarterly_eps``, ``seasonal_sue``), one event per (CIK, quarter end)
(``link_events``), first public close (``first_close``), quintile against
``quarter_bounds`` (releases listed by the EDGAR full-text search, as live).
Each event of ``events.parquet`` (earn, edgar) of the year is matched on
(symbol, drift_date) and its ``sue`` / ``sue_q`` compared. The lake is read only.

Usage (Windows venv of ta-patterns, from backend/, network for the bounds):
    python -B -m study.sue_parity --config ../config/local.yml [--year 2025]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from study.earnings import first_close
from study.lake import CONFIG_FILE, import_tools, lake_dir

PARITY_MIN: Final[float] = 0.99
SUE_RTOL: Final[float] = 1e-9
HISTORY_DAYS: Final[int] = 180  # earlier 8-K of the same quarter, for the repeat rule


def main(argv: list[str] | None = None) -> int:
    """Print the share of the year's events whose SUE and quintile match; 1 under PARITY_MIN."""
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=CONFIG_FILE)
    ap.add_argument("--year", type=int, default=2025)
    a = ap.parse_args(argv)
    lake = lake_dir(a.config)
    if lake is None:
        print(f"study.ta_patterns_dir absent de {a.config}", file=sys.stderr)
        return 2
    print(f"ta-patterns {import_tools(lake)}")
    import pyarrow.parquet as pq
    from tools.lake.norgate import LAKE_DIR
    from tools.measure.outcomes import DERIVED_DIR

    import earnings as live

    t0 = time.time()
    y0, y1 = pd.Timestamp(f"{a.year}-01-01"), pd.Timestamp(f"{a.year + 1}-01-01")
    pub = pd.read_parquet(DERIVED_DIR / "events.parquet")
    pub = pub[(pub["kind"] == "earn") & (pub["source"] == "edgar")]
    pub = pub.assign(drift_date=pub["drift_date"].astype("datetime64[ns]"))
    pub = pub[(pub["drift_date"] >= y0) & (pub["drift_date"] < y1)][["symbol", "drift_date", "sue", "sue_q"]]

    # Same order as ta-patterns edgar_earnings_events: no_symbol, out_of_range, link, repeat.
    earn = pd.read_parquet(LAKE_DIR / "edgar_earnings.parquet")
    earn = earn[(earn["accepted"] >= y0 - pd.Timedelta(days=HISTORY_DAYS)) & (earn["accepted"] < y1 + pd.Timedelta(days=15))]
    earn = earn.dropna(subset=["symbol"]).astype({"symbol": str, "accepted": "datetime64[ns]"})
    prices = pq.read_table(
        LAKE_DIR / "prices.parquet", columns=["symbol", "date"],
        filters=[("date", ">=", (y0 - pd.Timedelta(days=HISTORY_DAYS + 30)).to_pydatetime())],
    ).to_pandas()
    sessions = prices[prices["symbol"].astype(str).isin(set(earn["symbol"]))].astype({"symbol": str})
    earn["drift_date"] = first_close(sessions, earn["symbol"], earn["accepted"])
    earn = earn.dropna(subset=["drift_date"])
    facts_zip = LAKE_DIR.parent / "cache" / "edgar" / "companyfacts.zip"
    eps = live.seasonal_sue(live.quarterly_eps(live.zip_facts(facts_zip, set(earn["cik"]))))
    ev = live.link_events(earn.rename(columns={"accepted": "t"})[["cik", "t", "accession", "symbol", "drift_date"]], eps)
    ev = ev.drop_duplicates(["symbol", "drift_date"])
    print(f"events {a.year}: ta-patterns {len(pub)}, live {int(((ev['drift_date'] >= y0) & (ev['drift_date'] < y1)).sum())}; {time.time() - t0:.0f}s")

    m = pub.merge(ev[["symbol", "drift_date", "sue"]], on=["symbol", "drift_date"], how="left", suffixes=("_ta", ""))
    k = m["drift_date"].dt.to_period("Q")
    m["sue_q_live"] = 0
    for q in sorted(k.unique()):
        at = (k == q).to_numpy()
        m.loc[at, "sue_q_live"] = live.quintile(m.loc[at, "sue"], live.quarter_bounds(q, facts_zip=facts_zip))
    sue_ok = np.isclose(m["sue"], m["sue_ta"], rtol=SUE_RTOL, atol=0)
    q_ok = (m["sue_q_live"] == m["sue_q"]).to_numpy()
    for q in sorted(k.unique()):
        at = (k == q).to_numpy()
        print(f"  {q}: n={at.sum()} sue {sue_ok[at].mean():.4f} quintile {q_ok[at].mean():.4f}")
    both = float((sue_ok & q_ok).mean())
    print(
        f"parité {a.year} : n={len(m)} trouvés={int(m['sue'].notna().sum())} "
        f"SUE égale (rtol {SUE_RTOL}) {sue_ok.mean():.4f} · quintile égal {q_ok.mean():.4f} · "
        f"les deux {both:.4f} (seuil {PARITY_MIN}) ; durée {time.time() - t0:.0f}s"
    )
    return 0 if both >= PARITY_MIN else 1


if __name__ == "__main__":
    sys.exit(main())
