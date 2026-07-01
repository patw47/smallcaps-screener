# Architecture

## Overview

SmallCaps Screener is split into two containers:

- `backend`: FastAPI application and stock scanning engine.
- `frontend`: React/Vite single-page application.

Docker Compose starts both services and creates a persistent `data` volume used by the backend cache.

```text
Browser
  |
  | GET /api/scan, /api/scan/force
  v
Frontend container :5173
  |
  | Vite dev proxy/runtime fetches /api/*
  v
Backend container :8000
  |
  | NASDAQ API, Finviz, yfinance
  v
External market data sources
```

## Repository Layout

```text
.
├── backend/
│   ├── api.py
│   ├── screener_backend.py
│   ├── backtest.py            # forward-return validation harness
│   ├── tests/                 # offline unit tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/main.jsx
│   ├── smallcap-screener.jsx
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── docs/
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Runtime Components

### Backend API

File: `backend/api.py`

Responsibilities:

- Expose the HTTP API under `/api/*`.
- Serve cached scan results when valid.
- Start scans in the background for force-scan requests.
- Serialize scan status for polling.
- Manage an in-memory custom watchlist.

### Screener Engine

File: `backend/screener_backend.py`

A **two-pass funnel** (see `docs/backend.md` for detail):

- Discover tickers dynamically and take a per-scan random sample (`max_tickers`, reshuffled each scan).
- **Pass A** (`analyze_prices`): batch-download OHLCV (`yf.download`) and apply **minimal** price/volume hard filters (price 2–25, 1-month perf, liquidity, and a falling-knife guard = MA50 slope ≥ 0). Compute technical signals (accumulation/OBV, ATR compression, near recent-base pivot, low extension, RS turning). RS and price>MA50 are **scoring**, not hard filters — so early setups aren't eliminated.
- Rank survivors by a technical score (`_price_score`, **accumulation weighted highest**) and keep the top `enrich_max` — this decides which names get the expensive `.info` call.
- **Pass B** (`enrich_ticker`): `.info` on the top-scored survivors only (small thread pool + backoff — Yahoo rate-limits `.info`), apply market-cap/exchange filters, add fundamentals, compute the normalized 0–10 score.
- Write results to `/app/data/screener_data.json`, sorted by `(score, rs_strength)`.

`backend/backtest.py` is a separate offline harness that replays `analyze_prices` at a past as-of date and measures forward returns of survivors vs the universe (validates the price/volume signals; not wired into the live API).

### Frontend App

Files:

- `frontend/src/main.jsx`
- `frontend/smallcap-screener.jsx`

Responsibilities:

- Fetch scan results from the backend.
- Normalize backend snake_case fields into frontend camelCase fields.
- Score and filter stocks in the UI.
- Render stock cards, scan statistics, filters, and optional Claude analysis.

## Data Persistence

The backend writes cache data to:

```text
/app/data/screener_data.json
```

In Docker Compose this path is backed by the named volume:

```yaml
volumes:
  data:
```

The cache is valid for `FILTERS["cache_minutes"]`, currently 30 minutes.

## Concurrency Model

Scans **never block a request**. `GET /api/scan` is non-blocking (stale-while-revalidate): it returns a fresh cache immediately, or a stale result while kicking a background refresh, or an empty `{"stocks": [], "scanning": true}` payload on a cold start — then a background scan runs. A FastAPI startup hook warms the cache if none exists.

A single background scan runs at a time, guarded by an in-flight flag (`_bg_scan_inflight`) whose check-and-set is atomic on the single-threaded event loop, plus `scan_state["scanning"]`. `POST /api/scan/force` clears the cache and starts a background scan, returning `409` if one is already running. Clients poll `GET /api/scan/status` for `phase`/`progress`.

## Configuration Sources

Most screener behavior is configured in the `FILTERS` dictionary in `backend/screener_backend.py`. Deployment configuration is in `docker-compose.yml`.

## Known Design Tradeoffs

- The custom watchlist is stored in backend memory, so it resets when the backend container restarts.
- The frontend recomputes a local score from normalized fields even though the backend also returns `score`, `positives`, and `flags`.
- Claude analysis is called directly from the browser. This should be moved behind the backend before production use.
