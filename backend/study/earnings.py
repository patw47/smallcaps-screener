"""Realisable earnings-surprise Q5 alert, measured on the ta-patterns lake (Epic 15 S1).

ta-patterns dates each Q5 case at ``drift_date``, the first public close after
the 8-K item 2.02, but reads the quarter's EPS in the 10-Q / 10-K XBRL filed up
to ``LINK_DAYS`` later. An alert reading XBRL can only enter after that filing.
Three variants of the same Q5 population (``sue_q`` = 5 of events.parquet):

- A, reproduction: case at ``drift_date``.
- B, XBRL realisable: case at the first public close after the acceptance of
  the filing that carries the quarter's EPS (same 16:00 New York rule).
- C, Finviz realisable: timing of A, EPS read in Finviz; judged by A's verdict
  plus the agreement of Finviz EPS with XBRL EPS on the survivors.

Same chain as ta-patterns Epic 6: ``costs.horizons`` (gap to the (date, tier,
vol_q) cell net of the Corwin-Schultz spread, clustered se) per variant, tier
and period; ``compare.measure`` per variant; the same populations on the GARCH
placebo prices of the lake. Every output goes to data/study/ (gitignored).

Usage (Windows venv of ta-patterns, from backend/):
    python -B -m study.earnings --config ../config/local.yml --step cases|net|measure|placebo|verdict|all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from study.lake import CONFIG_FILE, STUDY_DIR, import_tools, lake_dir

LINK_DAYS: Final[int] = 90  # tools/rules/events.py of ta-patterns
CLOSE_HOUR: Final[int] = 16  # New York: a filing from 16:00 on reaches the next close
YEAR_TOLERANCE: Final[pd.Timedelta] = pd.Timedelta(days=15)
EPS_TOL: Final[float] = 0.01  # USD per share
AGREEMENT_MIN: Final[float] = 0.95
T_MIN: Final[float] = 3.0  # Harvey, Liu & Zhu 2016
MIN_N: Final[int] = 2_000  # min_n of ta-patterns
HORIZONS: Final[tuple[int, ...]] = (5, 21, 63)
TIERS: Final[tuple[str, ...]] = ("ex_nano", "micro", "small", "mid", "large", "mega")
N_PERM: Final[int] = 200
RULE: Final[str] = (
    "Règle de décision pré-enregistrée, écrite avant toute mesure : une variante de "
    "l'alerte est GARDÉE si son rendement net du spread, hors nano, à h = 5 ou h = 21, "
    "a t ≥ +3 (t = net / se ; seuil Harvey, Liu & Zhu 2016, Review of Financial "
    "Studies 29(1), règle de ta-patterns depuis le 2026-10-10). Sinon : |t| < 3 = "
    "« non prouvé », t ≤ −3 = « réfuté ». Aucune variante gardée = arrêt de l'epic "
    "après le Sprint 1. Un tier n'est dans l'univers de l'alerte que si cette règle "
    "tient dans ce tier, avec n ≥ 2 000 (`min_n` de ta-patterns, héritage)."
)
FILES: Final[dict[str, str]] = {
    k: f"earnings_{k}.parquet"
    for k in ("cases", "agreement", "net", "measure", "placebo", "verdict")
}


# ---------------------------------------------------------------------------
# Pure functions (synthetic tests, no lake)
# ---------------------------------------------------------------------------

def _ns(s: pd.Series) -> pd.Series:
    return s.astype("datetime64[ns]")


def first_close(sessions: pd.DataFrame, symbol: pd.Series, t: pd.Series) -> pd.Series:
    """Date of the first public close after ``t`` (New York time), NaT past the data.

    Rule of ``drift_date``: before 16:00 on a session day, that day's close;
    from 16:00 on, or on a day without session, the symbol's next session.
    ``sessions``: one row per (symbol, date) the symbol trades.
    """
    t = _ns(t)
    d = t.dt.normalize() + pd.to_timedelta((t.dt.hour >= CLOSE_HOUR).astype(int), unit="D")
    q = pd.DataFrame({"symbol": symbol.astype(str).to_numpy(), "d": d.to_numpy(), "i": np.arange(len(t))})
    q = q.dropna(subset=["d"]).astype({"symbol": str}).sort_values("d", kind="stable")
    s = sessions[["symbol", "date"]].astype({"symbol": str, "date": "datetime64[ns]"})
    m = pd.merge_asof(
        q, s.sort_values("date", kind="stable"), left_on="d", right_on="date",
        by="symbol", direction="forward",
    )
    out = pd.Series(pd.NaT, index=range(len(t)), dtype="datetime64[ns]")
    out.iloc[m["i"].to_numpy()] = m["date"].to_numpy()
    return pd.Series(out.to_numpy(), index=t.index)


def link_eps(events: pd.DataFrame, eps: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    """Each event's quarter: last ``period_end`` before its day, filed 0..LINK_DAYS after.

    ``events``: ``cik``, ``t`` (8-K acceptance). ``eps``: ``cik``, ``period_end``,
    ``filed`` (+ any column carried). Link rule of ta-patterns
    ``edgar_earnings_events``; an event without such a filing is dropped as
    ``no_eps``.
    """
    e = events.assign(day=_ns(events["t"]).dt.normalize()).sort_values("day", kind="stable")
    q = eps.assign(period_end=_ns(eps["period_end"]), filed=_ns(eps["filed"]))
    m = pd.merge_asof(
        e, q.sort_values("period_end", kind="stable"), left_on="day",
        right_on="period_end", by="cik", allow_exact_matches=False,
    )
    lag = (m["filed"] - m["day"]).dt.days
    bad = ~lag.between(0, LINK_DAYS).to_numpy()
    return m[~bad].reset_index(drop=True), Counter(no_eps=int(bad.sum()))


def variant_b(
    events: pd.DataFrame, eps: pd.DataFrame, sessions: pd.DataFrame
) -> tuple[pd.DataFrame, Counter]:
    """``events`` plus ``date_b``: first public close after the EPS filing's ``accepted``.

    Dropped: ``no_eps`` (``link_eps``), ``out_of_range`` (no session after it).
    """
    b, n = link_eps(events, eps)
    b["date_b"] = first_close(sessions, b["symbol"], b["accepted"])
    out = b["date_b"].isna().to_numpy()
    n["out_of_range"] = int(out.sum())
    return b[~out].reset_index(drop=True), n


def eps_agreement(xbrl: pd.DataFrame, finviz: pd.DataFrame) -> pd.DataFrame:
    """XBRL quarters (symbol, period_end, eps) paired with Finviz (symbol, fiscal_end, eps_actual).

    Same symbol, nearest fiscal end within 15 days; ``ok`` = |difference| <= 0.01 $.
    """
    x = xbrl.assign(symbol=xbrl["symbol"].astype(str), period_end=_ns(xbrl["period_end"]))
    f = finviz[["symbol", "fiscal_end", "eps_actual"]].dropna()
    f = f.assign(symbol=f["symbol"].astype(str), fiscal_end=_ns(f["fiscal_end"]))
    m = pd.merge_asof(
        x.sort_values("period_end", kind="stable"),
        f.sort_values("fiscal_end", kind="stable"),
        left_on="period_end", right_on="fiscal_end", by="symbol",
        direction="nearest", tolerance=YEAR_TOLERANCE,
    ).dropna(subset=["eps_actual"])
    return m.assign(ok=(m["eps"] - m["eps_actual"]).abs() <= EPS_TOL + 1e-9)


def decide(t5: float, t21: float, n: int) -> str:
    """Pre-registered rule: kept at t >= 3 at h = 5 or 21 with n >= MIN_N."""
    if n >= MIN_N and (t5 >= T_MIN or t21 >= T_MIN):
        return "garder"
    if t5 <= -T_MIN or t21 <= -T_MIN:
        return "réfuté"
    return "non prouvé"


def verdict_table(net: pd.DataFrame, agreement: float) -> pd.DataFrame:
    """One row per (variant, tier) from ``costs.horizons`` rows of variants A and B.

    ``net``: rule, tier, horizon, n, long_net, se_long. C copies A (same timing)
    and is kept only when A is kept and ``agreement`` >= AGREEMENT_MIN.
    """
    v = net[net["rule"].isin(["A", "B"]) & net["tier"].isin(TIERS) & net["horizon"].isin(HORIZONS)]
    w = v.pivot_table(index=["rule", "tier"], columns="horizon", values=["n", "long_net", "se_long"])
    out = pd.DataFrame(index=w.index)
    out["n"] = w[("n", 21)].astype(int)
    for h in HORIZONS:
        out[f"net_{h}"] = w[("long_net", h)]
        out[f"se_{h}"] = w[("se_long", h)]
    for h in (5, 21):
        out[f"t_{h}"] = out[f"net_{h}"] / out[f"se_{h}"]
    out = out.reset_index().rename(columns={"rule": "variant"})
    out["verdict"] = [decide(a, b, n) for a, b, n in zip(out["t_5"], out["t_21"], out["n"])]
    c = out[out["variant"] == "A"].assign(variant="C")
    c.loc[(c["verdict"] == "garder") & (agreement < AGREEMENT_MIN), "verdict"] = "accord insuffisant"
    order = {t: i for i, t in enumerate(TIERS)}
    out = pd.concat([out, c], ignore_index=True)
    return out.sort_values(["variant", "tier"], key=lambda s: s.map(order) if s.name == "tier" else s)


# ---------------------------------------------------------------------------
# Lake steps (Windows venv of ta-patterns)
# ---------------------------------------------------------------------------

def accepted_times(sub_zip: Path, eps: pd.DataFrame, ciks: set[int]) -> tuple[pd.Series, pd.Series]:
    """Acceptance time (New York) of the filing behind each ``eps`` row, for ``ciks``.

    companyfacts gives the filing date only; submissions.zip gives
    ``acceptanceDateTime`` per filing (time zone of each file corrected by
    ta-patterns ``edgar.file_shift``). Matched on (cik, filing date, form),
    then (cik, filing date) on any 10- form. Unmatched rows: filing date at
    16:00 (next close, the latest the value can be public), ``known`` False.
    """
    from tools.lake import edgar

    rows = []
    with zipfile.ZipFile(sub_zip) as z:
        names = [n for n in z.namelist() if n.endswith(".json") and n[3:13].isdigit() and int(n[3:13]) in ciks]
        for name in names:
            cols = edgar._filing_columns(json.loads(z.read(name)))
            forms = cols.get("form", [])
            hit = [i for i, f in enumerate(forms) if f.startswith("10-")]
            if not hit:
                continue
            raw = cols["acceptanceDateTime"]
            times = edgar.new_york_times([raw[i] for i in hit], edgar.file_shift(raw, cols["filingDate"]))
            rows += [(int(name[3:13]), forms[i], cols["filingDate"][i], tm) for i, tm in zip(hit, times)]
    s = pd.DataFrame(rows, columns=["cik", "form", "filed", "accepted"])
    s = s.assign(filed=pd.to_datetime(s["filed"]), accepted=pd.to_datetime(s["accepted"]))
    s = s.dropna().groupby(["cik", "filed", "form"], as_index=False)["accepted"].min()
    e = eps[["cik", "filed", "form"]].assign(filed=_ns(eps["filed"]).dt.normalize())
    exact = e.merge(s, on=["cik", "filed", "form"], how="left")["accepted"]
    loose = e.merge(s.groupby(["cik", "filed"], as_index=False)["accepted"].min(), on=["cik", "filed"], how="left")["accepted"]
    acc = exact.fillna(loose)
    known = acc.notna().to_numpy()
    acc = acc.fillna(e["filed"] + pd.Timedelta(hours=CLOSE_HOUR))
    return pd.Series(acc.to_numpy(), index=eps.index), pd.Series(known, index=eps.index)


def step_cases(out: Path) -> int:
    """Q5 cases of A and B (earnings_cases) and the Finviz / XBRL EPS pairs (earnings_agreement)."""
    from tools.lake.norgate import LAKE_DIR
    from tools.measure.outcomes import DERIVED_DIR
    from tools.rules import events as ev

    t0 = time.time()
    panel = ev.load_panel(LAKE_DIR, DERIVED_DIR)
    keys = ev.panel_keys(panel)
    earn = pd.read_parquet(LAKE_DIR / "edgar_earnings.parquet")
    eps = pd.read_parquet(LAKE_DIR / "edgar_eps.parquet")
    ed, _ = ev.edgar_earnings_events(earn, eps, panel, keys)
    cik = earn[["symbol", "accepted", "cik"]].dropna().drop_duplicates(["symbol", "accepted"])
    ed = ed.merge(cik.rename(columns={"accepted": "t"}).astype({"t": ed["t"].dtype}), on=["symbol", "t"], how="left")
    pub = pd.read_parquet(DERIVED_DIR / "events.parquet")
    pub = pub[(pub["kind"] == "earn") & (pub["source"] == "edgar")][["symbol", "drift_date", "sue_q"]]
    ed = ed.astype({"drift_date": "datetime64[ns]"}).merge(
        pub.astype({"drift_date": "datetime64[ns]"}), on=["symbol", "drift_date"], how="inner"
    )
    print(f"events edgar: {len(ed)} rebuilt and in events.parquet (events.parquet: {len(pub)})")
    used = set(ed["symbol"])
    sessions = panel.loc[panel["symbol"].isin(used), ["symbol", "date"]].astype({"symbol": str})
    del panel, keys
    a = first_close(sessions, ed["symbol"], ed["t"])
    print(f"first_close(8-K) == drift_date: {float((a == ed['drift_date']).mean()):.4f} of {len(ed)}")

    q = ev.seasonal_sue(eps)
    q5 = ed[ed["sue_q"] == 5].reset_index(drop=True)
    q["accepted"], q["time_known"] = accepted_times(
        LAKE_DIR.parent / "cache" / "edgar" / "submissions.zip", q, set(q5["cik"].astype(int))
    )
    b, n_b = variant_b(q5[["symbol", "cik", "t", "drift_date", "sue"]], q.drop(columns="sue"), sessions)
    print(f"Q5: {len(q5)} cases A, {len(b)} cases B, dropped {dict(n_b)}, filing time unknown {int((~b['time_known']).sum())} B cases")
    cases = pd.concat(
        [
            q5.assign(variant="A", date=q5["drift_date"])[["variant", "symbol", "date", "t"]],
            b.assign(variant="B", date=b["date_b"])[["variant", "symbol", "date", "t", "accepted", "time_known", "form", "period_end"]],
        ],
        ignore_index=True,
    )
    out.mkdir(parents=True, exist_ok=True)
    cases.to_parquet(out / FILES["cases"], index=False)

    x, _ = link_eps(ed[["symbol", "cik", "t", "sue_q"]], q[["cik", "period_end", "filed", "eps"]])
    fz = ev.finviz_resolved(pd.read_parquet(LAKE_DIR / "earnings.parquet"), pd.read_parquet(LAKE_DIR / "symbols.parquet"))
    agree = eps_agreement(x[["symbol", "period_end", "eps", "sue_q"]], fz.dropna(subset=["symbol"]))
    agree.to_parquet(out / FILES["agreement"], index=False)
    print(f"EPS pairs Finviz / XBRL: {len(agree)}; duration {time.time() - t0:.0f}s")
    return 0


def step_net(out: Path) -> int:
    """``costs.horizons`` on A and B, whole and per period (earnings_net)."""
    import pyarrow.parquet as pq
    from tools.measure import costs
    from tools.measure.outcomes import DERIVED_DIR
    from tools.rules.high52 import PERIODS

    cases = pd.read_parquet(out / FILES["cases"])
    o = pq.read_table(DERIVED_DIR / "outcomes.parquet", columns=["symbol", "date"], read_dictionary=["symbol"]).to_pandas()
    o["symbol"] = o["symbol"].cat.set_categories(sorted(o["symbol"].cat.categories))
    year = o["date"].dt.year.to_numpy()
    pops = {}
    for v, g in cases.groupby("variant"):
        e = g.assign(kind="earn", source="edgar", sue_q=5, n_buyers=0, drift_date=g["date"])
        m = costs.event_masks(e, o)["E6 earn Q5"]
        pops[v] = m
        for y0, y1 in PERIODS:
            pops[f"{v} {y0}-{y1}"] = m & (year >= y0) & (year <= y1)
    del o
    return costs.horizons(hold=HORIZONS, path=out / FILES["net"], pops=pops)


def step_measure(out: Path) -> int:
    """``compare.measure`` of A and B on the lake (earnings_measure)."""
    from tools.measure.outcomes import DERIVED_DIR
    from tools.measure.pool import measure_jobs

    cases = pd.read_parquet(out / FILES["cases"])
    names = sorted(cases["variant"].unique())
    pops = [cases.loc[cases["variant"] == v, ["symbol", "date"]] for v in names]
    res = measure_jobs([(None, pops)], DERIVED_DIR, N_PERM, 0, 1)[0]
    res = pd.concat([r.assign(variant=v) for v, r in zip(names, res)], ignore_index=True)
    res.to_parquet(out / FILES["measure"], index=False)
    with pd.option_context("display.width", 200):
        print(res[["variant", "horizon", "part", "n", "delta", "p_adj", "mean_delta", "mean_p_adj"]].to_string(index=False))
    return 0


def step_placebo(out: Path) -> int:
    """A and B on the GARCH placebo prices of the lake, tolerances of ta-patterns ``run_events``."""
    from tools.measure.compare import load_inputs, measure, presort
    from tools.measure.outcomes import START
    from tools.rules import placebo_garch as pg

    cases = pd.read_parquet(out / FILES["cases"])
    o, daily = load_inputs(None, pg.PLACEBO_DIR)
    o = presort(o)[0]
    in_base = ((o["date"] >= START) & (o["tier"] != "none") & (o["vol_q"] >= 1)).to_numpy()
    base = o.loc[in_base, ["symbol", "date"]].assign(i=np.flatnonzero(in_base))
    sym = o["symbol"].to_numpy()
    parts = []
    for v, g in cases.groupby("variant"):
        c = g[["symbol", "date"]].astype({"date": "datetime64[ns]"})
        r = measure(c, o, daily, n_perm=N_PERM, seed=0, presorted=True)
        i = c.drop_duplicates().merge(base, on=["symbol", "date"])["i"].to_numpy()
        ret = [o[f"r_{p}_{h}"].to_numpy(float)[i] for p, h in zip(r["part"], r["horizon"])]
        r["se"] = [pg.cluster_se(sym[i], x) for x in ret]
        r["freq_se"] = [pg.cluster_se(sym[i], np.where(np.isfinite(x), x > 0, np.nan)) for x in ret]
        parts.append(r.assign(flag=v))
    res = pd.concat(parts, ignore_index=True)
    res["tol"] = pg.mean_tol_of(res, pg.MEAN_TOL, pg.MEAN_SE_K)
    floor = np.where(res["part"] == "night", pg.TOL_NIGHT, pg.TOL)
    res["freq_tol"] = np.fmax(floor, pg.MEAN_SE_K * res["freq_se"].to_numpy(float))
    res.to_parquet(out / FILES["placebo"], index=False)
    with pd.option_context("display.width", 200):
        print(res[["flag", "horizon", "part", "n", "delta", "freq_tol", "mean_delta", "tol"]].to_string(index=False))
    fails = pg.verdict(res, name="STUDY", mean_tol=pg.MEAN_TOL)
    print("\n".join(fails) if fails else "STUDY PLACEBO OK")
    return 1 if fails else 0


def step_verdict(out: Path) -> int:
    """Print the rule, one line per (variant, tier), the 8-K -> 10-Q delay and the EPS agreement."""
    agree = pd.read_parquet(out / FILES["agreement"])
    share = float(agree["ok"].mean())
    v = verdict_table(pd.read_parquet(out / FILES["net"]), share)
    v.to_parquet(out / FILES["verdict"], index=False)
    print(RULE)
    print()
    for r in v.itertuples():
        print(
            f"{r.variant} {r.tier:<8} n={r.n:>6} net_5={100 * r.net_5:+.2f} net_21={100 * r.net_21:+.2f} "
            f"net_63={100 * r.net_63:+.2f} pt  t_5={r.t_5:+.2f} t_21={r.t_21:+.2f}  {r.verdict}"
        )
    b = pd.read_parquet(out / FILES["cases"])
    b = b[b["variant"] == "B"]
    days = (b["accepted"] - b["t"]).dt.total_seconds() / 86_400
    print()
    print(
        f"délai 8-K -> dépôt de l'EPS (jours civils, n={len(days)}) : médiane {days.median():.1f}, "
        f"p90 {days.quantile(0.9):.1f}, part <= 1 jour {float((days <= 1).mean()):.3f} ; "
        f"heure de dépôt inconnue (entrée au close suivant) {float((~b['time_known'].astype(bool)).mean()):.3f}"
    )
    q5 = agree[agree["sue_q"] == 5]
    print(
        f"accord EPS Finviz / XBRL à {EPS_TOL} $ (survivants) : {share:.3f} (n={len(agree)}), "
        f"Q5 {float(q5['ok'].mean()):.3f} (n={len(q5)}) ; seuil C {AGREEMENT_MIN}"
    )
    return 0


STEPS: Final = {"cases": step_cases, "net": step_net, "measure": step_measure, "placebo": step_placebo, "verdict": step_verdict}


def main(argv: list[str] | None = None) -> int:
    """CLI: one step, or all in order."""
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=CONFIG_FILE)
    ap.add_argument("--step", choices=[*STEPS, "all"], default="all")
    a = ap.parse_args(argv)
    lake = lake_dir(a.config)
    if lake is None:
        print(f"study.ta_patterns_dir absent de {a.config}", file=sys.stderr)
        return 2
    print(f"ta-patterns {import_tools(lake)}")
    rc = 0
    for name in STEPS if a.step == "all" else [a.step]:
        t0 = time.time()
        rc |= STEPS[name](STUDY_DIR)
        print(f"step {name}: {time.time() - t0:.0f}s", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
