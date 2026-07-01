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
| `scoring_mode` | `binary` | `binary` (default, ~0–8) or `continuous` (decile 0–10) — see Scoring. |
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

## Scoring — two modes (`FILTERS["scoring_mode"]`)

The scoring approach is **not settled** — it is a config flag, and a larger rolling
backtest is meant to decide it (the current small-sample backtest cannot). Both modes
use the same weights (`FILTERS["score_weights"]`) and are computed in `_score_candidates`.

- **`"binary"` (default)** — the original "checkbox" score (`_binary_score`): each signal
  adds fixed points, normalized to 0–10. Known and conservative, but **caps around 8**
  (some points are near-unreachable, e.g. ATR compression fires on ~1/146 names).
- **`"continuous"`** — standard quant factor scoring: each factor is a **continuous** value,
  **percentile-ranked across the candidate set** (`_rank_pct`), combined into a weighted
  average (`_factor_composite`), then mapped to a **decile 0–10** so the best of the day's
  pool = 10. Fixes the scale and loses no information, but its edge is **not yet validated**.

Selection of which survivors get enriched follows the same mode (`_select_scores`).

**Technical factors** (Pass A; `TECH_FACTORS`; used to rank which survivors get enriched):

| Factor (continuous) | Weight | Direction |
| --- | ---: | --- |
| `f_accum` — net directional volume fraction (∈[-1,1]) | 4 | higher better |
| `f_atr_ratio` — ATR20 / ATR90 | 3 | lower better |
| `f_pct_recent` — proximity to recent-base high | 2 | higher better |
| `f_ext` — price/MA50 − 1 (extension) | 2 | lower better |
| `f_rs` — relative-strength magnitude vs IWM | 2 | higher better |

**Fundamental factors** (Pass B; `FUND_FACTORS`): `insider_pct` (2), `cash_bin` (1),
`revenue_growth` (1), `float_shares` (1, lower better), `short_interest_pct` (1).

The two factor tables above are the **continuous-mode** factors. In continuous mode the
final `score` is computed **cross-sectionally over the candidate set** in `run_scan` (a
percentile needs the population). In **binary mode** (the default) the score instead comes
from `_binary_score` (`_tech_rules` + `_fundamental_rules`, the boolean signals). Selection
(`_select_scores`) follows the active mode. Candidates are sorted by `(score, rs_strength)`.

> The backtest (`backend/backtest.py`) scores the same survivors **both ways** and prints
> the two quartile tables side by side, so the mode can be chosen on evidence once the
> sample is large enough. At small survivor counts the two are statistically indistinguishable.

## Pass B — fundamentals (`enrich_ticker`)

`.info` on the **top-scored** survivors only (bounded by `enrich_max`). `_fetch_info` wraps `.info` with retries + exponential backoff on `YFRateLimitError`; `enrich_workers` is small (Yahoo rate-limits `.info`). Hard filters: exchange, market-cap band. Fundamentals: `cash_positive` (`None` when missing — not penalized), insider, short interest, revenue growth, `float_shares`/`low_float`, `ipo_year`.

## Orchestration — `run_scan(tickers=None)`

Discover → sample → `_download_prices` → **Pass A** (hard filters + continuous factors) → **rank survivors by technical composite (`_select_scores`), keep top `enrich_max`** → **Pass B** (`.info`) → **`_score_candidates` (decile 0–10 over the whole set)** → sort → write `/app/data/screener_data.json`. `scan_state` (`scanning`/`progress`/`total`/`phase`) is shared with `api.py`.

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
