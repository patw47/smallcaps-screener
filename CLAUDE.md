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
- `screener_backend.py` is the core. It runs a **two-pass funnel** driven by **scoring, not strict elimination** — the thesis is to catch small caps *early* (quiet accumulation / tight base before the move). **Pass A** (`analyze_prices`) batch-downloads `FILTERS["history_period"]` (1y) OHLCV via `yf.download` and applies **minimal** hard filters: price band (2–25), 1-month perf, **liquidity ≥ $1M median dollar-volume**, and a **falling-knife guard = MA50 slope ≥ 0**. RS and price>MA50 are **scoring, not hard filters** (`rs_require`/`trend_require_above_ma` default `False`) so early setups aren't eliminated. It computes technical signals: OBV accumulation, ATR compression, near recent-base pivot (`pivot_window`), low extension (`low_ext`), RS turning/magnitude. **Pass B** (`enrich_ticker`) fetches `.info` only for the **top-scored** survivors, applies market-cap/exchange hard filters, adds fundamentals (incl. `float_shares`/`low_float`), and computes the final score. All thresholds live in `FILTERS`; `scan_state` (`scanning`/`progress`/`total`/`phase`) is shared with `api.py`.
- **The `.info` endpoint (Pass B) is heavily rate-limited by Yahoo** — parallelizing it aggressively gets the IP banned (`YFRateLimitError`). Pass B uses a *small* `ThreadPoolExecutor` (`enrich_workers`, default 2) + jitter + exponential backoff/retry (`_fetch_info`). The real lever to keep `.info` calls safe is **fewer survivors**, bounded by the `enrich_max` cap.
- **Ranking selects who gets enriched.** Survivors are sorted by `_price_score` (technical only, **accumulation weighted highest**) and the top `enrich_max` go to Pass B. This replaced the earlier random-sample cap — now that accumulation *is* the thesis, ranking by it is intended, not a bias. Candidates are finally sorted by `(score, rs_strength)`.
- Score is **normalized** (`round(10 * raw / raw_max)`), not hard-capped. Weights live in `FILTERS["score_weights"]` (tunable for backtesting). Technical: accumulation +4, compression +3, near_pivot +2, low_ext +2, rs_turning +2, price>MA50 +1. Fundamental: insider +2, cash>debt +1, revenue +1, low_float +1, short +1.
- `cash_positive` is `None` when balance-sheet data is missing (not `False`) — absence is not penalized.
- `backend/backtest.py` is an **offline forward-return validation harness** (replays `analyze_prices` at a past as-of date, compares survivor vs universe forward returns). Not wired into the live API. Validates price/volume signals only (no point-in-time fundamentals; survivorship bias).
- Offline unit tests live in `backend/tests/` (`DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/`). The module honors a `DATA_DIR` env var so it can be imported outside the container.
- `api.py` wraps the backend as a FastAPI app under `/api/*`, CORS open for dev. **Scans never block a request**: `GET /api/scan` is non-blocking (stale-while-revalidate; kicks a background scan and returns cache/empty immediately), a startup hook warms the cache, and a single background scan is guarded by `_bg_scan_inflight`. Clients poll `/api/scan/status` for `phase`/`progress`. `DELETE /api/watchlist` reverts to dynamic discovery.

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
    → Pass A: yf.download batch (1y) → analyze_prices()
              minimal hard filters: price 2-25, perf1m, liquidity≥$1M,
              falling-knife guard (MA50 slope ≥ 0)
              + technical signals (accumulation, compression, near_pivot, low_ext, RS)
    → rank survivors by technical score (accumulation-led) → keep top enrich_max
    → Pass B: .info per top survivor (2 workers + backoff) → enrich_ticker()
              market-cap/exchange filters + fundamentals + normalized score
    → screener_data.json
                                          ↕
                          FastAPI /api/scan  ←→  JSX (Vite proxy /api → backend:8000)
```

## Key design notes

- A scan takes ~2-4 min: Pass A batch-downloads the 800-sample (cheap, no ban risk), Pass B does `.info` only on the **top-scored** survivors, bounded by `enrich_max` (≤150), via a small thread pool with backoff. The `enrich_max` cap is what keeps `.info` under Yahoo's rate limit.
- `catalyst_type` and `catalyst_date` fields are always `null` from the backend — reserved for manual enrichment via the dashboard.
- The JSX uses `claude-sonnet-4-20250514` model ID — update this when migrating to newer Claude versions.

## Security note

Claude API calls are made directly from the browser in the current JSX. This is a temporary development shortcut. In production, proxy all Anthropic API calls through the FastAPI backend to avoid exposing the API key client-side.
