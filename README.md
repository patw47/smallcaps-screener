# SmallCaps Screener

A Dockerized dashboard that discovers and tracks US small-cap stocks. It scans the
full eligible universe (~2,500 names across NASDAQ, NYSE and AMEX) every trading day
and surfaces candidates as a **research / watchlist tool**: it displays measured
historical frequencies with their two-sided risks and runs live forward-validation
experiments. It does **not** claim a trading edge and it does **not** trade — the final
call stays human. The interface is in French; this documentation is in English.

## What it is today

A research dashboard, deliberately not an advice engine. On free, survivor-only market
data no score was shown to beat a plain index ETF at predicting which micro-caps double,
so **no number is presented as an edge** — the dashboard shows descriptive historical
frequencies, each next to its own statistical weakness. What it surfaces:

- **The washout cohorts of the day** — cheap, beaten-down stocks falling *with* a falling
  market and free of pending share dilution: the one historically positive pattern the
  research isolated. Shown with their measured stats *and* their statistical weakness side
  by side (in-sample, unproven → judged only on future data).
- **A cohort tracker** — every past qualifying name followed forward vs IWM, with
  probability checkpoints (information, never an automatic sell rule).
- **Extreme-zone watchlists** — the 🚀 **Fusée** / 🔥 **Phénix** profiles, labelled
  *research-only*, each with its two-sided measured stats (explosion lift *and* crash lift)
  and a per-stock risk dossier: each distress marker is shown individually (code, backend-set
  severity level, date of the underlying fact when already available at zero network cost),
  the high-severity ones as a dedicated alert band above the badges. A header counter says
  how many displayed names carry at least one marker, and a client-side sort groups them —
  reordering only, nothing is ever hidden and no sort/filter parameter enters the API.
- **Context flags on every extreme-zone name** — descriptive facts read from the *same*
  requests the scan already makes, at zero extra network cost: insider and institutional net
  transactions, short float and days-to-cover, options/borrow availability, earnings and
  revenue surprises, the most recent 8-K (the SEC's material-event form, typed by its event
  codes) and the latest headline. Values are shown **raw and unqualified** — no "high short
  interest" verdict, because no threshold for these fields exists or is served. A missing flag
  displays nothing, never an error state. Two native selects sort and filter on them, purely
  client-side; the served list, its order and its scores are untouched — an invariant enforced
  by test, not by convention. The one exception is the cash/debt reconstruction, which restores
  a scoring criterion the Yahoo path already served (see `docs/backend.md`).
- Every displayed term has a tooltip and a glossary entry with its measured number and
  source.

The internal 0–10 score is used **only** to rank which Pass A survivors get the expensive
Pass B `.info` calls; it is not displayed and not presented as a signal. `p_explode`
(a probability-of-doubling score) is intentionally left `null` — it did not validate on
free data.

## How it works

The scan is a **two-pass funnel** driven by **scoring, not strict elimination**.

```
NASDAQ + NYSE + AMEX (NASDAQ screener API)  →  dedupe  →  full universe (~2–3k)
    (Small + Micro cap · identical every scan · shuffle only sets download order)
    │
    ▼  Pass A  (analyze_prices) — batch yf.download, no per-ticker cost
    │     minimal hard filters:  price 2–25 · 1-month perf · liquidity ≥ $1M ·
    │                            falling-knife guard (MA50 slope ≥ 0)
    │     technical signals:     accumulation (CMF) · compression (ATR) ·
    │                            near recent-base pivot · low extension · RS turning
    │
    ▼  rank survivors by technical score  →  keep the top ~150
    │     (bounds the expensive .info calls — lifted on the snapshot path below)
    │
    ▼  Pass B  (enrich_ticker) — yfinance .info on the top-scored names only
    │     hard filters:  market cap 50M–2B · exchange
    │     fundamentals:  insider · cash/debt · revenue growth · float · short interest
    │
    ▼  ranked list  →  data/screener_data.json
```

