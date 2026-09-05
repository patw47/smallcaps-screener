# Backend Screener

## Files

- `backend/api.py`: FastAPI application and HTTP routes.
- `backend/screener_backend.py`: market data discovery, two-pass filtering, scoring, and JSON output.
- `backend/profiles.py`: tail-hunting profile detectors (Fusée / Phénix) — the single source of truth for the protocol v2 §3 definitions, shared by production and the study.
- `backend/finviz.py`: Finviz Elite CSV export client — optional fundamentals source, **not wired into the scan yet** (Epic 13 S1).
- `backend/backtest.py`: forward-return validation harness (offline analysis, not part of the live API).
- `backend/tests/`: offline deterministic unit tests (`test_screener.py`, `test_backtest.py`).
- `requirements.txt`: Python runtime dependencies used by the backend image.
- `backend/Dockerfile`: backend container definition.

## Design in one line

**Minimal hard filters (tradable + not a falling knife) → rank by a technical score led by accumulation → enrich the top-scored names with fundamentals.** The thesis is to catch small caps *early* (quiet accumulation / tight base, before the move), so selection is driven by **scoring**, not by strict elimination.

> **Epic 2 — tail-hunting pivot (FAILED).** The v1 thesis above failed its pre-registered study;
> the project pivoted to two frozen profiles (**Fusée**, **Phénix**) in
> [backtest_protocol_v2.md](backtest_protocol_v2.md). Both FAILED Validation A (§9-§10 there).
>
> **Epic 3 — survival-conditioned right-tail scoring (in progress).** The next thesis replaces the
> hand-drawn profiles with an interpretable, calibrated `P(fwd63 ≥ +100 %)` model over frozen
> price features **plus EDGAR survival signals**, validated by purged walk-forward. Binding spec:
> [backtest_protocol_v3.md](backtest_protocol_v3.md). The v1 screener documented here stays in
> production until v3 lands.

## Screener Configuration

The main configuration lives in `FILTERS` in `backend/screener_backend.py`. No magic numbers in the logic.

