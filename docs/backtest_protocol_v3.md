# Backtest Protocol v3 — Survival-Conditioned Right-Tail Scoring

**Status: pre-registered DRAFT — becomes binding once committed to `main` AND signed off by the
project owner, BEFORE any judged run of the v3 study.** Changing the feature set, model class,
hyperparameter grid, validation scheme, metrics or success/kill criteria after seeing any
out-of-fold result is forbidden. Supersedes `backtest_protocol_v2.md` (tail-hunting profiles) for
the new thesis; v1 and v2 remain the record of the previous theses and their verdicts.

> ⚠️ **This protocol cannot self-approve.** The whole value of pre-registration is that a human
> fixes the criteria before results exist. The v3 study (`--study-v3`) is implemented freely, but
> **it is not executed for judgement until this document is signed off.** Until then, any run is a
> dry-run for plumbing only, and its numbers are non-binding.

## 0. Why a v3 — the verdicts that killed v1 and v2

Two pre-registered theses have failed, for two *different* reasons (both documented, both judged
once):

- **v1** (accumulation + healthy start): selected the **dead middle of the U** — all ten score
  deciles negative in cost-adjusted excess of IWM, every year. CMF accumulation showed no tail
  enrichment. Wrong region entirely.
- **v2** (Fusée / Phénix tail profiles): selected the **right regions** (the extremes) but caught
  the whole distribution there — a fat right tail AND a fat left tail. Fusée had no out-of-sample
  lift (`P(fwd63≥+100%)` **1.03×**, CI [0.46, 1.71]). Phénix had a large, real right-tail lift
  (**4.59×**) but a **barbell eaten by the left tail** (≤−50% guard **2.27×** over the 1.5× cap,
  net expectancy **−11%**). Both FAIL (`backtest_protocol_v2.md` §9-§10).

**The lesson that defines v3:** the right tail is already *found* — Phénix concentrates explosions
4.6×. The failure is (a) not dying (left tail) and (b) not being able to measure it (survivorship
bias flatters exactly the distressed profile). The lever is no longer in price. It is in
**fundamental survival information the price does not contain**, and in an **honest measurement
discipline** given that we are constrained to free, survivor-biased data.

## 1. Objective & metrics (pre-registered)

Score the tradable universe by an estimated, calibrated **probability of a right-tail move,
conditioned on survival**, and select the top of that distribution — keeping the left tail priced
in. The product principle is unchanged: a short daily list, one prominent per-stock indicator.

- **Label**: `y = 1` if `fwd63 ≥ +100%`, else `0` (decisive). `fwd63 ≥ +50%` and `fwd63 ≤ −50%`
  are tracked alongside for lift and left-tail guard.
- **Model output**: `p_hat = P(y=1 | features known at t)`, isotonic-calibrated.
- **Primary metric**: lift of `P(fwd63 ≥ +100%)` in the **top decile of `p_hat`** vs the tradable
  base rate at the same dates, with a bootstrap 95% CI.
- **Decision metric**: mean **net expectancy** per ticket in the top decile (`fwd63 − 1%`
  round-trip), which must be positive — a lift eaten by crashes fails.
- **Value-of-survival metric** (the crux of v3, see §7): net expectancy of the top decile WITH the
  survival features minus the same WITHOUT them (technicals only). The new information must earn
  its place.
- **Guard metric**: `P(fwd63 ≤ −50%)` in the top decile vs base.
- Secondary horizon: 21d, reported, not decisive.
- **Granularity**: judged on the pooled out-of-fold predictions across the purged walk-forward
  (thousands of obs), never on top-20 lists — no statistical power there; the live tracker judges
  short lists over time.

## 2. Universe & data — and the free-data ceiling

- **Tradable universe only**: price ≥ 2 USD, median dollar-volume ≥ 1 M USD/day (non-negotiable;
  the sub-threshold illiquidity corner is not harvestable). Same pool as v2 (`analyze_prices` in
  `pool_mode="tradability"`).
- **Data**: yfinance daily OHLCV (price/return features) + SEC EDGAR filings (survival features,
  §3). **Current listings only** — survivorship bias is present and handled in §6.
- **Decision (project owner, 2026-07-05): no delisted-inclusive data will be purchased.** This is a
  hard constraint, not a deferral.