**Optional fundamentals source.** Pass B costs one `.info` call per name, and Yahoo bans the
IP if hammered — hence the cap, which drops the names past it unexamined. With a Finviz Elite
account, `enrich_source: finviz` in the private config overlay swaps those per-ticker calls for
**one** CSV export covering the whole universe, and the cap becomes a valve you can lift: every
name above the cutoff gets examined. It is optional by construction — no account, no config: the
clone you just checked out runs the Yahoo path exactly as before, and an unreachable export falls
back to it mid-scan. Details in [docs/backend.md](docs/backend.md).

**Why scoring instead of hard filters?** Requiring "already strong" signals (high relative
strength, near the 52-week high) selects stocks that have *already moved* — you arrive
after the party. Keeping the hard filters minimal and letting the score rank means early
setups aren't eliminated. See [docs/backend.md](docs/backend.md) for the exact factors,
weights and functions.

## The forward experiments (washout cohorts)

The one pattern worth watching: cheap, beaten-down stocks with no pending EDGAR
dilution, falling **together with a falling market** — historically they mean-reverted
(a small positive quarterly return, but statistically unproven). The historical data is
exhausted, so the only honest judge left is the future. Two variants run in parallel:

- a **21-day-window** cohort (`backend/v4.py`), and
- a **multi-window** set — 7/14/21 trading days, switchable from the dashboard header
  (`backend/v5.py`) — with tighter filters (deeper fall, quiet volume, money-flow floor)
  and a display-only ⚡ flash-crash flag. The frozen rule values live in the private
  config overlay, not in the code.

Every daily scan records the day's qualifying cohort into a dated snapshot. On
rising-market days the method doesn't apply and the dashboard says so, showing a **pre-list**
of what *would* qualify. **Telegram alerts** fire on genuinely new cohort entries
(disclaimer embedded, deduped per ticker). Judgment happens later, on the accumulated
forward record — never on the in-sample numbers.

## Validation & monitoring

- **Live performance tracking**: every scan writes a dated snapshot of its picks to
  `data/history/`; `GET /api/performance` measures each pick's return **since it was first
  flagged** and compares it to IWM. Robust by design — a delisted ticker, a data outage or
  a corrupt snapshot never breaks the report (it always returns a well-formed payload).
- **Leak-proof cohorts**: a tracked name is followed to its horizon even once it leaves the
  discovered universe — prices missing from the day's scan are backfilled before any
  lifecycle computation. This matters in both directions: doubling in value pushes a name
  past the market-cap ceiling, so *the success condition used to be the ejection condition*,
  while a collapse drops it under the price floor. "No data" now means one thing only: the
  stock genuinely does not quote. `make check-cohort` is the guard.
- **Snapshots keep the evidence**: each dated snapshot archives the five distress markers
  and the dollar volume alongside every pick, so a past day's state can be reconstructed
  instead of recomputed. `make check-snapshot-keys` guards against a key being dropped.
- **Tracked rows carry today's risk**: every tracking row shows two risk files side by
  side — the markers frozen on entry day, and the **current** ones recomputed at each
  build. Price flags (sub-floor streak with its length, recent reverse split) are read
  from prices already in hand — zero extra network; filing facts (going-concern doubt,
  late filing, share issuance in preparation) are swept from EDGAR **at most once per
  calendar day per ticker**, with a dated memo persisted in the data directory so a
  container restart never re-pays the sweep. Information only: no marker closes an
  observation window or triggers anything. EDGAR silent or failing → price flags still
  served, and the scan always completes.
- **Automatic scans**: the backend re-scans every `SCAN_EVERY_HOURS` (default 24), **only
  on trading days** (`SCAN_TRADING_DAYS_ONLY`, default on), so the snapshot history builds
  up on its own.
- **Retention**: snapshots are tiny JSON files (a few KB each) — the policy is **keep
  everything**; a longer history only makes the tracker more meaningful.
