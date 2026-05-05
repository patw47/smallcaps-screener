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

Responsibilities:

- Discover candidate tickers dynamically.
- Fetch ticker metadata and price history.
- Apply hard filters.
- Compute setup metrics and scores.
- Write scan results to `/app/data/screener_data.json`.

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

`GET /api/scan` uses an `asyncio.Lock` so only one scan runs for concurrent cache misses. Requests that arrive while the first scan is running wait for the lock and then read the cache produced by the first request.

`POST /api/scan/force` starts a scan in a background executor and returns immediately. It rejects requests with HTTP 409 if the scanner state already indicates a scan is active.

## Configuration Sources

Most screener behavior is configured in the `FILTERS` dictionary in `backend/screener_backend.py`. Deployment configuration is in `docker-compose.yml`.

## Known Design Tradeoffs

- The custom watchlist is stored in backend memory, so it resets when the backend container restarts.
- The frontend recomputes a local score from normalized fields even though the backend also returns `score`, `positives`, and `flags`.
- Claude analysis is called directly from the browser. This should be moved behind the backend before production use.
