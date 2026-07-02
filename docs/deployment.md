# Deployment and Operations

## Local Docker Run

```bash
cp .env.example .env
docker-compose up --build
```

The Compose stack starts:

| Service | Port | Description |
| --- | ---: | --- |
| `backend` | `8000` | FastAPI API and screener engine. |
| `frontend` | `5173` | Vite React app. |

## Docker Compose

File: `docker-compose.yml`

Backend:

- Builds from the repository root.
- Uses `backend/Dockerfile`.
- Exposes port `8000`.
- Mounts named volume `data` at `/app/data`.
- Restarts automatically.

Frontend:

- Builds from `./frontend`.
- Uses `frontend/Dockerfile`.
- Exposes port `5173`.
- Receives `ANTHROPIC_API_KEY` as `VITE_ANTHROPIC_API_KEY`.
- Depends on the backend service.
- Restarts automatically.

## Backend Container

File: `backend/Dockerfile`

The backend image:

1. Starts from `python:3.11-slim`.
2. Sets `/app` as the working directory.
3. Copies `requirements.txt`.
4. Installs Python dependencies.
5. Copies `backend/`.
6. Runs Uvicorn with reload enabled:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

## Frontend Container

File: `frontend/Dockerfile`

The frontend image:

1. Starts from `node:20-alpine`.
2. Sets `/app` as the working directory.
3. Copies `package.json`.
4. Runs `npm install`.
5. Copies the frontend source.
6. Runs Vite dev server with host binding:

```bash
npm run dev -- --host
```

## Cache and history

The scanner writes the latest results to `/app/data/screener_data.json`, and a dated
snapshot of each scan's picks to `/app/data/history/*.json` (used by `GET /api/performance`
to track past selections over time). Both live on the Compose named volume `data`, so they
survive container restarts. The scheduler runs one scan per **trading day**
(`SCAN_TRADING_DAYS_ONLY`, weekends skipped). **Retention policy: keep everything** —
snapshots are a few KB each and a longer history makes the tracker more meaningful.

Remove everything (cache + history) by deleting the volume:

```bash
docker-compose down -v
```

Or force a fresh scan without removing the volume (previous results stay served meanwhile):

```bash
curl -X POST http://localhost:8000/api/scan/force
```

## Backtest and performance tooling (offline)

```bash
# Forward-return backtest (single window; continuous vs binary score)
docker-compose exec backend python backtest.py --n 200 --forward 63 --seed 42

# Rolling weight sweep (pools several windows to escape small-sample noise)
docker-compose exec backend python backtest.py --sweep --n 250 --forward 63

# Performance of past selections since first flagged
curl http://localhost:8000/api/performance
```

## Environment

`.env.example`:

```text
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

| Variable | Required | Description |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Only for the frontend Claude button | Passed to the frontend as `VITE_ANTHROPIC_API_KEY`. The screener and API run without it. |
| `SCAN_EVERY_HOURS` | No (default 24) | Interval between automatic background scans (history accumulation). |
| `SCAN_TRADING_DAYS_ONLY` | No (default `true`) | Only auto-scan on trading days (Mon–Fri); skip weekends. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | No | Breakout alerts (Sprint 3). Absent → alerting silently disabled. |
| `EDGAR_USER_AGENT` | No | SEC Form 4 insider data (Sprint 5). Identifying UA (name + email). Absent → EDGAR disabled (neutral). |
| `DATA_DIR` | No (default `/app/data`) | Where cache + history are written (used by tests outside the container). |

## Operational Checks

Health check:

```bash
curl http://localhost:8000/api/health
```

Scan status:

```bash
curl http://localhost:8000/api/scan/status
```

Backend logs:

```bash
docker-compose logs -f backend
```

Frontend logs:

```bash
docker-compose logs -f frontend
```

## Production Hardening Checklist

- Move Anthropic API calls from the browser to a backend endpoint.
- Restrict CORS origins in `backend/api.py`.
- Disable Uvicorn `--reload`.
- Use a production frontend build instead of the Vite dev server.
- Add authentication if exposing watchlist or scan controls publicly.
- Add request timeouts and retries around external market data calls where needed.
- Add structured logging for scan progress and rejection statistics.
- Add tests for filter boundaries, scoring, cache behavior, and API routes.