| Key | Default | Purpose |
| --- | ---: | --- |
| `market_cap_min_m` / `market_cap_max_m` | `50` / `2000` | Market-cap band (USD millions), Pass B hard filter. |
| `price_min` / `price_max` | `2.0` / `25.0` | Price band (Pass A hard filter). |
| `perf_1m_min` / `perf_1m_max` | `-0.35` / `0.25` | 1-month perf band — light "not already exploded" guard. |
| `vol_window_short` / `vol_window_long` | `10` / `50` | Volume-ratio windows (display only; scoring uses OBV). |
| `compression_window` / `compression_baseline` | `20` / `90` | ATR compression windows (ATR20 / ATR90). |
| `compression_threshold` / `use_atr_compression` | `0.70` / `True` | **v1 only** raw-ratio threshold `ATR20 < 0.70 × ATR90`. |
| `sensors_version` | `v2` | `v2` (default) or `v1` — selects compression + accumulation sensors (see Sensors v2). |
| `compression_pct_lookback` / `compression_pct_threshold` / `compression_pct_min_obs` | `252` / `0.25` / `60` | **v2 compression**: self-percentile of ATR20/ATR90 over the stock's own history; `< 0.25` → compressed; needs ≥60 obs else neutral. |
| `cmf_window` / `updown_vol_window` | `20` / `50` | **v2 accumulation**: Chaikin Money Flow window + up/down volume-ratio window. |
| `cmf_pos_threshold` / `updown_ratio_min` | `0.0` / `1.0` | v2 accumulation booleans: `CMF > 0` AND up/down volume ratio `> 1`. |
| `ma_trend_window` / `ma_slope_lookback` | `50` / `10` | Trend MA + slope lookback. |
| `trend_require_above_ma` | `False` | Price > MA50 is **scoring**, not a hard filter (catch the start of the move). |
| `rs_benchmark` | `IWM` | Relative-strength benchmark (Russell 2000 ETF). |
| `rs_return_window` / `rs_line_lookback` | `63` / `21` | RS return window and RS-line slope lookback. |
| `rs_require` | `False` | RS is **scoring**, not a hard filter (don't require "already strong"). |
| `dollar_vol_window` / `dollar_vol_min` | `20` / `1_000_000` | Median dollar-volume liquidity floor (hard). |
| `obv_lookback` | `21` | **v1 only** OBV-rising window → `accumulation`. |
| `pivot_window` / `near_pivot_pct` | `50` / `0.85` | Near the high of the **recent** base → about to break out. |
| `low_ext_pct` | `0.12` | Price ≤ MA50 × 1.12 → not extended (still early). |
| `trigger_vol_window` / `trigger_vol_mult` | `50` / `1.5` | Breakout: today's volume > `1.5 ×` the 50-day average. |
| `alert_dedup_days` | `5` | Telegram: no re-alert of a ticker within N days. |
| `high_window` / `near_high_pct` | `252` / `0.75` | 52-week high position (informational). |
| `float_max` | `50_000_000` | Float < 50M shares → `low_float` (score bonus). |
| `insider_pct_min` / `revenue_growth_min` / `short_interest_high` | `5.0` / `0.10` / `15.0` | Fundamental thresholds. `insider_pct_min` is **display only** now (score uses net buying). |
| `insider_window_days` | `180` | EDGAR Form 4: net-purchase aggregation window (3–6 months). |
| `edgar_cache_ttl_hours` / `edgar_rate_limit_s` / `edgar_max_filings` | `24` / `0.12` / `40` | EDGAR submissions cache TTL, throttle (≤10 req/s), Form 4 parse cap per ticker. |
| `scoring_mode` | `binary` | `binary` (default, ~0–8) or `continuous` (decile 0–10) — see Scoring. |
| `score_weights` | dict | Weight of every score signal (tunable for backtesting). |
| `allowed_exchanges` | `NMS`,`NYQ`,`NGM`,`NCM` | Accepted exchange codes (Pass B). |
| `discovery_exchanges` | `nasdaq`,`nyse`,`amex` | US exchanges queried on the NASDAQ screener API. |
| `discovery_marketcaps` | `Small`,`Micro` | Market-cap buckets pulled per exchange. |
| `max_tickers` | `None` | `None` → **full universe** (no sampling); `int` → optional safety cap (tests/debug). |
| `history_period` | `1y` | OHLCV depth (needs 252 for 52w + ATR90). |
| `enrich_max` | `150` | Cap on `.info` calls — the **top-scored** survivors are enriched. Also the bound the Finviz→Yahoo fallback reverts to. |
| `enrich_source` | `yahoo` | Pass B fundamentals: `yahoo` (one `.info` per ticker — code default, the only path of a plain clone) or `finviz` (one export call for the whole universe, **local config only**). |
| `enrich_max_snapshot` | `150` | Cap on the **snapshot** path. One request covers the universe, so this is a **valve** (`max_tickers` pattern): `null` in local config lifts it and every name above the cutoff is examined. The code default stays the guard. |
| `enrich_workers` / `enrich_jitter_s` / `enrich_retries` / `enrich_backoff_s` | `2` / `0.5` / `4` / `3.0` | Pass B pool + anti-throttle backoff (Yahoo bans the IP if hammered). |
| `cache_minutes` | `720` | Cache lifetime (12 h). Shorter buys no freshness — the scan is daily — and costs a full rescan per restart/visit. |
| `shuffle_seed` | `None` | `int` → reproducible **download order**; `None` → random order. Never changes universe membership. |
| `pool_mode` | `tradability` | **Epic 2**: `tradability` (default) → hard path = price ≥ `price_min` + dollar-volume ≥ `dollar_vol_min`, selection by **profile detectors**; `legacy` → the v1 funnel (`price_max`, `perf_1m` band, MA50-slope gate) for backtest reproducibility. |
| `profiles` | dict | Cross-sectional **percentile** thresholds for Fusée / Phénix, **verbatim** from protocol v2 §3: Fusée `rs63/perf_1m ≥ P80`; Phénix `pct_52w ≤ P20`, `atr_ratio ≤ P40`, `close ≥ SMA20` (`phenix_sma_window`). Single source of truth (prod ↔ study). |

## Ticker Discovery

`discover_tickers()` queries the **NASDAQ screener API** across the three US exchanges
(`nasdaq` + `nyse` + `amex`), each for the `Small` and `Micro` cap buckets, then
deduplicates into the **complete eligible universe** (~2,000–3,000 names). The result is
**stable from one scan to the next** — there is no random sampling. `shuffle_seed`/shuffle
only set the *download order*, never which tickers are in the universe. `max_tickers` is
`None` by default (no truncation); an `int` is an optional safety cap for tests/debug. A
custom watchlist bypasses discovery.

**Finviz was removed** (Sprint 1): without pagination it contributed only ~20 tickers from
a single exchange (NASDAQ), now fully covered by the NASDAQ screener API. Discovery stays
**dynamic** — no static ticker list.

## Pass A — price/volume (`analyze_prices`)

Pure function on a batch-downloaded OHLCV DataFrame (no network). The **hard filters depend on `pool_mode`** (Epic 2):

| Filter | `tradability` (default) | `legacy` (v1 funnel) | Reason |
| --- | --- | --- | --- |
| Price floor | `close ≥ price_min` (2) | `close ≥ price_min` | `price:…` |
| Price ceiling | — (kept as value only) | `close ≤ price_max` (25) | `price:…` |
| 1-month perf | — (informational) | within `perf_1m_min..max` | `change_1m:…` |
| Liquidity | median 20d dollar-volume ≥ `dollar_vol_min` | same | `liquidity:…` |
| Falling-knife guard | — (informational) | **MA50 slope ≥ 0** | `trend:down` |

In `tradability` the pool is **everything tradable** (price floor + liquidity, protocol v2 §2) and **selection is done by the profile detectors** (below), not by the funnel. `legacy` reproduces the v1 hard path for backtest regression. RS, price > MA50 and near-high are never hard filters (scoring signals); optional legacy-only gates live behind `rs_require` / `trend_require_above_ma`.

Signals computed: `accumulation`, `compressed` (see Sensors v2), `near_pivot` / `pct_recent_high` (recent base), `low_ext` (near MA50), `rs_turning` / `rs_strength` / `rs_signal`, `price_above_ma50`, **`sma20`** (Phénix `close ≥ SMA20` gate), `pct_52w_high` / `near_high` (informational), `dollar_volume`, `vol_ratio`, `change_1d` / `change_1m`, the v2 diagnostics `compression_pct` / `atr_ratio` / `cmf` / `updown_vol_ratio`, and the **trigger** fields below.

## Sensors v2 — compression & accumulation (`FILTERS["sensors_version"]`)

The two pillar sensors were reworked (Sprint 4) to fix v1 defects, **without touching the
score's weights or philosophy**. The old versions stay behind the `sensors_version` flag
(`v2` default, `v1` for the Sprint 6 backtest comparison).

- **Compression v2** (`_compression_self_pct`) — v1's raw `ATR20/ATR90 < 0.70` fired on
  ~0.8 % of names (dead). v2 asks *"is this stock unusually quiet **relative to itself**?"*:
  the **self-percentile** of today's ATR20/ATR90 against that ratio's own last
  `compression_pct_lookback` (252) days — a per-stock **time series**, **not** the
  cross-sectional percentile the continuous score already uses. `compressed` =
  `compression_pct < 0.25`. Needs ≥ `compression_pct_min_obs` (60) observations, else neutral
  (`None`) — recent IPOs with a near-empty distribution never raise. On a real scan it fires
  on a non-degenerate fraction (~18 % of the price-eligible pool; lower on momentum survivors,
  which are structurally less compressed) vs v1's ~0.8 %.
- **Accumulation v2** (`_cmf` + `_updown_vol_ratio`) — v1's binary OBV-rising is fragile on
  gappy names. v2 = **20-day Chaikin Money Flow** (close location within each day's range ×
  volume) **AND** the **50-day up-day/down-day volume ratio**. Boolean `accumulation` =
  `CMF > 0` AND `ratio > 1`; the continuous **CMF** feeds the percentile score.

Continuous factors follow the active version: in v2, `f_atr_ratio` carries the compression
**self-percentile** (lower better) and `f_accum` carries **CMF** (higher better); in v1 they
carry the raw ATR20/ATR90 and the net directional-volume fraction. The factor **keys and
weights are unchanged** — only the values feeding them change.

## Tail-hunting profiles — Fusée & Phénix (`profiles.py`, Epic 2)

`profiles.py` is the **single source of truth** for the protocol v2 §3 definitions, shared by
production (`run_scan`, badges, alerts) and the study (Sprint 5). Thresholds live only in
`FILTERS["profiles"]`; a dedicated test asserts they equal the protocol values verbatim.

Memberships are **cross-sectional percentiles** computed per scan over the whole tradable pool
(all Pass A survivors), so the detector needs the full population — not a per-ticker rule:

- **Fusée** (momentum extreme): `rs63 ≥ P80` **AND** `perf_1m ≥ P80` (mapped to the existing
  `rs_strength` and `change_1m` signals). Event variant `fusee_event` = member **AND** a
  breakout `triggered` that day.
- **Phénix** (massacred, coiling, stabilizing): `pct_52w_high ≤ P20` **AND** `atr_ratio ≤ P40`
  **AND** `close ≥ SMA20` (the `sma20` stabilization gate).

`detect_profiles(signals)` mutates each signal in place, adding `is_fusee` / `is_phenix`
(bool), `fusee_strength` / `phenix_strength` (float | `None`, members only — the mean of the
member percentiles, oriented so *deeper = stronger*; the boolean SMA gate is excluded per §3),
`fusee_event`, `profiles` (list), `profile` (`"fusee"` | `"phenix"` | `"both"` | `None`) and
`profile_strength` (max, used for ranking display). Robust to an **empty universe** and to
**missing values** (a required field `None` → non-member). `rank_members` keeps only members,
sorted by `profile_strength`. Membership is boolean; strength is display-only, never part of
the pass/fail judgment.

## Setup vs trigger (`_breakout`)

Two distinct notions, so the screener can *watch beforehand* and *ping at departure*:

- **`setup_score`** — the current score (technical + fundamental), **logic unchanged**; a
  canonical alias of `score`. It says *"the spring is coiled"* (watchlist candidate). The
  original `score` field is kept as-is (the current UI reads it); `setup_score` equals it.
- **`triggered`** (bool) — the breakout is happening **now**: `close > pivot`
  (pivot = highest High of the last `pivot_window` days, **current session excluded**)
  **AND** today's volume `> trigger_vol_mult ×` the `trigger_vol_window`-day average volume.
- **`days_since_trigger`** — sessions since price crossed the pivot (breakout day = `0`);
  `None` when price is not above the pivot. `pivot_level` carries the pivot price.

`_breakout` is a pure function (offline-testable). These fields ride on every Pass A signal
set, so every candidate in the JSON/snapshots carries them.

## Distress markers — measured, never applied (Epic 9 S2)

Five markers, **two layers, two denominators**. They colour the dashboard
(`scoring.RISK_FLAGS` → `survival_risk`) and are archived in the dated snapshots; **none of
them enters selection, ranking or score** — a dedicated test fails if one ever does.

| Marker | Layer | Where computed | Available on |
|---|---|---|---|
| `sub_dollar_flag` / `sub_dollar_days` | price | Pass A (`sub_dollar_marker`) | whole universe |
| `reverse_split_flag` / `reverse_split_date` | price | Pass A (`_reverse_split_marker`) | whole universe |
| `dilution_flag`, `late_filing_flag`, `going_concern_flag` | filings | Pass B (`edgar.survival_signals`) | funnel survivors |

`sub_dollar_flag` is a **consecutive run**, not a touch: it needs `sub_dollar_min_days`
uninterrupted closes below `sub_dollar_price` within `sub_dollar_window`, mirroring the
listing rule. `sub_dollar_days` carries the run length — a raw boolean throws away the
gravity, counting one panic afternoon like six months of drifting below the floor.

Since Epic 10 S1 each served stock also carries **`risk_markers`**: the detail of the
markers actually raised, as `{code, level, date?, days?}` entries — codes and variables
only, translated by the frontend, never a display string built in the backend. Levels are
data (`scoring.MARKER_LEVELS`): `high` for going concern and share consolidation, `medium`
for upcoming issuance, `low` for late filing and sub-dollar price. A stock with no marker
carries an **empty list**, and the aggregate `survival_risk` boolean stays served unchanged
next to it. Dates come from data already fetched (filing dates, split date) — no extra
network call is ever made for them.

Filing markers are `None` when EDGAR is silent (unknown ticker, no User-Agent): a mute
sensor is never counted as a healthy name. `make flag-prevalence` reports prevalence per
layer, with a per-sector breakdown isolating biotechnology.

## Telegram alerts (`alerts.py`)

On each scan, `notify_new_v4_entries` and `notify_new_v5_entries` ping the names **newly
entering the v4 / v5 cohorts**. The original Fusée-breakout alert was removed in Epic 7 S2
(its trigger measured non-predictive; the v4 cohort alert replaced it). **Dedup**: a ticker
is not re-notified within `alert_dedup_days` (state persisted in `data/alerts_state.json`;
recorded **only on successful send**, so a failure/absent token retries next scan; the `v4:`
/ `v5:` state prefixes keep the two cohorts independent). Secrets come from env only
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) — **without them, alerting is silently disabled
and the scan runs normally**. Never fatal (wrapped in `run_scan`).

