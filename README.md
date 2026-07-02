# SmallCaps Screener

A Dockerized dashboard that discovers and ranks US small-cap stocks. The goal is
to surface promising names **early** — quiet accumulation and tight bases, *before*
the move — rather than stocks that have already run.

It is a decision-support tool: it discovers, scores, and ranks. It does not trade.
The final call stays human. The interface is in French; this documentation is in
English.

## How it works

The scan is a **two-pass funnel** driven by **scoring, not strict elimination**.

```
NASDAQ + NYSE + AMEX (NASDAQ screener API)  →  dedupe  →  full universe (~2–3k)
    (Small + Micro cap · identical every scan · shuffle only sets download order)
    │
    ▼  Pass A  (analyze_prices) — batch yf.download, no per-ticker cost
    │     minimal hard filters:  price 2–25 · 1-month perf · liquidity ≥ $1M ·
    │                            falling-knife guard (MA50 slope ≥ 0)
    │     technical signals:     accumulation (OBV) · compression (ATR) ·
    │                            near recent-base pivot · low extension · RS turning
    │
    ▼  rank survivors by technical score (accumulation weighted highest)
    │     → keep the top ~150 (bounds the expensive .info calls)
    │
    ▼  Pass B  (enrich_ticker) — yfinance .info on the top-scored names only
    │     hard filters:  market cap 50M–2B · exchange
    │     fundamentals:  insider · cash/debt · revenue growth · float · short interest
    │
    ▼  0–10 score (see scoring modes)  →  sorted list  →  data/screener_data.json
```

**Why scoring instead of hard filters?** Requiring "already strong" signals (high
relative strength, near the 52-week high) selects stocks that have *already moved* —
you arrive after the party. Keeping the hard filters minimal and letting the **score**
rank means early setups aren't eliminated; the accumulation-led score floats the best
candidates to the top.

## Scoring model

The scoring approach is **not settled** — it is a config flag (`FILTERS["scoring_mode"]`),
to be decided by a larger backtest:

- **`binary` (default)** — the original additive "checkbox" score. Known and conservative,
  but caps around 8 (some signals are near-unreachable).
- **`continuous`** — each signal is a continuous factor, percentile-ranked across the
  candidates, combined and shown as a **decile 0–10** ("how good among today's candidates").
  Fixes the scale; edge not yet validated.

Both modes use the same weights below (`FILTERS["score_weights"]`, tunable).

**Technical factors** (computed in Pass A; also used to rank which survivors get enriched):

| Factor | Weight | Meaning |
| --- | ---: | --- |
| Accumulation (Chaikin Money Flow + up/down volume) | **4** | Money quietly coming in — the strongest pre-move tell |
| Compression (ATR20/ATR90 self-percentile) | 2 | Volatility contracting *relative to the stock's own history* |
| Near recent-base pivot | 2 | Close to breaking out of its recent base |
| Low extension (near MA50) | 2 | Still early in the move, not 40% extended |
| Relative-strength magnitude | 2 | Outperforming the market |
| Price above MA50 | — | (kept as a signal for display) |

**Fundamental factors** (added in Pass B, on the top-scored names):

| Factor | Weight |
| --- | ---: |
| Insider ownership | 2 |
| Cash > debt | 1 |
| Revenue growth | 1 |
| Low float | 1 |
| High short interest (squeeze) | 1 |

