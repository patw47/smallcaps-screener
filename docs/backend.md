# Backend Screener

## Files

- `backend/api.py`: FastAPI application and HTTP routes.
- `backend/screener_backend.py`: market data discovery, two-pass filtering, scoring, and JSON output.
- `backend/backtest.py`: forward-return validation harness (offline analysis, not part of the live API).
- `backend/tests/`: offline deterministic unit tests (`test_screener.py`, `test_backtest.py`).
- `requirements.txt`: Python runtime dependencies used by the backend image.
- `backend/Dockerfile`: backend container definition.

## Design in one line

**Minimal hard filters (tradable + not a falling knife) → rank by a technical score led by accumulation → enrich the top-scored names with fundamentals.** The thesis is to catch small caps *early* (quiet accumulation / tight base, before the move), so selection is driven by **scoring**, not by strict elimination.

## Screener Configuration

The main configuration lives in `FILTERS` in `backend/screener_backend.py`. No magic numbers in the logic.

| Key | Default | Purpose |
| --- | ---: | --- |
| `market_cap_min_m` / `market_cap_max_m` | `50` / `2000` | Market-cap band (USD millions), Pass B hard filter. |
| `price_min` / `price_max` | `2.0` / `25.0` | Price band (Pass A hard filter). |
| `perf_1m_min` / `perf_1m_max` | `-0.35` / `0.25` | 1-month perf band — light "not already exploded" guard. |
| `vol_window_short` / `vol_window_long` | `10` / `50` | Volume-ratio windows (display only; scoring uses OBV). |
| `compression_window` / `compression_baseline` | `20` / `90` | ATR compression windows. |
| `compression_threshold` / `use_atr_compression` | `0.70` / `True` | `ATR20 < 0.70 × ATR90` (True Range, High/Low). |
| `ma_trend_window` / `ma_slope_lookback` | `50` / `10` | Trend MA + slope lookback. |
| `trend_require_above_ma` | `False` | Price > MA50 is **scoring**, not a hard filter (catch the start of the move). |
| `rs_benchmark` | `IWM` | Relative-strength benchmark (Russell 2000 ETF). |
| `rs_return_window` / `rs_line_lookback` | `63` / `21` | RS return window and RS-line slope lookback. |
| `rs_require` | `False` | RS is **scoring**, not a hard filter (don't require "already strong"). |
| `dollar_vol_window` / `dollar_vol_min` | `20` / `1_000_000` | Median dollar-volume liquidity floor (hard). |
| `obv_lookback` | `21` | OBV-rising window → `accumulation`. |
| `pivot_window` / `near_pivot_pct` | `50` / `0.85` | Near the high of the **recent** base → about to break out. |
| `low_ext_pct` | `0.12` | Price ≤ MA50 × 1.12 → not extended (still early). |
| `high_window` / `near_high_pct` | `252` / `0.75` | 52-week high position (informational). |
| `float_max` | `50_000_000` | Float < 50M shares → `low_float` (score bonus). |
| `insider_pct_min` / `revenue_growth_min` / `short_interest_high` | `5.0` / `0.10` / `15.0` | Fundamental scoring thresholds. |
| `score_weights` | dict | Weight of every score signal (tunable for backtesting). |
| `allowed_exchanges` | `NMS`,`NYQ`,`NGM`,`NCM` | Accepted exchange codes (Pass B). |
| `max_tickers` | `800` | Per-scan universe sample, reshuffled each scan. |
| `history_period` | `1y` | OHLCV depth (needs 252 for 52w + ATR90). |
| `enrich_max` | `150` | Cap on `.info` calls — the **top-scored** survivors are enriched. |
| `enrich_workers` / `enrich_jitter_s` / `enrich_retries` / `enrich_backoff_s` | `2` / `0.5` / `4` / `3.0` | Pass B pool + anti-throttle backoff (Yahoo bans the IP if hammered). |
| `cache_minutes` | `30` | Cache lifetime. |
| `shuffle_seed` | `None` | `int` → deterministic scan; `None` → resample each scan. |

## Ticker Discovery

`discover_tickers()` — NASDAQ (`Small`+`Micro`) + Finviz, deduplicated, shuffled, capped at `max_tickers` (800). With `shuffle_seed=None` each scan resamples a different 800; successive dashboard "Scan" clicks sweep the universe. A custom watchlist bypasses discovery.

## Pass A — price/volume (`analyze_prices`)

Pure function on a batch-downloaded OHLCV DataFrame (no network). **Hard filters** (kept minimal):

| Filter | Condition | Reason |
| --- | --- | --- |
| Price | `price_min ≤ last close ≤ price_max` (2–25) | `price:…` |
| 1-month perf | within `perf_1m_min..max` | `change_1m:…` |
| Liquidity | median 20d dollar-volume ≥ `dollar_vol_min` | `liquidity:…` |
| Falling-knife guard | **MA50 slope ≥ 0** (flat or rising) | `trend:down` |

RS, price > MA50, and near-high are **not** hard filters — they are scoring signals (so early setups aren't eliminated). Optional hard gates exist behind `rs_require` / `trend_require_above_ma` (both `False` by default).

Signals computed: `accumulation` (OBV rising), `compressed` (ATR), `near_pivot` / `pct_recent_high` (recent base), `low_ext` (near MA50), `rs_turning` / `rs_strength` / `rs_signal`, `price_above_ma50`, `pct_52w_high` / `near_high` (informational), `dollar_volume`, `vol_ratio`, `change_1d` / `change_1m`.

## Scoring — `_compute_score` / `_price_score`

**Normalized** to 0–10 via `round(10 × raw / raw_max)`. Weights live in `FILTERS["score_weights"]`.

**Technical signals** (`_tech_rules` — available from Pass A, used to rank survivors):

| Signal | Points |
| --- | ---: |
| Accumulation (OBV rising) | **4** |
| Compression (ATR, tight base) | **3** |
| Near recent-base pivot | 2 |
| Low extension (near MA50) | 2 |
| Relative strength turning up | 2 |
| Price > MA50 | 1 |

**Fundamental signals** (`_fundamental_rules` — added in Pass B):

| Signal | Points |
| --- | ---: |
| Insider ownership > `insider_pct_min` | 2 |
| Cash > debt (only when data present) | 1 |
| Revenue growth > `revenue_growth_min` | 1 |
| Low float | 1 |
| Short interest > `short_interest_high` | 1 |

`_price_score` (technical only) ranks Pass A survivors to decide **which get the expensive `.info` call** — accumulation-led, thesis-justified. Candidates are finally sorted by `(score, rs_strength)`.

## Pass B — fundamentals (`enrich_ticker`)

`.info` on the **top-scored** survivors only (bounded by `enrich_max`). `_fetch_info` wraps `.info` with retries + exponential backoff on `YFRateLimitError`; `enrich_workers` is small (Yahoo rate-limits `.info`). Hard filters: exchange, market-cap band. Fundamentals: `cash_positive` (`None` when missing — not penalized), insider, short interest, revenue growth, `float_shares`/`low_float`, `ipo_year`.

## Orchestration — `run_scan(tickers=None)`

Discover → sample → `_download_prices` → **Pass A** (hard filters + signals) → **rank survivors by `_price_score`, keep top `enrich_max`** → **Pass B** (`.info` + final score) → sort → write `/app/data/screener_data.json`. `scan_state` (`scanning`/`progress`/`total`/`phase`) is shared with `api.py`.

## Output JSON

Top-level: `scanned_at`, `universe_size`, `total_scanned`, `survivors_price_filter`, `enriched`, `candidates`, `stocks`, `rejection_stats`. Each stock carries the Pass A signals plus `ticker`, `name`, `sector`, `industry`, `exchange`, `market_cap_m`, fundamentals, `score`, `positives`, `flags`, and `catalyst_type`/`catalyst_date` (`null`).

## Backtest harness — `backend/backtest.py`

Replays `analyze_prices` at a past as-of date and compares forward returns of survivors vs the tested universe vs IWM, **bucketed by technical score quartile** (does a higher score predict a higher forward return?).

```bash
DATA_DIR=/tmp/bt PYTHONPATH=backend python backtest.py --n 200 --forward 63 --seed 42
```

**Honest limitations:** survivorship bias, no point-in-time fundamentals (validates price/volume signals only), single as-of snapshot. Small samples are not conclusive — a real verdict needs large `n` and a rolling multi-period run.

## Tests

```bash
DATA_DIR=/tmp/screener_test PYTHONPATH=backend python -m pytest backend/tests/
```

Deterministic, offline. The module honors `DATA_DIR` so it imports outside the container.