## Scoring — two modes (`FILTERS["scoring_mode"]`)

The scoring approach is **not settled** — it is a config flag, and a larger rolling
backtest is meant to decide it (the current small-sample backtest cannot). Both modes
use the same weights (`FILTERS["score_weights"]`) and are computed in `_score_candidates`.

- **`"binary"` (default)** — the original "checkbox" score (`_binary_score`): each signal
  adds fixed points, normalized to 0–10. Known and conservative, but historically **caps
  around 8** (v1 compression fired on ~1/146 names; **sensors v2 relaxes this** — compression
  now fires on a non-degenerate fraction).
- **`"continuous"`** — standard quant factor scoring: each factor is a **continuous** value,
  **percentile-ranked across the candidate set** (`_rank_pct`), combined into a weighted
  average (`_factor_composite`), then mapped to a **decile 0–10** so the best of the day's
  pool = 10. Fixes the scale and loses no information, but its edge is **not yet validated**.

Selection of which survivors get enriched follows the same mode (`_select_scores`).

**Technical factors** (Pass A; `TECH_FACTORS`; used to rank which survivors get enriched):

| Factor (continuous) | Weight | Direction |
| --- | ---: | --- |
| `f_accum` — v2: **CMF** (∈[-1,1]); v1: net directional volume fraction | 4 | higher better |
| `f_atr_ratio` — v2: compression **self-percentile**; v1: ATR20 / ATR90 | 2 | lower better |
| `f_pct_recent` — proximity to recent-base high | 2 | higher better |
| `f_ext` — price/MA50 − 1 (extension) | 2 | lower better |
| `f_rs` — relative-strength magnitude vs IWM | 2 | higher better |

