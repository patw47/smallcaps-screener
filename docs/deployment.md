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

## Cache Management

The scanner writes:

```text
/app/data/screener_data.json
```

Because `/app/data` is mounted to the Compose named volume `data`, cached results survive container restarts.

Remove the cache by deleting the volume:

```bash
docker-compose down -v
```

Or force a scan without removing the volume:

```bash
curl -X POST http://localhost:8000/api/scan/force
```

## Environment

`.env.example`:

```text
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

The key is only required for the frontend Claude analysis button. The stock screener and backend API can run without it.

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