> **The free-data ceiling — REFUTE-ONLY rule.** Survivor-only data undercounts the left tail (the
> −100% delistings are gone). Therefore every expectancy computed here is an **optimistic ceiling**.
> Consequence, pre-registered: **the backtest can only REFUTE, never confirm.** A result that meets
> the criteria is "not yet refuted" — provisional — and can only be *validated forward* by the live
> tracker (§5, Validation B). A result that fails the criteria *even on this optimistic data* is
> **refuted for good**. The dashboard badge stays permanently "non validé" on backtest evidence
> alone.

## 3. Frozen feature set (SINGLE SOURCE OF TRUTH)

Exactly the features below, computed **point-in-time** on data known at each as-of date `t`,
cross-sectionally within the tradable universe. Production scoring and the study MUST share the
same code (as `profiles.py` did for v2). **Adding, removing or redefining a feature is a protocol
revision — never a mid-study tweak.**

**A. Technical / region features** (from price; univariate right-tail lift established in v1/v2
diagnostics):

| # | Feature | Rationale |
|---|---|---|
| T1 | `pct_52w_high` — distance below the 52-week high | far-below-high had the strongest univariate lift (≈2.5×) |
| T2 | `rs63` — 63d relative strength vs IWM | momentum tail (both ends of the U) |
| T3 | `change_1m` — 1-month price change | momentum tail |
| T4 | `atr_ratio` — ATR20/ATR90 | volatility compression (coiling) |
| T5 | `vol_expansion` — recent volume / 50d average | breakout confirmation |
| T6 | `close_vs_sma20` — close / SMA20 − 1 | first stabilization sign |

**B. Survival features** (from EDGAR, new in v3 — the information the price does not contain; these
are our only window onto the otherwise-invisible left tail):

| # | Feature | Signal |
|---|---|---|
| S1 | `dilution_flag` — recent S-3 / 424B / ATM / shelf registration | new share issuance ahead |
| S2 | `reverse_split_flag` — recent reverse split (8-K / share-count contraction) | distress / delisting-compliance move |
| S3 | `going_concern_flag` — going-concern language in latest 10-Q/10-K | bankruptcy risk |
| S4 | `cash_runway` — cash / quarterly burn (quarters of runway) | solvency (may be sparse → neutral when missing) |
| S5 | `sub_dollar_flag` — price recently < 1 USD | Nasdaq minimum-bid non-compliance |
| S6 | `late_filing_flag` — recent NT 10-Q / NT 10-K | reporting distress |
| S7 | `insider_net_buying` — net open-market Form 4 buying (reuse Epic 1 S5) | informed money |

Missing/unavailable survival feature → **neutral**, never penalizing (a missing filing is not a bad
filing). All survival features are dated and cached (§ edgar module), reusable point-in-time by the
study with no look-ahead.

## 4. Frozen model class & hyperparameter grid

Degrees of freedom are the enemy after two overfitting-adjacent failures. Locked before any run:

- **Primary model**: **L2-regularized logistic regression** on cross-sectionally standardized
  features (percentile ranks within each as-of date). Interpretable, low-variance, coefficients
  readable. This is the model that is judged.
- **Hyperparameter grid** (the ONLY tuning allowed): inverse-regularization `C ∈ {0.03, 0.1, 0.3,
  1.0}`, `class_weight="balanced"` (fixed). `C` selected by **inner** purged-CV log-loss (nested;
  §5) — never on the outer evaluation folds.
- **Calibration**: isotonic regression fit on inner-fold out-of-sample predictions only.
- **Secondary model (appendix, NON-decisive)**: a monotonic-constrained gradient boosting model may
  be reported for context, but the verdict is rendered on the primary logistic model. A better GBM
  number never overturns a logistic FAIL (that path is how one fishes).
- **No deep learning, no unconstrained tree ensembles, no AutoML, no feature search.** The feature
  set (§3) and this grid are the whole search space.

## 5. Validation scheme — purged walk-forward with embargo

No virgin historical window remains (exploration 2023-07→2026-06 and Validation A 2021-07→2023-06
are both spent). Decision (project owner, 2026-07-05): **purged k-fold walk-forward with embargo**
(López de Prado), plus the live tracker as the incorruptible forward judge.