**Fundamental factors** (Pass B; `FUND_FACTORS`): **`insider_net_buying`** (2 — net Form 4
purchases $, see Insiders), `cash_bin` (1), `revenue_growth` (1), `float_shares` (1, lower
better), `short_interest_pct` (1).

The two factor tables above are the **continuous-mode** factors. In continuous mode the
final `score` is computed **cross-sectionally over the candidate set** in `run_scan` (a
percentile needs the population). In **binary mode** (the default) the score instead comes
from `_binary_score` (`_tech_rules` + `_fundamental_rules`, the boolean signals). Selection
(`_select_scores`) follows the active mode. Candidates are sorted by `(score, rs_strength)`.

> The backtest (`backend/backtest.py`) scores the same survivors **both ways** and prints
> the two quartile tables side by side, so the mode can be chosen on evidence once the
> sample is large enough. At small survivor counts the two are statistically indistinguishable.

## Pass B — fundamentals (`enrich_ticker`)

Hard filters: exchange, market-cap band. Fundamentals: `cash_positive` (`None` when missing — not penalized), insider net buying (see below), short interest, revenue growth, `float_shares`/`low_float`, `ipo_year`. The EDGAR layer is unchanged whatever the source: same functions, same 24 h cache, same SEC throttle — it just now applies to every enriched candidate.