- **Snapshots survive the volume**: after every scan, each dated snapshot is copied to a host
  mount (`./backups`, gitignored) — incrementally, never overwriting a name already there, and
  never able to fail a scan. Without it a single `docker compose down -v` would erase the whole
  history, and nothing can reconstruct after the fact which markers were raised on a past date.
  `make check-backup` guards completeness *and* non-regression: it keeps a SHA-256 manifest at
  the destination, because the directory is unversioned and a repo diff over it would be empty
  by construction — incapable of ever turning red.
- **Finished results are frozen, not recomputed**: once a tracked row reaches the end of its
  observation window, it is written once to an external table and never touched again. Prices
  are rewritten retroactively by the provider on corporate actions (reverse splits, delistings,
  mergers) — exactly what distressed small caps go through — so a return recomputed months later
  is not the one that was observed. Markers and profile are read from the **entry** snapshot,
  never from the current scan. Deduplication queries the table itself rather than any local
  state, so losing the volume cannot cause a duplicate re-export. Missing secret, unreachable
  service or quota: the export disables itself silently and the scan still completes.
- **Survivorship ceiling**: free data only contains companies that still exist, which
  flatters distressed-stock strategies. Every displayed number is an **optimistic ceiling**
  and every crash frequency a **floor**. These are descriptive historical frequencies, not
  advice.

## Things to know

- **Setup vs trigger.** `setup_score` says *"the spring is coiled"* (a watchlist candidate);
  `triggered` says *"the breakout is happening now"* (close above the recent pivot **and** a
  volume surge). Every candidate carries both plus `days_since_trigger`.
- **Yahoo rate-limits `.info` hard.** Hitting it with many parallel requests bans the IP.
  Pass B uses a small thread pool (2) + backoff and only enriches the top ~150 survivors.
  The cost lever is *fewer survivors*, never more concurrency — do not raise `enrich_workers`.
- **`GET /api/scan` is non-blocking.** It returns the current cache immediately (or an empty
  `scanning: true` payload on a cold start) and scans in the background. Poll
  `GET /api/scan/status` for `phase`/`progress`.
- A scan sweeps the **entire eligible universe** (identical from one scan to the next — no
  random sampling), takes ~5–10 minutes, and caches for 30 minutes.
- The dashboard header carries the **7/14/21 d market switch** (+ ⚡ flash-crash badge on
  extreme IWM drops), which drives the washout section; the extreme-zone profiles
  sit below with their two-sided stats. Every label has a tooltip mirrored in
  [docs/glossaire.md](docs/glossaire.md).
- This is a screening tool, **not financial advice**.

## Stack

- Backend: Python 3.11, FastAPI, yfinance, pandas, numpy (numpy-only models — no ML framework)
- Frontend: React 18, Vite 5
- Runtime: Docker Compose; scan cache and history on a Docker volume at `/app/data`, doubled
  onto a host mount at `/app/backup` (`./backups`) so the history outlives the volume

## Quick start

Prerequisite: Docker Desktop or Docker Engine with Compose.

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY in .env only if you want the per-stock Claude analysis button.
docker compose up --build
```

Services:

- Frontend: http://localhost:5173
- API scan: http://localhost:8000/api/scan
- Performance: http://localhost:8000/api/performance
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/health

## Commands

```bash
docker compose up --build                                  # start everything
curl -X POST http://localhost:8000/api/scan/force          # force a fresh scan
docker compose exec backend python screener_backend.py     # run a scan directly
docker compose exec backend python backtest.py --n 200     # quick backtest
docker compose logs -f backend                             # follow logs
docker compose down                                        # stop
docker compose down -v                                     # stop + wipe cache/history (the
                                                           # snapshot copies in ./backups survive)
curl http://localhost:8000/api/performance                 # performance of past selections

