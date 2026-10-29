# Backend

The backend has one job: the post-earnings alert (Epic 15). The former scan (two-pass
funnel, score, Fusée / Phénix profiles, washout cohorts, performance tracker) was removed
in Epic 15 S2; its theses and verdicts stay in
[backtest_protocol_v2.md](backtest_protocol_v2.md) / [backtest_protocol_v3.md](backtest_protocol_v3.md).

## Files

- `backend/earnings.py`: live earnings releases of one session with their seasonal surprise (SUE), quintile and entry date — see *Earnings releases* below.
- `backend/run_earnings.py`: the job (Telegram, journal, realized returns) — see *Alert job* below.
- `backend/api.py`: FastAPI app, `GET /api/health`, `GET /api/alerts`, and the compiled page when `frontend/dist` exists.
- `backend/finviz.py`: Finviz Elite CSV export client; the alert reads the market cap from it (universe).
- `backend/edgar.py`: SEC/EDGAR client and the risk-file signals (dilution, late filing, going-concern doubt, cash runway).
- `backend/lifecycle.py`: the current risk file of a ticker (`current_risk_markers`) and the once-a-day EDGAR sweep (`scan_filings`).
- `backend/alerts.py`: `send_telegram`.
- `backend/screener_backend.py`: `FILTERS` (EDGAR and price-marker thresholds), `DATA_DIR`, loader of `config/local.yml`.
- `backend/study/`: offline studies on the ta-patterns lake, read only (`earnings.py`: the decision study, `lake.py`: access to the lake, `sue_parity.py`: parity of `earnings.py` with the lake) — see [backtest_protocol_v6.md](backtest_protocol_v6.md).
- `backend/tests/`: offline deterministic tests; tests marked `lake` are skipped without the lake.

## Configuration

`FILTERS` (`backend/screener_backend.py`) holds the thresholds of the risk file: `survival_window_days`, `edgar_cache_ttl_hours`, `edgar_rate_limit_s` (≤ 10 requests/s, SEC rule), `sub_dollar_*`, `reverse_split_window`. No magic number in the logic.

`config/local.yml` (gitignored, template `config/local.example.yml`) is merged at startup over **neutral code defaults**. Allowed sections: `filters`, `finviz`, `study`, `earnings`; an unknown key or section refuses to start (typo guard). `REQUIRE_LOCAL_CONFIG=1` refuses to start without the file.

| Section | Key | Meaning |
| --- | --- | --- |
| `study` | `ta_patterns_dir` | Path of the ta-patterns lake, read only. Empty: study tests are skipped. |
| `earnings` | `tiers` | Market-cap tiers kept by the study (micro / small, nano refused). Empty (code default): nobody enters. |
| `earnings` | `net` | Measured net return per horizon, shown in the Telegram message and on the page. Empty by default. |
| `earnings` | `notify_empty` | `true`: a "no release" message on sessions without alert. Default `false`. |
| `finviz` | `export_url`, `token` | Export link and token. Without a token the module is inactive. |

`make check-edge` fails if the code, tests, docs, `scripts/`, `deploy/` or the page carry a value of `config/local.yml` or a non-neutral default.

## Alert job (`run_earnings.py`)

`run(session)`: takes `earnings.detect(session)`, keeps `sue_q` = 5, sends one Telegram message per release never alerted (dedup on CIK + period end, read from the journal) and appends one line to `data/earnings/alerts.jsonl`. `update_returns` fills, when 5 / 21 / 63 sessions have passed, the realized return of the stock (open of the entry day to close of the horizon day, split- and dividend-adjusted, Yahoo chart API, no key) and IWM's over the same dates. `--bounds` precomputes the quintile bounds. Any error sends a Telegram message "job failed" and exits 1. Schedule and install: [deployment.md](deployment.md).

The message carries ticker, release and filing times, SUE, quintile, entry date, measured net return (from `config/local.yml`), the EDGAR risk flags and a Finviz quote link.

## Finviz export client (`finviz.py`, Epic 13)

`snapshot()` fetches the Finviz Elite screener CSV export in **one authenticated request** and
parses it into `{TICKER: {…}}`. The alert reads the **market cap** (`marketCap`) from it to place
a company in a tier (`earnings.universe`); the other mapped columns (`FIELD_MAP`, `CONTEXT_MAP`,
`_balance_sheet`) were built for the removed scan and are no longer consumed.

- **Never fatal**: missing token, dead network, unreadable CSV, empty cell → `None` (or a `None`
  field), never an exception.
- **Token**: `finviz:` section of `config/local.yml` (gitignored). Code defaults are neutral
  (`export_url: ""`, `token: ""`) → module inactive, no request attempted. The token is never
  printed: a network error logs the exception **type** only, because `requests` copies the whole
  URL — hence the token — into its own message.
- **Units**: the export **API** serves `Market Cap` and shares **in millions, without suffix**
  (`_millions`: bare value × 1e6, an explicit `K`/`M`/`B`/`T` suffix wins). Percentages arrive as
  text with `%` and become fractions; an empty cell or `-` yields `None`.
- **Column headers** are the export API's (longer than the screen's). A header may be a tuple of
  candidates (`_cell`): the first present in the CSV wins. A column absent from the `c=` codes of
  `export_url` reads `None`, exactly as a wrong header would.
