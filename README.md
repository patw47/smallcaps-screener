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
  and a per-stock risk dossier.
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
    │     (bounds the expensive .info calls)
    │
    ▼  Pass B  (enrich_ticker) — yfinance .info on the top-scored names only
    │     hard filters:  market cap 50M–2B · exchange
    │     fundamentals:  insider · cash/debt · revenue growth · float · short interest
    │
    ▼  ranked list  →  data/screener_data.json
```

**Why scoring instead of hard filters?** Requiring "already strong" signals (high relative
strength, near the 52-week high) selects stocks that have *already moved* — you arrive
after the party. Keeping the hard filters minimal and letting the score rank means early
setups aren't eliminated. See [docs/backend.md](docs/backend.md) for the exact factors,
weights and functions.

## The forward experiments (washout cohorts)

The one pattern worth watching: cheap (≤ $8), beaten-down stocks with no pending EDGAR
dilution, falling **together with a falling market** — historically they mean-reverted
(a small positive quarterly return, but statistically unproven). The historical data is
exhausted, so the only honest judge left is the future. Two variants run in parallel:

- a **21-day-window** cohort (`backend/v4.py`), and
- a **multi-window** set — 7/14/21 trading days, switchable from the dashboard header
  (`backend/v5.py`) — with tighter filters (deeper fall ≥ 15 %, quiet volume, money-flow
  floor) and a display-only ⚡ flash-crash flag.

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
- **Automatic scans**: the backend re-scans every `SCAN_EVERY_HOURS` (default 24), **only
  on trading days** (`SCAN_TRADING_DAYS_ONLY`, default on), so the snapshot history builds
  up on its own.
- **Retention**: snapshots are tiny JSON files (a few KB each) — the policy is **keep
  everything**; a longer history only makes the tracker more meaningful.
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
- The dashboard header carries the **7/14/21 d market switch** (+ ⚡ flash-crash badge when
  IWM ≤ −8 % over 3 sessions), which drives the washout section; the extreme-zone profiles
  sit below with their two-sided stats. Every label has a tooltip mirrored in
  [docs/glossaire.md](docs/glossaire.md).
- This is a screening tool, **not financial advice**.

## Stack

- Backend: Python 3.11, FastAPI, yfinance, pandas, numpy (numpy-only models — no ML framework)
- Frontend: React 18, Vite 5
- Runtime: Docker Compose; scan cache and history on a Docker volume at `/app/data`

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
docker compose down -v                                     # stop + wipe cache/history
curl http://localhost:8000/api/performance                 # performance of past selections

# Tests (offline, deterministic, no network)
DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/
```

## Configuration

Screener thresholds and weights live in the `FILTERS` dict at the top of
`backend/screener_backend.py` (no magic numbers in the logic).

| Variable | Used by | Required | Description |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | Frontend (`VITE_ANTHROPIC_API_KEY`) | Only for AI analysis | Key for the browser-side Claude analysis button. |
| `SCAN_EVERY_HOURS` | Backend | No (default 24) | Interval between automatic background scans. |
| `SCAN_TRADING_DAYS_ONLY` | Backend | No (default `true`) | Skip weekend auto-scans. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Backend | No | Enable cohort alerts. Absent → alerting silently disabled. |
| `EDGAR_USER_AGENT` | Backend | No | SEC-compliant identifying UA (name + email) for filings data. Absent → EDGAR disabled (neutral). |
| `DATA_DIR` | Backend | No (default `/app/data`) | Where the cache and history are written (used by tests). |

## API endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/scan` | GET | Ranked results + washout cohorts (non-blocking; triggers a background scan if stale). |
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
├── alerts.py             # Telegram alerts (cohort entries, persistent dedup)
├── edgar.py              # SEC/EDGAR point-in-time survival signals (dilution, runway…)
├── profiles.py           # Fusée/Phénix detectors
├── backtest.py           # backtest harness + quick checks
├── track.py              # live performance tracking of past selections
└── tests/                # offline deterministic unit tests
frontend/
├── smallcap-screener.jsx # dashboard UI (washout cohorts, tracking, extreme zones, tooltips)
└── src/main.jsx
docs/                     # architecture, backend, api, frontend, glossary, methodology
```

## Documentation

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