# Tests (offline, deterministic, no network)
DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/
```

### Verification targets

Every gate is a `make` target; `make test` is the offline suite.

| Target | Guards against |
| --- | --- |
| `make test` | Regressions in the offline deterministic suite. |
| `make check-edge` | Any frozen v4/v5 value or private-protocol reference reaching the repo. |
| `make check-thresholds` | A threshold key or value reaching the browser. |
| `make check-jargon` | Version numbers, internal vocabulary or protocol references reaching the screen. |
| `make i18n-parity` / `make check-i18n` | Missing translations; hard-coded UI strings in the JSX. |
| `make check-criteria-coverage` | A rule or scoring key absent from the public criteria index. |
| `make build-frontend` | JSX that no longer compiles (containerised `vite build`). |
| `make test-frontend` | A broken flag sort or filter — the ordering of missing values, and the predicates behind the two selects (`node --test`, no dependency to install). Covers the logic, not the rendering. |
| `make check-runtime` | Python that compiles on the dev interpreter but not on the production 3.11 container. |
| `make check-cohort` | A tracked stock still quoting but read as "no data" — replays the tracking on the live history from an *empty* universe (needs the running container and network). |
| `make check-snapshot-keys` | A selection key silently dropped or renamed in the dated snapshots — the history is read years later and never rewritten (needs the running container). |
| `make check-backup` | A snapshot without its copy outside the volume, or a copy that vanished or was rewritten since the previous pass (needs the running container — only it sees both the volume and the host mount). |
| `make check-secrets` | A secret value reaching a versioned file, or `.env.example` missing an export variable name — or carrying its value. Never prints what it finds: file, line and variable *name* only. |
| `make docs-build` | A broken public documentation build (strict MkDocs). |

`make flag-prevalence` is not a gate but a report: prevalence of the five distress markers,
with the two denominators kept apart (price-derived markers over the whole universe,
filing-derived markers over the funnel survivors) and a per-sector breakdown with
biotechnology separated out. Descriptive only — no marker enters selection, ranking or score.

`make proof-export` is not a gate either: it replays in the container the tests the host skips
(FastAPI is not installed there, so they are silently *skipped* — and a skipped test proves
nothing), then exercises the real network path end to end. It **writes a dummy-symbol row into
the live table and archives it** — do not run it in a loop, and never mistake it for a gate.

## Configuration

Screener thresholds live in the `FILTERS` dict at the top of
`backend/screener_backend.py` (no magic numbers in the logic). The **edge values**
(v4/v5 frozen rule constants, scoring weights, display stats) are **not versioned**:
the code ships neutral defaults, and the real values load at startup from
`config/local.yml` (gitignored — see `config/local.example.yml`). Set
`REQUIRE_LOCAL_CONFIG=1` in production so a scan refuses to start without it.
`make check-edge` gates the repo against value leaks.

### Rule thresholds are never served

The scan response carries **no rule threshold at any depth** — not as a mode, as the only
behaviour. The price cap, fall thresholds, money-flow floor, volume multiple, checkpoint
threshold and reference window are simply never built, so no flag can serve them by
mistake. A masking you have to remember to switch on is a masking you forget: the screen
is already up when the thought occurs.

Still served: expectancy, median, probabilities, robustness test, case counts, each rule's
existence, meaning and state of the day, and the **observation schedule**
(`checkpoint.day`, `horizon`) — a measurement protocol, not a selection criterion; knowing
it reconstructs no list. The values themselves live in the private reference page that
`docs/criteria-index.md` points to.

Glossary texts must be written without their figure. A runtime net blanks — and names —
any text still quoting a loaded value, so a badly reread sentence costs an explanation
rather than the edge. `make check-thresholds` gates both the keys and the served texts.

Documented residual leak: qualifying stocks keep their own values on screen, so the worst
qualifying name **bounds** the price cap from below. A bound is not the value, and removing
it would mean showing nothing at all.

| Variable | Used by | Required | Description |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | Frontend (`VITE_ANTHROPIC_API_KEY`) | Only for AI analysis | Key for the browser-side Claude analysis button. |
| `SCAN_EVERY_HOURS` | Backend | No (default 24) | Interval between automatic background scans. |
| `SCAN_TRADING_DAYS_ONLY` | Backend | No (default `true`) | Skip weekend auto-scans. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Backend | No | Enable cohort alerts. Absent → alerting silently disabled. |
| `EDGAR_USER_AGENT` | Backend | No | SEC-compliant identifying UA (name + email) for filings data. Absent → EDGAR disabled (neutral). |
| `NOTION_API_KEY` / `NOTION_RESULTS_DB_ID` | Backend | No | Enable the export of finished tracked rows. Absent → export silently disabled, the scan is unaffected. |
| `DATA_DIR` | Backend | No (default `/app/data`) | Where the cache and history are written (used by tests). |
| `BACKUP_DIR` | Backend | No (default `/app/backup`) | Where the snapshot copies are written — override to aim a throwaway destination when verifying. |

## API endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/scan` | GET | Ranked results + washout cohorts (non-blocking; triggers a background scan if stale). Never carries rule thresholds. |
| `/api/scan/status` | GET | `scanning` / `phase` / `progress`. |
| `/api/scan/force` | POST | Force a fresh background scan. |
| `/api/performance` | GET | Return of past selections since first flagged, vs IWM. |
| `/api/stock/{ticker}` | GET | One ticker from the latest result. |
| `/api/watchlist` | GET/POST/DELETE | Read / set / clear a custom watchlist (POST overrides discovery). |
| `/api/health` | GET | Health check. |