**Two sources, one switch (`enrich_source`, Epic 13 S2).** `enrich_ticker(ticker, signals, info=None)` does the same work either way — only where `info` comes from changes:

- **`yahoo` (code default)** — `info=None` → `_fetch_info` per ticker: retries + exponential backoff on `YFRateLimitError`, small `enrich_workers` pool and per-call jitter (Yahoo rate-limits `.info` and **bans the IP** if hammered). That per-ticker cost is what `enrich_max` bounds, and what made the funnel drop everything past the cutoff as `below_cutoff` without examining it.
- **`finviz` (local config)** — **one** export call at the start of Pass B (`finviz.snapshot()`), then each candidate reads its dict from the snapshot: **zero Yahoo fundamental call**, no jitter. Cost no longer scales with the number of candidates, so `enrich_max_snapshot` becomes a valve — `null` lifts it and `below_cutoff` disappears from this path.
- **Fallback, never fatal** — export unreachable or snapshot empty ⇒ logged switch back to the Yahoo path **within the same scan**, back under `enrich_max` (the fallback must never fire hundreds of `.info` calls). A candidate **missing from the snapshot** gets an empty dict, i.e. the existing missing-data path (no exchange → rejected), never an exception.

Logging is console-only (source, snapshot size, fallback) — none of it reaches the payload, and the served contract is identical on both paths.

