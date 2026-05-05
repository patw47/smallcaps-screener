# Backend Screener

## Files

- `backend/api.py`: FastAPI application and HTTP routes.
- `backend/screener_backend.py`: market data discovery, filtering, scoring, and JSON output.
- `requirements.txt`: Python runtime dependencies used by the backend image.
- `backend/Dockerfile`: backend container definition.

## Screener Configuration

The main configuration lives in `FILTERS` in `backend/screener_backend.py`.

| Key | Default | Purpose |
| --- | ---: | --- |
| `market_cap_min_m` | `50` | Minimum market cap in USD millions. |
| `market_cap_max_m` | `2000` | Maximum market cap in USD millions. |
| `price_min` | `2.0` | Minimum stock price. |
| `price_max` | `50.0` | Maximum stock price. |
| `ipo_year_min` | `2015` | IPO year threshold used for scoring. |
| `perf_1m_min` | `-0.35` | Minimum one-month performance. |
| `perf_1m_max` | `0.25` | Maximum one-month performance. |
| `vol_window_short` | `10` | Short volume average window in trading days. |
| `vol_window_long` | `50` | Long volume average window in trading days. |
| `compression_window` | `20` | Recent range window. |
| `compression_baseline` | `90` | Baseline range window. |
| `compression_threshold` | `0.70` | Compression threshold. |
| `insider_pct_min` | `5.0` | Insider ownership threshold for scoring. |
| `revenue_growth_min` | `0.10` | Revenue growth threshold for scoring. |
| `short_interest_high` | `15.0` | Short interest threshold for scoring. |
| `score_vol_ratio_min` | `1.3` | Lower ideal volume-ratio score bound. |
| `score_vol_ratio_max` | `2.5` | Upper ideal volume-ratio score bound. |
| `score_change_1m_max` | `0.15` | Maximum absolute one-month move for consolidation scoring. |
| `allowed_exchanges` | `NMS`, `NYQ`, `NGM`, `NCM` | Accepted exchange codes. |
| `rate_limit_s` | `0.3` | Delay between ticker requests. |
| `cache_minutes` | `30` | Cache lifetime. |
| `max_tickers` | `300` | Dynamic discovery cap. |

## Ticker Discovery

Function: `discover_tickers()`

Discovery uses two sources:

- NASDAQ screener API for `Small` and `Micro` market-cap groups.
- Finviz screener page for US NASDAQ small caps.

Symbols containing `.` or `/` are skipped. The combined set is deduplicated, shuffled, capped by `FILTERS["max_tickers"]`, and returned as a list.

If a custom watchlist is set through the API, `run_scan()` receives that list and skips dynamic discovery.

## Per-Ticker Analysis

Function: `analyze_ticker(ticker)`

For each ticker, the screener:

1. Builds a `yfinance.Ticker`.
2. Reads `Ticker.info`.
3. Applies hard exchange, price, market-cap, history, and one-month performance filters.
4. Loads one year of daily history.
5. Computes one-day and one-month price changes.
6. Computes 10-day versus 50-day average volume ratio.
7. Computes 20-day range compression against a 90-day baseline.
8. Reads balance-sheet, insider, short-interest, revenue-growth, and IPO-year fields from `Ticker.info`.
9. Computes score, positives, and warning flags.

Return shape:

```python
(stock_dict, "ok")
```

or:

```python
(None, rejection_reason)
```

Rejection reasons use a `category:detail` convention where possible, for example `price:1.45` or `market_cap:2400M`.

## Hard Filters

The ticker is eliminated immediately when any hard filter fails:

| Filter | Condition |
| --- | --- |
| Exchange | Must be in `allowed_exchanges`. |
| Price | Must be between `price_min` and `price_max`. |
| Market cap | Must be between `market_cap_min_m` and `market_cap_max_m`. |
| History | Must have at least `vol_window_long` daily rows. |
| One-month performance | Must be between `perf_1m_min` and `perf_1m_max`. |

IPO year, volume ratio, insider ownership, cash position, revenue growth, and short interest are scoring inputs, not hard eliminators.

## Scoring

Function: `_compute_score(stock)`

The score is capped at 10.

| Signal | Points |
| --- | ---: |
| Volume ratio between `score_vol_ratio_min` and `score_vol_ratio_max` | 2 |
| Range compression detected | 2 |
| Absolute one-month move below `score_change_1m_max` | 2 |
| Insider ownership above `insider_pct_min` | 2 |
| Total cash greater than total debt | 1 |
| Revenue growth above `revenue_growth_min` | 1 |
| IPO year greater than or equal to `ipo_year_min` | 1 |
| Short interest above `short_interest_high` | 1 |

## Output JSON

`run_scan()` writes this structure to `/app/data/screener_data.json`:

```json
{
  "scanned_at": "2026-05-05T10:00:00+00:00",
  "total_scanned": 300,
  "candidates": 12,
  "stocks": [],
  "rejection_stats": {
    "price": 42,
    "market_cap": 30
  }
}
```

Each stock contains:

```json
{
  "ticker": "ABCD",
  "name": "Example Corp",
  "sector": "Technology",
  "industry": "Software",
  "exchange": "NMS",
  "price": 12.34,
  "change_1d": 0.0123,
  "change_1m": -0.0456,
  "market_cap_m": 450.1,
  "vol_ratio": 1.42,
  "compressed": true,
  "cash_positive": true,
  "insider_buying": false,
  "insider_pct": 1.25,
  "short_interest_pct": 8.3,
  "revenue_growth": 0.18,
  "ipo_year": 2021,
  "catalyst_type": null,
  "catalyst_date": null,
  "score": 7,
  "positives": [],
  "flags": []
}
```

## Scan State

Global `scan_state` exposes:

- `scanning`: whether a scan is active.
- `progress`: number of tickers processed.
- `total`: number of tickers in the current scan.

The API exposes this through `GET /api/scan/status`.