## Project structure

```
backend/
├── screener_backend.py   # discovery, two-pass funnel, scoring, snapshots
├── api.py                # FastAPI app (non-blocking scan, daily scheduler, endpoints)
├── v4.py                 # 21-day washout cohort, pre-list, tracking
├── v5.py                 # multi-window (7/14/21 d) washout cohorts
├── lifecycle.py          # observation schedule shared by both families + current risk file
├── alerts.py             # Telegram alerts (cohort entries, persistent dedup)
├── edgar.py              # SEC/EDGAR point-in-time survival signals (dilution, runway, 8-K catalysts)
├── finviz.py             # optional Pass B source: one CSV export for the whole universe (local config only)
├── profiles.py           # Fusée/Phénix detectors
├── backtest.py           # quick control backtest (--n/--forward/--seed/--period)
├── track.py              # live performance tracking + snapshot copy outside the volume
├── notion_export.py      # writes finished tracked rows to the external table, once and for all
└── tests/                # offline deterministic unit tests
frontend/
├── smallcap-screener.jsx # dashboard UI (washout cohorts, tracking, extreme zones, tooltips)
├── flags.js              # context-flag sort/filter tables — no React, so a test can exercise them
├── flags.test.js         # `node --test` lock on that logic (make test-frontend)
└── src/main.jsx
docs/                     # architecture, backend, api, frontend, glossary, methodology
backups/                  # host-side copies of the dated snapshots (gitignored, never rewritten)
```

## Documentation

Published as a browsable site: https://patw47.github.io/smallcaps-screener/

- [Architecture](docs/architecture.md)
- [Backend screener & scoring](docs/backend.md)
- [API reference](docs/api.md)
- [Frontend](docs/frontend.md)
- [Deployment and operations](docs/deployment.md)
- [Glossary — every displayed metric, its tooltip and its source](docs/glossaire.md)
- [Interface reading guide — what you see, tier by tier](docs/guide_interface.md)

## Security note

The per-stock Claude analysis currently calls the Anthropic API **directly from the
browser**, which exposes the API key to browser code. This is convenient for local use
only. For production, proxy AI requests through the backend.

## License

All rights reserved. See [LICENSE](LICENSE) — the source is public for portfolio and
evaluation only; no reuse or redistribution is granted.
```

