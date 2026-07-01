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
- `screener_backend.py` is the core. It runs a **two-pass funnel** with **ultra-quality hard filters, then unbiased sampling** (no biased ranking). **Pass A** (`analyze_prices`) batch-downloads `FILTERS["history_period"]` (6mo) OHLCV via `yf.download` and applies the price/volume hard filters — price band, 1-month perf, **liquidity ≥ $1M median dollar-volume**, **MA50 trend (price > MA50 AND slope ≥ 0)**, and **relative strength vs `IWM` as a HARD filter** (`rs_require`; skipped gracefully if the benchmark download fails). It also computes the technical signals (vol_ratio, compression). **Pass B** (`enrich_ticker`) fetches `.info` for survivors, applies market-cap/exchange hard filters, adds fundamental signals, and scores. It writes `screener_data.json`. All thresholds live in `FILTERS`. `scan_state` (`scanning`/`progress`/`total`/`phase`) is shared with `api.py`.
- **The `.info` endpoint (Pass B) is heavily rate-limited by Yahoo** — parallelizing it aggressively gets the IP banned (`YFRateLimitError`). Pass B uses a *small* `ThreadPoolExecutor` (`enrich_workers`, default 2) + jitter + exponential backoff/retry (`_fetch_info`). The real lever to keep `.info` calls safe is **fewer survivors**, not more concurrency: the ultra-quality Pass A filters + the `enrich_max` safety cap bound the call count.
- **No biased ranking cap.** If survivors exceed `enrich_max`, they are cut by `random.sample` (unbiased), reshuffled each scan — NOT ranked by a partial price-only pre-score. Selection quality comes from the hard filters; sampling only bounds cost.
- Score is **normalized** (`round(10 * raw / raw_max)`), not hard-capped. `rs_signal` (+2) and `price_above_ma50` (+1) are scored (RS is both a hard gate and a score component); the old "calm 1m" bonus and IPO-recency points were removed.
- `cash_positive` is `None` when balance-sheet data is missing (not `False`) — absence is not penalized.
- Offline unit tests live in `backend/tests/` (`DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/`). The module honors a `DATA_DIR` env var so it can be imported outside the container.
- `api.py` wraps the backend as a FastAPI app. All endpoints are prefixed `/api/*`. CORS is open on `*` for development. Runs scans in a thread executor to avoid blocking the event loop. A `DELETE /api/watchlist` endpoint reverts back to dynamic discovery.

**Ticker discovery** (dynamic — no static list)
- Tickers are fetched fresh each scan from two sources:
  - NASDAQ API: `https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange=nasdaq`
  - Finviz scraping: `https://finviz.com/screener.ashx` via `requests` + `BeautifulSoup` (selector: `a.screener-link-primary`)
- The combined list is deduplicated, `random.shuffle()` applied, then capped at `FILTERS["max_tickers"]` (800 — a **per-scan random sample** of the ~1,686 universe). With `shuffle_seed=None` (default) the global RNG advances and the universe is re-fetched each scan, so **every scan / dashboard "Scan" click resamples a different 800** — successive clicks sweep the universe. Set `shuffle_seed` to an int for reproducible scans (e.g. for a backtest/diff).
- There is no static ticker list. Do not reintroduce one.
- `POST /api/watchlist` overrides dynamic discovery for the session; `DELETE /api/watchlist` reverts to dynamic.

**Frontend** (`frontend/smallcap-screener.jsx`)
- Do not modify this component. It is the canonical UI and is imported as-is by `frontend/src/main.jsx`.
- **Already wired to the backend** (no `MOCK_STOCKS`): `fetchData()` calls `fetch("/api/scan")` on mount and `runScan()` POSTs `/api/scan/force`. The Vite dev server proxies `/api` → `http://backend:8000` (`vite.config.js`), so relative `/api/*` from :5173 reaches the backend container.
- Has its own `scoreStock()` function that duplicates scoring logic from `_compute_score()` in the backend. **These have diverged** (backend scoring changed: RS/trend added, normalized, calm/IPO removed) — `scoreStock()` is only used for the Claude brief prompt/display; the ranking uses the backend's `stock.score`. Resync when convenient.
- Calls `https://api.anthropic.com/v1/messages` directly from the browser for per-stock Claude analysis (temporary dev setup — see Security note below).

**Data flow**
```
NASDAQ API + Finviz → deduplicate → random.shuffle → [:800]   (resampled each scan)
    → Pass A: yf.download batch (6mo) → analyze_prices()
              ultra-quality hard filters: price, perf1m, liquidity≥$1M,
              trend (price>MA50 & slope≥0), RS vs IWM (hard)
    → survivors → (random.sample to enrich_max if too many, unbiased)
    → Pass B: .info per survivor (2 workers + backoff) → enrich_ticker()
              market-cap/exchange filters + fundamentals + normalized score
    → screener_data.json
                                          ↕
                          FastAPI /api/scan  ←→  JSX (Vite proxy /api → backend:8000)
```

## Key design notes

- A scan takes ~2-4 min: Pass A batch-downloads the 800-sample (cheap, no ban risk), Pass B does `.info` on the survivors (typically <150) via a small thread pool with backoff. Ultra-quality filters keep survivors low, which is what keeps `.info` under Yahoo's rate limit.
- `catalyst_type` and `catalyst_date` fields are always `null` from the backend — reserved for manual enrichment via the dashboard.
- The JSX uses `claude-sonnet-4-20250514` model ID — update this when migrating to newer Claude versions.

## Security note

Claude API calls are made directly from the browser in the current JSX. This is a temporary development shortcut. In production, proxy all Anthropic API calls through the FastAPI backend to avoid exposing the API key client-side.