Accumulation (4) is the top signal. **Sensors v2** (Sprint 4) reworked the two pillars
without changing any weight: **compression** is now the self-percentile of ATR20/ATR90
against the stock's *own* 252-day history (v1's raw `< 0.70` threshold fired on ~0.8 % of
names — effectively dead), and **accumulation** is Chaikin Money Flow + the up/down volume
ratio (more robust than v1's binary OBV on gappy names). The v1 sensors stay switchable via
`FILTERS["sensors_version"]` for the Sprint 6 backtest. Weight calibration is Sprint 8.

See [docs/backend.md](docs/backend.md) for the exact factors and functions.

## Validation & monitoring

- **Backtest** (`backend/backtest.py`): replays the scan at a past date and compares
  forward returns of selected names vs the universe vs IWM, bucketed by score quartile,
  and shows the continuous vs the old binary score side by side. **So far inconclusive**:
  at ~14 survivors per run the numbers swing between runs (edge seen from +7% to −32%),
  so it cannot yet confirm an edge or that continuous beats binary. A meaningful verdict
  needs a much larger, rolling multi-period backtest. Caveats: survivorship bias,
  price/volume signals only (no point-in-time fundamentals).
- **Live performance tracking**: every scan writes a dated snapshot of its picks to
  `data/history/` (ticker, entry price, score, key signals). `GET /api/performance` then
  measures each pick's return **since it was first flagged** and compares it to IWM — an
  unbiased, real-time read of whether the screener works. It is **robust by design**: a
  delisted or missing ticker, a market-data outage, or a corrupt snapshot never breaks the
  report — the endpoint always returns a well-formed payload (with a `message` on failure).
- **Automatic scans**: the backend re-scans every `SCAN_EVERY_HOURS` (default 24), **only on
  trading days** (Mon–Fri, weekends skipped — `SCAN_TRADING_DAYS_ONLY`, default on), so the
  snapshot history builds up on its own, roughly one snapshot per trading day.
- **Retention**: snapshots are tiny JSON files (a few KB each) — the policy is **keep
  everything**; a longer history only makes the tracker more meaningful.

```bash
# Backtest (offline analysis)
docker compose exec backend python backtest.py --n 200 --forward 63 --seed 42

# Performance of past selections
curl http://localhost:8000/api/performance
```

## Things to know

- **Setup vs trigger.** `setup_score` (alias of `score`) says *"the spring is coiled"* —
  a watchlist candidate. `triggered` says *"the breakout is happening now"* (close above the
  recent pivot **and** a volume surge). Every candidate carries both plus `days_since_trigger`.
  A **Telegram alert** pings newly triggered names (`setup_score ≥ alert_min_score`,
  deduped); set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` to enable — absent, it's silently off.
- **Yahoo rate-limits `.info` hard.** Hitting it with many parallel requests bans the
  IP (`YFRateLimitError`). Pass B therefore uses a small thread pool (2) + backoff, and
  only enriches the top ~150 survivors. This is by design — do not raise `enrich_workers`.
- **`GET /api/scan` is non-blocking.** It returns the current cache immediately (or an
  empty `scanning: true` payload on a cold start) and scans in the background. Poll
  `GET /api/scan/status` for `phase`/`progress`. No multi-minute freeze on first load.
- A scan sweeps the **entire eligible universe** (~2,000–3,000 tickers across NASDAQ,
  NYSE and AMEX, identical from one scan to the next — no random sampling), takes
  ~5–10 minutes, and caches results for 30 minutes. Pass A downloads price/volume in
  batches (free); only the top ~150 survivors reach the costly `.info` calls.
- Market data comes from public endpoints and `yfinance`; field quality varies by
  ticker (small caps especially). The reliable signals are price/volume based.
- **Do not modify `frontend/smallcap-screener.jsx`** — it is the canonical UI.
- This is a screening tool, **not financial advice**.

## Stack

- Backend: Python 3.11, FastAPI, yfinance, pandas, requests
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
docker compose exec backend python backtest.py --n 200     # backtest
docker compose logs -f backend                             # follow logs
docker compose down                                        # stop
docker compose down -v                                     # stop + wipe cache/history

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
| `SCAN_TRADING_DAYS_ONLY` | Backend | No (default `true`) | Skip weekend auto-scans (market closed → redundant snapshots). |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Backend | No | Enable breakout alerts. Absent → alerting silently disabled. |
| `DATA_DIR` | Backend | No (default `/app/data`) | Where the cache and history are written (used by tests). |

## API endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/scan` | GET | Ranked results (non-blocking; triggers a background scan if stale). |
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
├── backtest.py           # offline forward-return validation
├── track.py              # live performance tracking of past selections
└── tests/                # offline deterministic unit tests
frontend/
├── smallcap-screener.jsx # canonical dashboard (do not modify)
└── src/main.jsx
docs/                     # architecture, backend, api, frontend, deployment
```

## Documentation

- [Architecture](docs/architecture.md)
- [Backend screener & scoring](docs/backend.md)
- [API reference](docs/api.md)
- [Frontend](docs/frontend.md)
- [Deployment and operations](docs/deployment.md)

## Security note

The per-stock Claude analysis currently calls the Anthropic API **directly from the
browser**, which exposes the API key to browser code. This is convenient for local use
only. For production, proxy AI requests through the backend.
