# Pre-registered protocol v4 — "innocent-fall reversion basket" (DRAFT — NOT SIGNED)

**Status: DRAFT.** Non-binding until the owner signs it off (§0 of every protocol in this
project: the anti-cheat barrier cannot self-approve). Written 2026-07-06, immediately after
the Epic 3 TERMINAL_FAIL verdict and the exploration session documented in the Medium case
study ("autopsie des explosions", "carré marché × titre", "filtre différenciateur").

## 0. What this is — and what it is NOT

This is **statistical research, not an edge claim**. The hypothesis below was found by
**post-hoc exploration on seen data** (dozens of cells scanned; thresholds chosen after
looking at the answers; 18 independent date-cohorts; date-level **t = 0.47** — statistically
indistinguishable from zero). Historical data can no longer confirm nor refute it: every
window has been spent on discovery. The ONLY admissible judge is **forward data** (§4).
The product consequence is a probability display with permanent disclaimers — never a
positive-expectancy claim before the forward verdict.

## 1. Hypothesis (frozen)

Cheap small caps in a **recent innocent decline** — falling *with* a falling market, not
alone — and **without pending dilution**, mean-revert over the next 63 trading days with:
(a) net expectancy ≥ 0, and (b) explosion rate (fwd63 ≥ +100 %) ≥ crash rate (fwd63 ≤ −50 %).

Rationale (measured 2021-2026, in-sample, survivor-biased — all optimistic ceilings):
- Combo cell (price/dilution/fall): E net +4.2 %, P(expl) 2.19 % vs P(crash) 2.77 % (n=1 733).
- Conditioned on falling market: **E net +5.9 %, median +1.6 %**, P(expl) 2.0 % ≈ P(crash) 1.9 % (n=1 193).
- Mechanism: the fall is the market's fault (beta), not the stock's (no dilution overhang);
  reversion does the rest. The mirror cells are all negative (lone risers −5.7 %, lone
  fallers −7.3 %, rising-market buys −6.6 %).

## 2. Entry definition (frozen — no tuning after sign-off)

A stock **qualifies at date t** iff ALL of:

1. `price ≤ 8 USD`
2. `dilution_flag == False` — EDGAR point-in-time (§ Epic 3 S2): no S-1/S-3/F-1/F-3/424B
   registration in the trailing 180-day window. `None` (EDGAR unavailable) does NOT qualify.
3. `change_1m ≤ −3 %`
4. **Market context**: IWM 21-trading-day return `< 0` at t.

Universe: the standard tradable pool (same filters as production). Margins (distance to each
threshold) are *displayed*, never used to re-rank or tune.

## 3. Display contract (research tool — no edge claim)

- The daily scan lists the qualifying names ("cohorte v4") with threshold margins.
- Frozen historical stats shown next to them, labelled **in-sample 2021-2026, survivor-only,
  post-hoc (t = 0.47)**: the §1 numbers and the checkpoint table (P(explosion) roughly ×4 /
  P(crash) ÷2 above vs below the +3 % @ 1-week mark; full table in the case study).
- Checkpoints are **display-only**. No automatic exit rule: measured, tight stops *degrade*
  this basket (they cut the reversion that generates its return: E +1.4 % → −0.4 %).
- Permanent disclaimer: "Recherche statistique en validation forward — espérance historique
  non significative (t = 0,47) — pas un conseil d'investissement."

## 4. Validation — forward only ("Validation C")

- **Instrumentation** (Epic 4 S2): each daily scan appends the v4-qualifying tickers with
  entry price and margins to the dated snapshots (`data/history/`). Zero trading, zero claim —
  bookkeeping only. Forward data has **no survivorship bias**: delistings are observed live,
  so a forward pass is a real pass (unlike any backtest in this project).
- **Cohorts**: one cohort per trading day; outcomes measured at 63 trading days (net of the
  standard −1 % round-trip haircut). Judgment uses **non-overlapping** cohort windows only
  (≈ one independent observation per quarter).
- **Judgment date**: first evaluation no earlier than **12 months** after instrumentation
  goes live, and only if ≥ 4 non-overlapping cohort windows have completed. Final judgment
  at **≥ 8 non-overlapping windows** (~24 months).
- **Success criteria (all required)**:
  1. Mean non-overlapping-cohort net return > 0 with cohort-level t ≥ 2.
  2. Crash rate ≤ 1.5 × explosion rate across pooled cohorts.
  3. Result holds in both market regimes present in the sample (if both occur).
- **Kill criteria (any suffices)**:
  1. Mean cohort net return ≤ 0 at final judgment.
  2. t < 1 after 8 non-overlapping windows.
  3. Crash rate > 2 × explosion rate pooled.
- On success: the display may drop "non significatif" (never "validé" — that word stays
  banned) and a v5 sizing discussion may open. On kill: the hypothesis is retired, the
  display reverts to pure watchlist, documented in the case study. **No threshold tuning in
  either case** — any change is a v4.1 revision that RESTARTS the forward clock.

## 5. Degrees-of-freedom lock

Entry thresholds (§2), cost model, cohort scheme, judgment dates and criteria (§4) are frozen
by this document at sign-off. The checkpoint table and historical stats shown in the UI are
frozen artifacts of the 2026-07-06 exploration — they are documentation, not parameters.

## 6. Run log — forward judgment (empty until judged)

<!-- VALIDATION_V4_RUNLOG -->
*(pending — instrumentation not yet live; protocol not yet signed)*
<!-- /VALIDATION_V4_RUNLOG -->