## Finviz export client (`finviz.py`, Epic 13)

`snapshot()` fetches the Finviz Elite screener CSV export in **one authenticated request** and
parses it into `{TICKER: {…}}` whose keys are **the yfinance `.info` keys `enrich_ticker` reads**.
Pass B therefore reads a snapshot instead of calling Yahoo per ticker without a single line of the
enrichment body changing (Sprint 2 wired it — see the switch above).

- **Never fatal**: missing token, dead network, unreadable CSV, empty cell → `None` (or a `None`
  field), never an exception. The Sprint 2 fallback to the Yahoo path leans on exactly that.
- **Token**: `finviz:` section of `config/local.yml` (gitignored), read by the module itself.
  Code defaults are neutral (`export_url: ""`, `token: ""`) → module inactive, no request attempted.
  The token is never printed: a network error logs the exception **type** only, because `requests`
  copies the whole URL — hence the token — into its own message.
- **Enabling it** (Sprint 2 registered the section, so `load_local_config` no longer rejects it):
  add `finviz: {export_url, token}` **and** `filters: {enrich_source: finviz, enrich_max_snapshot: null}`
  to `config/local.yml`. **Verify one known market cap on the first real call before trusting the
  switch**: `Market Cap` is assumed to carry a `K`/`M`/`B` suffix, and a cap served in millions
  *without* one would be read as absolute dollars (412.5M$ → 412$), silently emptying the
  market-cap band. Everything about the export is proven on a recorded fixture, never against a
  live response. One command tells you, without printing the token:

  ```bash
  docker compose exec -T backend python -c "import finviz, statistics; s = finviz.snapshot(); \
    caps = [d['marketCap'] for d in (s or {}).values() if d['marketCap']]; \
    print(len(s or {}), 'rows · median cap', f'{statistics.median(caps):,.0f}')"
  ```

  A small/micro-cap universe must show a median in the **hundreds of millions**. A median in the
  hundreds means the suffix is missing and the switch must not be enabled.

### Correspondence table — export column → enrichment contract

