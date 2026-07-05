# Backtest Protocol v2 — Tail Hunting (Fusée & Phénix)

**Status: pre-registered draft — becomes binding once committed to `main` (Epic 2, Sprint 1),
BEFORE any implementation or run of the v2 study.** Changing definitions, metrics or success
criteria after seeing results is forbidden. Supersedes `backtest_protocol.md` (v1) for the new
thesis; v1 remains the record of the previous thesis and its verdict.

## 0. Why a v2 — the verdict that killed v1

The v1 study (pre-registered, full universe, 3y) failed its own criteria: **all ten score
deciles were negative in cost-adjusted excess of IWM**, both horizons, every year. Diagnosis
(2026-07-02/03, in-sample, documented in the "Rapport Fable" Notion page):

- The micro-cap segment itself matched IWM; **the thesis hard filters selected relative losers**
  (−2%/21d, −5%/63d vs own universe, every year).
- The stated product goal was never "beat IWM on average" but **catch stocks about to explode**
  (+50% / +100%). Measured on that goal, the v1 filters **halved** the explosion rate.
- Explosions live at the **extremes** the v1 screener excluded: far below the 52-week high
  (lift ≈ 2.5×), and at both momentum extremes (crashed ≈ 1.8×, very hot ≈ 1.5×). The
  "reasonable middle" (moderate perf, near MA50, rising trend, accumulating) is the dead zone
  (lift ≈ 0.4×). CMF accumulation showed **no** tail enrichment.

## 1. Objective & metrics (pre-registered)

Maximize capture of the right tail on the **tradable** universe, with the left tail priced in.

- **Primary metric**: lift of `P(fwd63 ≥ +100%)` and `P(fwd63 ≥ +50%)` for profile members vs
  the tradable-universe base rate at the same dates.
- **Guard metric**: `P(fwd63 ≤ −50%)` for profile members vs base (left tail must not blow up).
- **Decision metric**: mean net expectancy per ticket (`fwd63 − 1%` round-trip cost), which
  must be positive — a lift eaten by crashes fails.
- Secondary horizon: 21d, reported but not decisive.
- Granularity: judged at **profile-membership level** (hundreds of obs), never on top-20 lists
  (no statistical power there; live tracker judges short lists over time).

## 2. Universe & data

- Tradable universe only: price ≥ 2 USD, median dollar-volume ≥ 1 M USD/day (non-negotiable —
  the sub-threshold "illiquidity premium" corner is not harvestable).
- **No thesis hard filters.** Profiles do the selecting.
- Data: yfinance daily OHLCV, current listings → **survivorship bias present and handled in §5**.

## 3. Frozen profile definitions

Cross-sectional percentiles computed per as-of date within the tradable universe. These
definitions are the SINGLE SOURCE OF TRUTH: the production detectors (badges, alerts) and the
study MUST share the same code.

- **Fusée (momentum extreme)** — primary:
  `rs63 ≥ 80th percentile` AND `perf_1m ≥ 80th percentile`.
  Event variant (reported alongside): primary AND breakout trigger that day
  (close > 50d pivot on volume ≥ 1.5× 50d average — the Sprint 3 trigger).
- **Phénix (massacred, coiling, stabilizing)** — primary:
  `pct_52w ≤ 20th percentile` (far below its 52-week high) AND
  `atr_ratio ≤ 40th percentile` (volatility compressed) AND
  `close ≥ SMA20` (first stabilization sign).
- Membership is boolean; a per-profile continuous strength (mean of the member percentiles) is
  computed for ranking display only — it is NOT part of the pass/fail judgment.

## 4. Windows — exploration vs validation

- **Exploration (already spent)**: 2023-07 → 2026-06 (the 3y used by every diagnostic above).
  Nothing can be validated on it; it may only be re-reported for context.
- **Validation A (backward out-of-sample)**: 2021-07 → 2023-06 (5y download, judged once).
  Caveat: survivorship bias worsens further back — §5 sensitivity applies.
