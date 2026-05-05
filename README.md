# SmallCaps Screener

SmallCaps Screener is a Dockerized dashboard for discovering and ranking US small-cap stocks. It discovers candidates from NASDAQ and Finviz, enriches them with `yfinance`, applies hard filters, computes a setup score, and exposes the results through a FastAPI backend consumed by a React/Vite frontend.

The interface is written in French and targets quick visual review of small-cap setups before a potential rally.

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

The first `/api/scan` request starts a market scan. With the default cap of 300 tickers, the scan usually takes a few minutes and writes cached results to the Docker volume for 30 minutes.

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

1. The frontend loads and calls `GET /api/scan`.
2. The backend returns a fresh JSON cache if one exists.
3. If the cache is stale or absent, the backend runs a scan.
4. The screener discovers tickers from NASDAQ and Finviz unless a custom watchlist is configured.
5. Each ticker is fetched from `yfinance`, filtered, scored, and added to the result set if it passes.
6. Results are written to `/app/data/screener_data.json`.
7. The frontend normalizes the result shape, applies local sector and score filters, and renders stock cards.

## Important Notes

- This project is a screening tool, not financial advice.
- Market data is sourced from public endpoints and `yfinance`; availability and field quality can vary by ticker.
- Claude analysis currently runs directly from the browser using `anthropic-dangerous-direct-browser-access`. This is convenient for local use, but it exposes the API key to the browser runtime. For production, proxy AI requests through the backend.