- **As-of grid**: monthly (`study_step_days = 21`) over the full free-data period (~5y download).
- **Purged k-fold** (`K = 5`, contiguous time folds): when a fold is the test set, **remove from
  training every observation whose 63-day label window overlaps the test span, plus an embargo of
  `E = 73` trading days** (63d horizon + 10d buffer) on each boundary. This kills label leakage
  across the train/test seam.
- **Nested**: hyperparameter `C` and the isotonic calibrator are chosen on an **inner** purged split
  of the training folds only; the outer fold is touched once, for evaluation.
- **Per-regime reporting**: each fold is additionally labelled by market regime (sign of trailing
  IWM 63d return) and metrics are broken out by regime — v2 failed partly because a single bear
  window (2022) judged it. Regime fragility must be visible, not hidden in an average.
- **Honest limitation, pre-registered**: walk-forward re-uses data the researcher has already seen.
  Purge + embargo remove statistical leakage, not researcher familiarity. Mitigations: the frozen
  §3/§4 search space, and — decisive — **Validation B, the live tracker** (`/api/performance`),
  which scores genuinely unseen forward data. **A backtest pass is provisional until the live
  tracker agrees over ≥ 3 months.**

## 6. Survivorship handling

- Free, survivor-only data (§2). Every report prints, per baseline and per model:
  - the **break-even hidden-delisting rate** (fraction of top-decile names that would need to be
    invisible −100% losses to erase the measured lift; < 5% ⇒ declared fragile), and
  - the count/fraction of top-decile names carrying each survival red flag (§3.B) — the model's
    *reconstruction* of the invisible left tail from the filing side.
- **Why the survival features partly repair the bias**: the −100% names are gone from the price
  data, but the EDGAR distress signals that *precede* delisting are still visible on the names that
  nearly died. The survival veto is therefore under-credited on survivor data (§7 exploits this).

## 7. Pre-registered success & kill criteria (out-of-fold, pooled)

Judged on the pooled out-of-fold predictions of the **primary logistic model** (§4), on the
**decisive fwd63 horizon**, top decile of `p_hat`:

1. **Ranking power** — `lift P(fwd63 ≥ +100%) ≥ 1.4×` the tradable base, bootstrap 95% CI
   excluding 1.0×.
2. **Value of survival (the crux)** — top-decile net expectancy WITH survival features (§3.B)
   exceeds the same model WITHOUT them (technicals §3.A only), by a margin whose bootstrap 95% CI
   excludes 0, AND the improvement holds in **≥ 4 of 5** outer folds. Rationale: on optimistic
   survivor data the veto is *under*-credited (§6); if it helps even here, it helps more in
   reality; if it does not help here, it never will.
3. **Left-tail guard** — top-decile `P(fwd63 ≤ −50%) ≤ 1.5×` base.
4. **Beats baselines** — top-decile net expectancy beats (a) random tradable picks, (b) the best
   single feature, and (c) v2 Phénix-raw membership.
5. **Calibration** — reliability curve + Brier score reported; `p_hat` not materially
   over-confident (top-decile realized rate within the top-decile predicted range).

**Decision rule:**
- All of 1–5 hold → **provisional pass** ("not yet refuted"). The score goes live in the dashboard
  with a permanent "non validé" badge (§2 ceiling); the live tracker (Validation B) is the only
  path to a real confirmation.
- **Kill criterion — criterion (2) fails** (survival features do not improve expectancy on
  optimistic data) → the survival-conditioning thesis is **dead; documented; no consolation
  re-fit** on this data.
- **Terminal kill — top-decile net expectancy ≤ 0 even with survival features AND (2) fails** →
  the micro-cap right tail is **unscoreable on free survivor data**. Recorded as the conclusion;
  the product reverts to a research / watchlist tool, not an edge source. No v4 fishing expedition.

**Degrees-of-freedom lock:** the feature set (§3), model class & grid (§4), fold scheme, embargo,
decile cutoff, and every metric and threshold above are frozen by this document before any judged
run. Any change after seeing out-of-fold results is a protocol revision + new epic decision.

## 8. Costs, capacity, sizing reality

- 1% round-trip haircut on every ticket; capacity: position ≤ 1% of daily dollar-volume.
- Base-rate math in every report: at a ~1–2% doubling rate per quarter, zero-double quarters are
  statistically normal; every ticket must be sized to survive −50%.

## 9. How to run

