# API Reference

Base URL in Docker Compose:

```text
http://localhost:8000
```

All application endpoints are prefixed with `/api`.

## `GET /api/scan`

Runs a scan if no valid cache exists, then returns scan data.

Cache behavior:

- Reads `/app/data/screener_data.json` when present.
- Cache is valid for `FILTERS["cache_minutes"]`, currently 30 minutes.
- Concurrent cache misses are serialized with an `asyncio.Lock`.

Response:

```json
{
  "scanned_at": "2026-05-05T10:00:00+00:00",
  "total_scanned": 300,
  "candidates": 12,
  "stocks": [],
  "rejection_stats": {}
}
```

Errors:

- `500`: scan completed without producing cached data.

## `GET /api/scan/status`

Returns the current scanner state.

Response:

```json
{
  "scanning": true,
  "progress": 42,
  "total": 300,
  "last_scan": "2026-05-05T10:00:00+00:00"
}
```

Fields:

- `scanning`: `true` when a scan is active.
- `progress`: processed ticker count.
- `total`: total ticker count for the active scan.
- `last_scan`: timestamp set when the API scan function finishes, or `null`.

## `POST /api/scan/force`

Deletes the cache file if present, clears in-memory cached data, starts a new scan in a background executor, and returns immediately.

Response:

```json
{
  "message": "Nouveau scan démarré en arrière-plan"
}
```

Errors:

- `409`: a scan is already in progress.

## `GET /api/stock/{ticker}`

Returns a single ticker from the latest scan result.

Example:

```bash
curl http://localhost:8000/api/stock/ABCD
```

Errors:

- `404`: no scan data is available.
- `404`: ticker was not found in the latest result set.

## `GET /api/watchlist`

Returns the current watchlist mode.

Response in dynamic mode:

```json
{
  "mode": "dynamic",
  "tickers": null,
  "count": null
}
```

Response in custom mode:

```json
{
  "mode": "custom",
  "tickers": ["ABCD", "EFGH"],
  "count": 2
}
```

## `POST /api/watchlist`

Sets a custom watchlist and disables dynamic discovery for future scans.

Request:

```json
{
  "tickers": ["abcd", "efgh", "ABCD"]
}
```

Behavior:

- Uppercases ticker symbols.
- Trims whitespace.
- Deduplicates while preserving first occurrence order.
- Stores the result in memory.

Response:

```json
{
  "message": "Watchlist personnalisée définie (2 tickers)",
  "tickers": ["ABCD", "EFGH"]
}
```

Errors:

- `400`: `tickers` is empty.

## `DELETE /api/watchlist`

Clears the custom watchlist and returns to dynamic discovery.

Response:

```json
{
  "message": "Retour à la découverte dynamique"
}
```

## `GET /api/health`

Health check endpoint.

Response:

```json
{
  "status": "ok",
  "timestamp": "2026-05-05T10:00:00+00:00"
}
```

## CORS

The FastAPI app currently allows all origins, all methods, and all headers:

```python
allow_origins=["*"]
allow_methods=["*"]
allow_headers=["*"]
```

This is suitable for local development. Restrict it before exposing the API publicly.