- **Check a new export URL against one known market cap before trusting it** (command never prints
  the token); a small / micro-cap universe must show a median in the **hundreds of millions** — a
  median in the hundreds means the unit is wrong and no company would land in its tier:

  ```bash
  cd backend && CONFIG_FILE=../config/local.yml DATA_DIR=/tmp/screener_test python3 -c \
    "import finviz, statistics; s = finviz.snapshot(); \
     caps = [d['marketCap'] for d in (s or {}).values() if d['marketCap']]; \
     print(len(s or {}), 'rows · median cap', f'{statistics.median(caps):,.0f}')"
  ```

**Exchanges**: `EXCHANGES` maps `NASDAQ`/`NASD` → `NMS`, `NYSE` → `NYQ`, `AMEX`/`NYSE American` →
`ASE`; an unknown market → `None`.

## EDGAR client (`edgar.py`)

- **SEC compliance**: identifying `User-Agent` from **`EDGAR_USER_AGENT` env** (email); without
  it EDGAR is **disabled → signals `None`** (neutral). Global throttle ≤ 10 req/s
  (`edgar_rate_limit_s`). Local cache (`data/edgar_cache/`): submissions have a TTL,
  **filings are immutable and never re-downloaded**.
- The net Form 4 insider purchases (`net_insider_buying`) were removed in Epic 15 S3: no net
  advantage outside nano caps on the ta-patterns lake, and no caller left.

## Earnings releases — live SUE (`earnings.py`, Epic 15 S3)

`detect(session)` returns the earnings releases whose entry is decided by that session, with
their seasonal surprise, its quintile and the entry date. `make earnings [SESSION=YYYY-MM-DD]`
prints them (default: the last session whose 16:00 New York close has passed, `last_session`)
with the duration. The alert job that uses it on the VPS is described in `docs/deployment.md`
(*Earnings alert on the VPS*).

**Mechanism.** The market under-reacts to an earnings surprise and the price keeps drifting in
the direction of the surprise for weeks (post-earnings announcement drift, Ball & Brown 1968,
*Journal of Accounting Research* 6(2); Bernard & Thomas 1989, *JAR* 27). The surprise is
measured without analyst estimates, against the company's own history (seasonal SUE, Bernard &
Thomas 1990, *Journal of Accounting and Economics* 13(4)):

    SUE = (EPS_q − EPS_q−4) / standard deviation of the 8 previous seasonal differences (4 at least)

**Timing (variant B of the Epic 15 study).** The release (8-K item 2.02) is public first, but the
quarter's EPS is read in XBRL, which arrives with the 10-Q / 10-K. So the trigger is the 10-Q /
10-K that **first carries** the quarter's basic EPS (its accession is the first filing of that
fact in companyfacts), linked to an 8-K 2.02 filed at most 90 days before (same link rule as
the study, `study.earnings.link_eps`). Entry date = the open of the session after the first
public close following the 10-Q acceptance (16:00 New York rule, `study.earnings.first_close`;
NYSE calendar with fixed holidays). One event per (CIK, quarter end): a second 8-K 2.02 on a
quarter already linked repeats a public surprise and is dropped.

**Same numbers as ta-patterns.** Tags (`us-gaap:EarningsPerShareBasic`, USD/shares, durations
80–100 days and 350–380 days), first-filed value per quarter, Q4 derived as year − Q1 − Q2 −
Q3, and the SUE formula are ported from ta-patterns (`quarterly_eps`, `seasonal_sue`): the job
runs without the lake.

**Quintile.** Against the bounds (20/40/60/80 % quantiles) of the SUE of all 8-K 2.02 releases
of the **previous calendar quarter** — the bounds of the quarter being published would read
surprises published later. Releases are listed by the EDGAR full-text search (one query per
day), EPS read in the bulk `companyfacts.zip` (one request, ~1.4 GB, deleted after use). The
bounds are cached per quarter in `data/earnings/` (never in the repo) and recomputed weekly
until 90 days after the previous quarter's end. The XBRL frames API was tried first: its
values are the latest filed (not the first) and its population is every XBRL filer, not the
releasing companies, which left too many quintiles different from the lake's.

**Universe.** Capitalisation tiers listed in `config/local.yml` (`earnings.tiers`, Finviz bounds,
nano refused; code default empty = nothing enters), market cap read in the Finviz export. No
liquidity or price filter: none was measured.

**Parity with the lake.** `make earnings-parity [YEAR=2025]` (Windows venv of ta-patterns,
pyarrow) runs the lake's 8-K 2.02 releases and `companyfacts.zip` through this module and
compares SUE and quintile with `events.parquet`; it exits 1 under 99 % agreement.

## Risk file (`lifecycle.py`, `edgar.py`)

`edgar.survival_signals(ticker)` reads the recent submissions of the company (cache `data/edgar_cache/`, filings immutable and never re-downloaded): dilution filing (S-1 / S-3 / F-1 / F-3 / 424B), late filing (NT 10-K / 10-Q), going-concern doubt (ASC 205-40 wording), cash runway (XBRL companyfacts) and the most recent 8-K with its items. `lifecycle.current_risk_markers` turns them into **codes + level + variables** (`going_concern`, `reverse_split`, `dilution`, `late_filing`, `sub_dollar`), never display text: the page translates (`risk.*` keys). The alert passes no price series, so only the filing-based markers can appear. Information only: no marker filters an alert.

## Tests

```bash
DATA_DIR=/tmp/screener_test PYTHONPATH=backend python -m pytest backend/tests/
```

Deterministic, offline. The module honors `DATA_DIR` so it imports outside the container.
