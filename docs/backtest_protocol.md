# Backtest Protocol — the study (Sprint 6)

**Status: pre-registered.** This protocol is committed **before** the first full study run.
It is the measuring instrument that — and it alone — authorizes the Sprint 8 calibration.
Changing the success criteria *after* seeing results is forbidden (that would be overfitting).

## 1. Purpose

Measure whether the screener's **score predicts forward returns** across the full US small/
micro-cap universe, with significance tests, transaction costs, and an anti-overfitting split.
The study **measures**; it does not tune. Weight calibration is Sprint 8 and is allowed **only
if** the validation-half criteria below are met.

## 2. Data & universe

- **Universe**: the full eligible pool from `discover_tickers()` (NASDAQ + NYSE + AMEX,
  small + micro cap — Sprint 1). No random sampling.
- **History**: ~3 years of daily OHLCV per ticker (`--period 3y`), batch-downloaded.
- **Cross-sections**: one as-of date every `study_step_days` (21 ≈ monthly) over the period.
- **Target size**: thousands of (date, ticker) observations.

## 3. Method — rolling cross-section

At each as-of date `t` (data known at `t` only, history truncated to `≤ t`):
1. Apply the hard filters + compute the score via **`analyze_prices`** (same code as live —
   no duplicated signal logic).
2. Record, per surviving ticker: `date`, `ticker`, continuous & binary scores, per-factor
   values, `dollar_volume`, and forward returns at **21d and 63d**, plus IWM's return over the
   same window.
3. Excess return = ticker forward return − IWM forward return over the identical window.

## 4. Statistics

- **Information Coefficient (IC)**: Spearman rank correlation `score → forward return`,
  computed **per date**, then averaged with a **t-stat** over the date series.
- **Non-overlapping windows for the t-stat** (non-negotiable): the IC series feeding the
  t-stat uses dates spaced **≥ horizon** (`no offset < horizon`) so the windows do not overlap
  (e.g. for the 63d horizon, keep every 3rd monthly date). Overlapping windows inflate `t`.
- **Decile table**: deciles by score assigned **within each date**, returns pooled per decile,
  reported **in excess of IWM**; **D10 − D1** spread; fraction of months with `D10 > D1`.
- **Medians alongside means** everywhere (small caps are fat-tailed).
- **Per-year breakdown** of the edge.
- **With and without costs** (see §5), side by side.

## 5. Transaction costs & capacity

- **Round-trip haircut**: −`study_cost_roundtrip` (1%) subtracted from every position's
  forward return for the "net" figures.
- **Capacity filter**: assume a notional position of `study_position_usd` ($10k). Exclude any
  (date, ticker) whose position would exceed `study_adv_max_frac` (1%) of that name's daily
  dollar-volume — i.e. drop obs where `dollar_volume < study_position_usd / study_adv_max_frac`.
  At the defaults this floor is $10k / 1% = **$1M**, i.e. identical to the existing hard
  liquidity filter (`dollar_vol_min`) — so it is a **no-op at defaults**; raise
  `study_position_usd` to make the capacity constraint bite.

## 6. Baselines — the composite must beat

- **(a) Random pick among survivors**: the top-decile net excess must beat the mean survivor
  net excess (a random survivor).
- **(b) Best single factor**: the composite IC must beat the best single-factor IC.
- **(c) Sensors v1 vs v2** and **binary vs continuous**: reported side by side.

## 7. Anti-overfitting protocol

- **Split by date**: **calibration = first half** of the as-of dates; **validation = second
  half**. The validation half is scored **once** (no iterating against it).
- **Pre-registered success criteria** (indicative, decided here, before any run):
  - mean **IC > 0.03** with **t > 2** (on non-overlapping dates), on the validation half;
  - **D10 > D1** in **≥ 60 %** of validation months;
  - **top decile net of costs > IWM** on the validation half.
- **Decision rule**: Sprint 8 may calibrate weights **only if** the validation half meets the
  criteria. If not, the screener stays as-is and the thesis is revisited — no fishing.

## 8. Survivorship bias (documented in every report)

The universe is **today's** listed names; delisted/acquired tickers are absent. Reported edges
are therefore an **upper bound** — real forward performance would be lower. Every generated
report prints this warning. This study measures the **price/volume** signals only. Point-in-time
fundamentals are not replayed; the dated EDGAR insider data (Sprint 5) is replayable in
principle but is **not** included here (future extension).

## 9. How to run

```bash
# Full study (slow — whole universe × 3y). Protocol committed BEFORE this is run.
# --n 0 = no cap (full universe).
DATA_DIR=/tmp/bt PYTHONPATH=backend python backtest.py --study --n 0 --period 3y

# v1-vs-v2 sensors: run twice, toggling FILTERS["sensors_version"].
# Bounded smoke run (machinery check)
DATA_DIR=/tmp/bt PYTHONPATH=backend python backtest.py --study --n 150 --period 2y
```
