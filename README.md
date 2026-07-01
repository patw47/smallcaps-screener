# SmallCaps Screener

SmallCaps Screener is a Dockerized dashboard for discovering and ranking US small-cap stocks. It discovers candidates from NASDAQ and Finviz, runs a **two-pass funnel** (minimal price/volume hard filters, then a technical score led by accumulation to pick which names get enriched with `yfinance` fundamentals), and exposes the ranked results through a FastAPI backend consumed by a React/Vite frontend.

The interface is written in French. The goal is to surface small caps **early** — quiet accumulation and tight bases, before the move — rather than stocks that have already run. See the [scoring model](docs/backend.md) for the exact signals and weights.

## Documentation

Complete project documentation is available in:

- [Architecture](docs/architecture.md)
- [Backend screener](docs/backend.md)
- [API reference](docs/api.md)
- [Frontend](docs/frontend.md)
- [Deployment and operations](docs/deployment.md)

## Stack

- Backend: Python 3.11, FastAPI, yfinance, pandas, requests, BeautifulSoup
- Frontend: React 18, Vite 5
- Runtime: Docker Compose
- Data cache: Docker volume mounted at `/app/data`

## Quick Start

Prerequisite: Docker Desktop or Docker Engine with Compose.

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY if Claude analysis is needed.
docker-compose up --build
```

Services:

- Frontend: http://localhost:5173
- API scan endpoint: http://localhost:8000/api/scan
- FastAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

`GET /api/scan` is **non-blocking**: it returns the current cache immediately (or an empty payload with `scanning: true` on a cold start) and runs the scan in the background. A scan samples 800 tickers from the universe (resampled each scan), takes ~2-4 minutes, and caches results to the Docker volume for 30 minutes. Poll `GET /api/scan/status` for `phase`/`progress`.

## Useful Commands

```bash
# Start all services
docker-compose up --build

# Force a new scan through the API
curl -X POST http://localhost:8000/api/scan/force

# Run the screener directly inside the backend container
docker-compose exec backend python screener_backend.py

# Follow backend logs
docker-compose logs -f backend

# Stop services
docker-compose down

# Stop services and remove cached scan data
docker-compose down -v
```

## Environment Variables

| Variable | Used by | Required | Description |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | Frontend container as `VITE_ANTHROPIC_API_KEY` | Only for AI analysis | Anthropic API key used by the browser-side Claude analysis button. |

## Main Data Flow

1. The frontend loads and calls `GET /api/scan`, which returns the current cache immediately (non-blocking) and triggers a background scan if the cache is stale or absent.
2. The screener discovers tickers from NASDAQ and Finviz (unless a custom watchlist is set) and samples 800.
3. **Pass A** batch-downloads price/volume data and applies minimal hard filters (price 2–25, liquidity, falling-knife guard) plus technical signals (accumulation, compression, near-pivot, low extension, relative strength).
4. Survivors are ranked by their technical score (accumulation weighted highest); the top ~150 go to **Pass B**.
5. **Pass B** fetches `yfinance` fundamentals for those names, applies market-cap/exchange filters, and computes the final 0–10 score.
6. Results are sorted by score and written to `/app/data/screener_data.json`.
7. The frontend normalizes the result shape, applies local sector and score filters, and renders stock cards.

An offline backtest harness (`backend/backtest.py`) validates that higher-scored names have historically produced higher forward returns.

## Important Notes

- This project is a screening tool, not financial advice.
- Market data is sourced from public endpoints and `yfinance`; availability and field quality can vary by ticker.
- Claude analysis currently runs directly from the browser using `anthropic-dangerous-direct-browser-access`. This is convenient for local use, but it exposes the API key to the browser runtime. For production, proxy AI requests through the backend.