Single source: `FIELD_MAP` in `backend/finviz.py`. Percentages arrive as text with a `%` sign and
become **fractions** (the contract's unit); market caps and share counts carry `K`/`M`/`B`/`T`
suffixes and become **absolute values**; dates become **epoch seconds UTC** (midnight). An empty
cell or `-` yields `None`.

| Finviz column | Contract key (`.info`) | Normalisation |
|---|---|---|
| `Company` | `shortName` | text |
| `Sector` | `sector` | text |
| `Industry` | `industry` | text |
| `Exchange` | `exchange` | market name → yfinance code (see below) |
| `Market Cap` | `marketCap` | suffix → absolute USD |
| `Float` | `floatShares` | suffix → absolute share count |
| `Float Short` | `shortPercentOfFloat` | `%` text → fraction |
| `Insider Ownership` | `heldPercentInsiders` | `%` text → fraction |
| `Sales Q/Q` | `revenueGrowth` | `%` text → fraction (quarterly YoY sales growth) |
| `Earnings Date` | `earningsTimestampStart` | date → epoch s UTC |
| `IPO Date` | `firstTradeDateEpochUtc` | date → epoch s UTC |

Contract fields with **no direct equivalent** in the export are always present and `None` —
neutral, never penalising (`UNMAPPED`): `longName` (the export has a single name column, served as
`shortName`), `earningsTimestamp` (the contract's fallback key; the primary one is enough), and
`totalCash` / `totalDebt` (the export carries ratios, not absolute balance-sheet values, so
`cash_positive` stays `None` — the existing "missing data is not penalised" path).

**Exchanges** are the one non-trivial translation: Finviz *names* markets, yfinance *codes* them and
`FILTERS["allowed_exchanges"]` compares codes, so a raw string comparison would reject the whole
universe. `EXCHANGES` maps `NASDAQ`/`NASD` → `NMS`, `NYSE` → `NYQ`, `AMEX`/`NYSE American` → `ASE`.
The export does not distinguish the three NASDAQ tiers, so all of them map to the main-tier code,
which is in the allowed set. An unknown market → `None` → rejected by the existing exchange filter,
exactly like `AMEX` today.

## Insiders — net Form 4 purchases (`edgar.py`, Sprint 5)

The scored insider signal is **net open-market purchases**, not ownership %. `net_insider_buying(ticker)`
maps the ticker → CIK (SEC `company_tickers.json`), reads the recent filings list
(`data.sec.gov/submissions/CIK…json`), parses each **Form 4** and sums the **open-market
buys minus sells** (`insider_net_buying` = Σ code-`P` $ − Σ code-`S` $) over
`insider_window_days`, filtered by **transaction date** (dated → point-in-time reusable by
the Sprint 6 backtest). Award/option/tax codes (`A`/`M`/`F`/`G`…) are ignored.

- **Score**: the insider point is awarded on `insider_net_buying_pos` (`net > 0`); the
  continuous factor is `insider_net_buying` ($). The old `insider_pct` (`heldPercentInsiders`)
  is **kept for display only** — no longer scored.
- **SEC compliance**: identifying `User-Agent` from **`EDGAR_USER_AGENT` env** (email); without
  it EDGAR is **disabled → signal `None`** (neutral, non-penalizing, scan still completes).
  Global throttle ≤ 10 req/s. Local cache (`data/edgar_cache/`): submissions have a TTL,
  **filings are immutable and never re-downloaded** → a second scan makes no repeat EDGAR call.
- Called only on the enriched Pass B survivors, so cost stays bounded by the enrichment cap in
  force (`enrich_max`, or `enrich_max_snapshot` on the snapshot path — where lifting the valve
  multiplies EDGAR lookups accordingly; the throttle and the 24 h cache are what bound them).
  Never fatal (wrapped in `enrich_ticker`).

## Orchestration — `run_scan(tickers=None)`

Discover (full universe, no sampling) → `_download_prices` → **Pass A** (tradability hard path + signals + trigger) → **`detect_profiles` over the whole tradable pool → keep profile members only, ranked by `profile_strength`** (in `legacy`: rank the whole pool by technical composite instead) → keep top `enrich_max` (on the snapshot path: `enrich_max_snapshot`, `null` = all of them) → **Pass B** (`.info` per ticker, or one export snapshot) → **`_score_candidates` (decile 0–10)** → set `setup_score` alias (kept for continuity, no longer drives selection) → sort by profile strength → write `/app/data/screener_data.json` → **`notify_new_v4_entries` / `notify_new_v5_entries`** (Telegram, best-effort). `scan_state` (`scanning`/`progress`/`total`/`phase`) is shared with `api.py`.

## Output JSON

Top-level: `scanned_at`, `universe_size`, `total_scanned`, `survivors_price_filter` (tradable pool), **`profile_members`**, **`pool_mode`**, `enriched`, `candidates`, `stocks`, `rejection_stats`. Each stock carries the Pass A signals plus `ticker`, `name`, `sector`, `industry`, `exchange`, `market_cap_m`, fundamentals, `score`, **`setup_score`, `triggered`, `days_since_trigger`, `pivot_level`**, the **profile fields `profile` / `is_fusee` / `is_phenix` / `fusee_event` / `fusee_strength` / `phenix_strength` / `profile_strength`**, the v2 sensor diagnostics **`compression_pct` / `atr_ratio` / `cmf` / `updown_vol_ratio`** (plus `sma20`), the insider fields **`insider_net_buying` / `insider_net_buying_pos`** (net Form 4 $, scored) and `insider_pct` / `insider_buying` (display only), `positives`, `flags`, the **context fields `binary_event` / `days_to_earnings` / `earnings_date`** (Epic 1 S7 — information only), and `catalyst_type`/`catalyst_date` (`null`). In `tradability` mode every stock is a **profile member**; non-members are absent. Snapshots (`data/history/`) also carry `setup_score` / `triggered` / `days_since_trigger` and the profile fields (for the Sprint 4 two-sleeve tracker).

## Backtest harness — `backend/backtest.py`

Replays `analyze_prices` at a past as-of date and compares forward returns of survivors vs
the tested universe vs IWM, **bucketed by score quartile**, showing the continuous and the
binary score side by side (does a higher score predict a higher forward return, and does
one scoring beat the other?).

```bash
DATA_DIR=/tmp/bt PYTHONPATH=backend python backtest.py --n 200 --forward 63 --seed 42
```

**Honest limitations:** survivorship bias, no point-in-time fundamentals (validates
price/volume signals only), a single as-of window. At ~14 survivors this is a control
run, not a verdict: the backtest cannot confirm an edge or that continuous beats binary.

The v1/v2/v3 study harnesses and the weight sweep were removed (Epic 7 S1) — the three
theses failed their pre-registered studies and re-fitting is forbidden. Their verdicts
live in `backtest_protocol_v2.md` / `_v3.md`, their code in git history.

## Tests

```bash
DATA_DIR=/tmp/screener_test PYTHONPATH=backend python -m pytest backend/tests/
```

Deterministic, offline. The module honors `DATA_DIR` so it imports outside the container.

## Context flags (Epic 1 S7)

Two flags tell the reader that a technical signal reads differently on this name. They are
**information only** — never an exclusion, never a scoring input, never a change to the
ordering. Both are read from the `.info` payload already fetched, so they cost **no extra
network call** (Yahoo bans the IP on bursts — see `enrich_workers`).

| Flag | Source | Meaning |
| --- | --- | --- |
| `binary_event` | `industry` then `sector` matched against `FILTERS["binary_event_industries"]` | Biotech / pharma: a regulatory decision or trial result moves the price tens of percent in one session, whatever the chart says. A stock-specific fall means something else here. |
| `days_to_earnings` / `earnings_date` | `earningsTimestampStart`, then `earningsTimestamp` | Days until the next earnings date **and that date (ISO)**, both `None` when absent or past. Flagged under `FILTERS["earnings_soon_days"]`; the flag carries both — the countdown goes stale the day after the scan, the date does not. |

`days_to_earnings` is **best effort**: yfinance only carries the date for part of the
micro-cap universe. A missing date is silent — never an error, just one flag fewer. The
count is a difference of **calendar dates**, so "three days minus two hours" reads as 3.

Both flags are emitted as **codes plus variables** (`{"code": "earnings_soon", "d": 3}`) and
translated by the frontend, like notes and statuses since Epic 8 S1. Legacy flags are still
French sentences built here; the JSX accepts both shapes during the transition.
