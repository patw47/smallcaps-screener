# API Reference

Base URL in Docker Compose:

```text
http://localhost:8000
```

All application endpoints are prefixed with `/api`.

## `GET /api/scan`

**Non-blocking** (stale-while-revalidate). Never runs a scan synchronously in the request:

- **Fresh cache** (< `cache_minutes`, default 30): returned directly.
- **Stale result** exists: returned immediately with `"stale": true` while a background refresh is kicked.
- **No data yet** (cold start): returns an empty payload with `"scanning": true` and kicks a background scan.

A FastAPI startup hook also warms the cache on boot. Clients should poll `GET /api/scan/status` for progress and re-fetch when a scan completes.

Response (fresh cache):

```json
{
  "scanned_at": "2026-07-01T16:14:00+00:00",
  "universe_size": 2487,
  "total_scanned": 2487,
  "survivors_price_filter": 210,
  "enriched": 150,
  "candidates": 148,
  "stocks": [],
  "rejection_stats": {}
}
```

Response (scan in progress, no fresh cache) adds `"scanning": true`, `"phase": "..."`, and (if a stale result exists) `"stale": true`.

Each entry in `stocks` carries, besides `score`/`positives`/`flags`: **`setup_score`** (canonical
alias of `score` — "the spring is coiled"), **`triggered`** (bool — the breakout is happening
now), **`days_since_trigger`** (breakout day = `0`, `None` if not above pivot) and **`pivot_level`**.
`GET /api/stock/{ticker}` returns the same fields. The frontend currently ignores the trigger
fields; a future UI will surface them.

**Telegram alerts** (server-side, no endpoint): each scan pings newly `triggered` names with
`setup_score ≥ alert_min_score`, deduplicated for `alert_dedup_days`. Configured via
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env vars; **absent → silently disabled**, the scan is
unaffected.

## `GET /api/scan/status`

Returns the current scanner state.

Response:

```json
{
  "scanning": true,
  "progress": 42,
  "total": 95,
  "phase": "enrich",
  "last_scan": "2026-07-01T16:14:00+00:00"
}
```

Fields:

- `scanning`: `true` when a scan is active.
- `progress` / `total`: processed count / total for the current phase (Pass A universe, then Pass B survivors).
- `phase`: `idle` | `download` | `price_filter` | `enrich`.
- `last_scan`: timestamp set when the API scan function finishes, or `null`.

## `POST /api/scan/force`

Starts a new scan in a background executor and returns immediately. It does **not** delete
the cache — the previous results stay served by `GET /api/scan` (stale-while-revalidate)
until the new scan finishes, so the dashboard is never blank while re-scanning.

Response:

```json
{
  "message": "Nouveau scan démarré en arrière-plan (les résultats actuels restent affichés)"
}
```

Errors:

- `409`: a scan is already in progress.

Besides this endpoint, the backend runs an **automatic scan every `SCAN_EVERY_HOURS`**
(default 24, env var), **only on trading days** (`SCAN_TRADING_DAYS_ONLY`, default `true` —
weekends skipped), and warms the cache on startup, so the scan history accumulates on its
own at roughly one snapshot per trading day.

## `GET /api/performance`

Tracks how past selections have performed over time. For each ticker it takes the first
scan that flagged it (entry date/price from `data/history/` snapshots), fetches the current
price, computes the return since flagged, and aggregates by score bucket and vs IWM.

Query params: `high` (int, default 7) — the "high score" threshold for the bucket split.

Runs in a background executor (it downloads recent prices, so it can take ~10–30 s).
Returns `{"n_picks": 0, ...}` until the scan history has entries.

**Always available**: the tracker is hardened so this endpoint never 500s. A delisted or
missing ticker is skipped, and a market-data outage or unreadable snapshot returns a
well-formed empty payload carrying a `message` field instead of raising.

```json
{
  "n_picks": 137,
  "n_tracked": 137,
  "overall": { "n": 137, "mean": 0.02, "median": 0.01, "hit": 0.55 },
  "excess_mean": 0.01,
  "high_score": { "n": 40, "mean": 0.05 },
  "low_score": { "n": 97, "mean": 0.01 },
  "rows": []
}
```

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
