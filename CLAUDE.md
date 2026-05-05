# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Full launch (builds images and starts all services)
docker-compose up --build

# Trigger a manual scan
docker-compose exec backend python screener_backend.py

# Stream backend logs
docker-compose logs -f backend
```

- Frontend: http://localhost:5173
- API: http://localhost:8001/api/scan
- Force a new scan: `POST http://localhost:8001/api/scan/force`
- API docs: http://localhost:8001/docs

## Architecture

**SmallCaps Screener** is a US small-cap stock screener with two layers, orchestrated via Docker Compose.

**Backend** (`backend/screener_backend.py` + `backend/api.py`)
- `screener_backend.py` is the core: discovers tickers dynamically (see below), fetches data via `yfinance`, applies all filters from the `FILTERS` dict, computes a score (0–10), and writes results to `screener_data.json`. All tunable thresholds live in `FILTERS`. The `scan_state` dict is a shared in-process object used by `api.py` to stream progress.
- `api.py` wraps the backend as a FastAPI app. All endpoints are prefixed `/api/*`. CORS is open on `*` for development. Runs scans in a thread executor to avoid blocking the event loop. A `DELETE /api/watchlist` endpoint reverts back to dynamic discovery.

**Ticker discovery** (dynamic — no static list)
- Tickers are fetched fresh each scan from two sources:
  - NASDAQ API: `https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange=nasdaq`
  - Finviz scraping: `https://finviz.com/screener.ashx` via `requests` + `BeautifulSoup` (selector: `a.screener-link-primary`)
- The combined list is deduplicated, `random.shuffle()` applied, then capped at 300 tickers (`FILTERS["max_tickers"]`).
- There is no static ticker list. Do not reintroduce one.
- `POST /api/watchlist` overrides dynamic discovery for the session; `DELETE /api/watchlist` reverts to dynamic.

**Frontend** (`frontend/smallcap-screener.jsx`)
- Do not modify this component. It is the canonical UI and is imported as-is by `frontend/src/main.jsx`.
- Currently uses hardcoded `MOCK_STOCKS` — not yet wired to the FastAPI backend.
- Has its own `scoreStock()` function that duplicates scoring logic from `_compute_score()` in the backend. If scoring criteria change, both must be updated.
- Calls `https://api.anthropic.com/v1/messages` directly from the browser for per-stock Claude analysis (temporary dev setup — see Security note below).

**Data flow (current state)**
```
NASDAQ API + Finviz → deduplicate → random.shuffle → [:300]
    → yfinance → analyze_ticker() → screener_data.json
                                          ↕
                                  FastAPI /api/scan
                                  (not yet consumed by JSX)
```

## Key design notes

- A full scan (up to 300 tickers) takes several minutes due to the 0.3s rate limit per ticker (`FILTERS["rate_limit_s"]`).
- `catalyst_type` and `catalyst_date` fields are always `null` from the backend — reserved for manual enrichment via the dashboard.
- The JSX uses `claude-sonnet-4-20250514` model ID — update this when migrating to newer Claude versions.

## Security note

Claude API calls are made directly from the browser in the current JSX. This is a temporary development shortcut. In production, proxy all Anthropic API calls through the FastAPI backend to avoid exposing the API key client-side.