- **Validation B (forward, unbiased)**: the live tracker (`/api/performance`) with per-profile
  sleeves, ≥ 3 months of real selections.
- **Full pass requires A and B to agree.** A alone = "provisional pass".

## 5. Survivorship handling (the Phénix problem)

- Every report prints a **break-even hidden-delisting rate**: the fraction of profile members
  that would need to have gone to −100% (invisible today) to erase the measured lift. If that
  rate is plausibly low (< 5%), the lift is declared fragile regardless of other numbers.
- **Phénix is money-gated**: no real capital on Phénix until its lift is re-measured on
  delisted-inclusive data (Norgate/Sharadar, ~30–80 USD/mo — separate purchase decision).
  Fusée (short holding windows on hot, liquid names) is judged with yfinance data.

## 6. Pre-registered success criteria (validation windows only)

Per profile, on Validation A and then B:

1. `lift P(fwd63 ≥ +100%) ≥ 1.4×` with a bootstrap 95% CI excluding 1.0×;
2. mean net expectancy per ticket > 0;
3. `P(fwd63 ≤ −50%) ≤ 1.5×` the tradable base rate.

Decision rule:
- Fusée passes A+B → Fusée sleeve goes live for real tickets.
- Fusée fails → the momentum-tail sub-thesis is dropped; **no consolation re-fitting** on the
  same data.
- Phénix passing A+B yields only a **conditional pass** ("pending delisted-data confirmation");
  its criteria are re-judged after the data purchase, or it stays research-only.

## 7. Costs, capacity, sizing reality

- 1% round-trip haircut on every ticket; capacity: position ≤ 1% of daily dollar-volume.
- Base-rate math kept in every report: at ~1–2% doubling rate per quarter, 10 tickets/quarter
  ≈ one double per year; zero-double years are statistically normal. Each ticket must be sized
  to survive −50%.

## 8. How to run

```bash
# Validation A (run ONCE, after this protocol is merged):
DATA_DIR=/tmp/bt2 PYTHONPATH=backend python backtest.py --study-v2 --period 5y

# Validation B: accumulate live scans; /api/performance reports per-profile sleeves.
```

The study lives in `backend/backtest.py` (`run_study_v2`). It reuses the production
detectors verbatim (`profiles.detect_profiles`) on the tradable pool
(`analyze_prices` in `pool_mode="tradability"`) — **no membership logic is duplicated**
(protocol §3). Per as-of date it labels the full cross-section, then measures, per
profile × window: the +50 %/+100 % tail lifts with bootstrap 95 % CI, the ≤ −50 % left-tail
guard, mean net expectancy (−1 % round-trip), the break-even hidden-delisting rate (§5),
and the explicit PASS/FAIL/CONDITIONAL verdict against §6. The +50 %/+100 % thresholds, the
two windows, and the §6 criteria are frozen module constants in `backtest.py` (not tunable —
outside `FILTERS`, like the tracker's tail thresholds).

## 9. Run log — Validation A (judged ONCE)

Validation A is executed a single time on the merged study code; its verdict is recorded
here verbatim and never re-fitted. Any change to definitions after seeing this is a protocol
revision + new epic decision (§6), not a rerun.

<!-- VALIDATION_A_RUNLOG -->
- **Status**: run launched on `feat/study-v2` (Epic 2 Sprint 5), 2026-07-05, full tradable
  universe, `--period 5y`. Verdict table below is filled from that run's report output.
- **Command**: `DATA_DIR=/tmp/bt2 PYTHONPATH=backend python backtest.py --study-v2 --n 0 --period 5y`
- **Commit**: _(study code commit hash — filled in the run-log commit)_

| Profile | fwd63 lift ≥+100× (CI95) | net expectancy | left-tail guard | break-even delisting | Verdict §6 |
|---|---|---|---|---|---|
| Fusée | _pending run_ | | | | |
| Phénix | _pending run_ | | | | |

The exploration window (2023-07 → 2026-06) is re-reported by the same command for context
only — **in-sample, spent**, never part of the verdict.
<!-- /VALIDATION_A_RUNLOG -->