```bash
# Plumbing dry-run (allowed anytime; numbers non-binding until §0 sign-off):
DATA_DIR=/tmp/bt3 PYTHONPATH=backend python backtest.py --study-v3 --period 5y --dry-run

# Judged run (ONLY after this protocol is signed off — executed once):
DATA_DIR=/tmp/bt3 PYTHONPATH=backend python backtest.py --study-v3 --period 5y
```

The study lives in `backend/backtest.py` (`run_study_v3`). It reuses the production feature and
scoring code verbatim (single source of truth, §3) on the tradable pool — no feature or membership
logic is duplicated. The frozen constants of §4/§7 live as module constants in `backtest.py` (not
in `FILTERS`, like the other studies' judged thresholds).

## 10. Run log — judged run (executed ONCE, after sign-off)

<!-- VALIDATION_V3_RUNLOG -->
*(empty — to be filled verbatim by the single judged run once §0 sign-off is granted; never
re-fitted)*
<!-- /VALIDATION_V3_RUNLOG -->

## 11. Verdict application

<!-- VALIDATION_V3_VERDICT -->
*(empty — the §7 decision rule applied to the §10 results; every statement must cite a §10 number)*
<!-- /VALIDATION_V3_VERDICT -->

## 12. Contingency — what remains if the verdict is bad

Documented in advance so a bad verdict does not trigger improvised thesis-fishing. This section
is a **decision map, not part of the frozen §7 criteria** — it changes nothing about how the
judged run is scored. The verdict falls into two failure modes, which point to different next steps:

- **Failure mode A — the survival veto adds nothing** (`value_of_survival.adds_value == False`:
  the full model ≈ the technicals-only model). The left tail is not in the filings either. The
  strongest lead is exhausted.
- **Failure mode B — the veto helps but expectancy stays ≤ 0** (`adds_value == True` yet the
  top-decile net expectancy is negative). A real signal exists, throttled by the survivor bias.

**The single most important consequence of any bad verdict:** it re-opens the "no paid data"
decision. v3 is the thesis survivorship handicaps *most* — the survival veto is asked to recognise
delistings it has never seen (dead companies are absent from free data). A bad verdict is
therefore partly "we could not test it fairly", which argues **for** revisiting the data question,
not against.

Ranked alternatives (do not implement until the verdict selects one — YAGNI):

1. **Free delisted-company reconstruction** (honours the no-paid-data decision). Rebuild a partial
   dead-companies set from free SEC filings (Form 25 delisting notices, deregistration, EDGAR
   gaps) and feed it into the study to de-bias the survival training. Engineering, zero dollars.
   **First move if the verdict is mode B.** Using it in the judged study requires a **protocol
   v3.1 revision** (§2 currently fixes survivor-only data) — a fresh pre-registration, not a re-fit.
2. **Buy delisted-inclusive data** (~40 USD/mo, Sharadar/Norgate). The clean version of (1).
   Justified only if mode B shows a throttled real signal; pointless in mode A. This is the user's
   money decision, currently DEFERRED.
3. **Live tracker as sole judge** (already running). The free-data backtest can never *confirm*
   anyway (§2). Deploy the score "non validé", let Validation B accumulate unbiased forward
   evidence over months. A bad backtest verdict does not kill the score — it means "backtest can't
   confirm, wait for live." Cost is time, not code.
4. **Basket / position-sizing thesis.** Phénix has a real +100 % lift with matching −50 % crashes;
   instead of screening the barbell away, size a diversified basket so the doublers pay for the
   crashes — per-name positive expectancy stops being required. Out of the screener's scope
   (portfolio construction) and needs the true crash rate → depends on (1)/(2).
5. **Downgrade the product to a watchlist / research tool** (the terminal-kill of §7). Keep the
   display; surface the extreme names for human research; drop any positive-expectancy claim.
6. **Accept the null result and document it.** Three pre-registered failures on free data is itself
   a real, publishable finding: retail-accessible free data does not support a micro-cap explosion
   edge. This is already the Medium case study's thesis.

**Recommended branch:** mode B → (1) free reconstruction as a protocol v3.1, with (3) the live
tracker running in parallel. Mode A → (5) or (6): the signal is nowhere in free data; stop fishing,
ship the honest watchlist and document the null. **Excluded in every case:** re-tuning thresholds
or features after seeing the verdict to force a pass. A fourth thesis must be a new pre-registered
epic, never a re-fit.
