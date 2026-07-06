# Pre-registered protocol v4 — "washout reversion basket" (DRAFT — NOT SIGNED)

> Naming note: an earlier draft called this the "innocent-fall" basket, on the story that the
> qualifying stocks fall *because of* the market. The per-stock beta test (2026-07-06, below)
> **refuted that story** while leaving the entry rules intact — see §1. Renamed accordingly.

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

Cheap small caps in a **recent decline during a falling market**, **without pending
dilution**, mean-revert over the next 63 trading days with: (a) net expectancy ≥ 0, and
(b) explosion rate (fwd63 ≥ +100 %) ≥ crash rate (fwd63 ≤ −50 %).

Rationale (measured 2021-2026, in-sample, survivor-biased — all optimistic ceilings):
- Combo cell (price/dilution/fall): E net +4.2 %, P(expl) 2.19 % vs P(crash) 2.77 % (n=1 733).
- Conditioned on falling market: **E net +5.9 %, median +1.6 %**, P(expl) 2.0 % ≈ P(crash) 1.9 % (n=1 193).
- The mirror cells are all negative (lone risers in down markets −5.7 %, lone fallers in
  rising markets −7.3 %, rising-market buys −6.6 %).

**Mechanism — corrected by measurement.** The original "innocence" story (the stock falls
*because of* the market, beta-driven) was tested at stock level: each observation's trailing
126-day beta/correlation vs IWM, decomposing the 1-month fall into a market-explained part
and an idiosyncratic **residual** (`chg1m − beta × mkt21`). Result — the gradient runs the
**other way**: within the combo, beta-explained falls (residual > −3 %) earn +2.9 %, while
falls far in excess of beta (residual < −10 %) earn **+11.2 %** (median +5.3 %, P(expl)
3.2 %, P(crash) 1.7 %, n=406). The working mechanism is therefore **oversold overshoot in a
market-wide washout** — cheap names crushed beyond their beta, with no dilution overhang,
while the whole tape is being purged. The falling-market condition still contributes (same
cell without it: +6.0 %) — a purging market appears to manufacture overshoot without
stock-specific rot, whereas the lone faller in a rising market (the −7.3 % cell) has real
problems. The residual gradient is recorded as **measured heterogeneity, NOT an entry rule**
(a fifth threshold chosen after this split would be post-hoc squared: n=406, ~9 dates).

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
  post-hoc (t = 0.47)**: the Appendix A tables — A.3 (funnel), A.6 (trajectories and
  checkpoint conditional probabilities). The UI displays THESE numbers verbatim, no others.
- Checkpoints are **display-only**. No automatic exit rule: measured, tight stops *degrade*
  this basket (they cut the reversion that generates its return: E +1.4 % → −0.4 %).
- Permanent disclaimer: "Recherche statistique en validation forward — espérance historique
  non significative (t = 0,47) — pas un conseil d'investissement."

## 4. Validation — forward only ("Validation C")

- **Instrumentation** (Epic 4 S2): each daily scan appends the v4-qualifying tickers with
  entry price and margins to the dated snapshots (`data/history/`). Zero trading, zero claim —
  bookkeeping only. Forward data has **no survivorship bias**: delistings are observed live,
  so a forward pass is a real pass (unlike any backtest in this project).
- **Observational fields** (recorded, NEVER judged on): each cohort entry also stores the
  name's trailing 126-day beta and correlation vs IWM and its 21-day residual
  (`chg1m − beta × mkt21`). Pre-registered **secondary analysis** at judgment time: does the
  §1 oversold gradient (deeper residual → better forward return) reproduce on fresh data?
  Descriptive only — it cannot pass or kill the hypothesis, and it must not be promoted to an
  entry rule without a v4.1 revision.
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

---

## Appendix A — Measured evidence (exploration of 2026-07-06, ALL in-sample)

Everything below was measured on the 5-year quarterly grid (2 519 tradable tickers, 19 666
ticker×date observations, fwd63 labels, −1 % round-trip cost where "net"). Survivor-only
data throughout → every number is an optimistic ceiling. These tables are **frozen
documentation**: they are what the UI may display (§3) and what the forward judgment will be
compared against — they are NOT tunable parameters.

### A.1 Portrait-robot — the 161 explosions vs 1 932 same-date controls

| Indicator at t0 | Exploders | Controls | Ratio |
|---|---|---|---|
| Going-concern flag (EDGAR) | 22.4 % | 5.1 % | **4.4×** |
| Late filing (NT 10-Q/K) | 10.6 % | 3.0 % | **3.6×** |
| Pending dilution (S-1/S-3/424B) | 37.9 % | 24.2 % | 1.6× |
| Cash runway (median) | 21 months | 120 months | — |
| Accumulation CMF > 0 | 46.0 % | 38.3 % | 1.2× |
| Breakout trigger active | 1.2 % | 1.2 % | 1.0× |
| Net insider buying | **0.0 %** | 3.4 % | 0× |
| ≥1 8-K filed in next 95 days | 83.9 % | 82.7 % | 1.0× |
| % of 52-week high (median) | 46 % | 73 % | — |
| 1-month return (median) | −5.1 % | −3.0 % | — |
| Price (median) | 6.5 $ | 13.2 $ | — |

### A.2 Explosions vs crashes head-to-head (161 vs 740) — why distress cannot rank

| Indicator at t0 | Exploders | Crashers |
|---|---|---|
| Going-concern (ratio vs own controls) | 4.35× | **5.19×** |
| Late filing (ratio) | 3.57× | **3.86×** |
| **Pending dilution (ratio)** | 1.57× | **2.14×** |
| Cash runway (median) | 21.4 mo | 20.3 mo |
| Price (median) | **6.46 $** | 14.16 $ |
| 1-month return (median) | −5.1 % | −1.6 % |
| CMF > 0 | 46.0 % | 40.1 % |
| Phénix profile | 6.8 % | 10.0 % |

Distress flags mark the barbell zone (both tails), slightly crash-biased → they can veto
nothing and select nothing. The only clean explosion-side tilts: **cheaper price, fresher
fall, absence of pending dilution** — the §2 entry rules.

### A.3 The differentiator filter — measured funnel and stability

| Set | n | P(expl) | P(crash) | E net fwd63 | Median net |
|---|---|---|---|---|---|
| Universe | 19 666 | 0.82 % | 3.77 % | −3.9 % | −4.8 % |
| Price ≤ 8 $ | 5 053 | 2.02 % | 4.53 % | −0.4 % | −4.6 % |
| Combo (price + no-dilution + fall) | 1 733 | 2.19 % | 2.77 % | +4.2 % | −0.4 % |
| **Combo + falling market (= v4 entry)** | 1 193 | 2.0 % | 1.9 % | **+5.9 %** | **+1.6 %** |
| Combo + RISING market (counterfactual) | 540 | 2.6 % | 4.6 % | +0.4 % | −5.4 % |
| Combo + CMF > 0 (not retained — n too small) | 322 | 3.73 % | 3.11 % | +6.4 % | −0.3 % |

The falling-market condition is retained on this measured contrast (+5.9 % vs +0.4 %; the
same holds inside the best sub-group: deep overshoot earns +11.2 % with the condition,
+6.0 % without). Note it rests on 9 down-market dates out of 18 — thin, like everything
in-sample here. The refuted "innocence" story (§1) does NOT justify it; only these numbers do.

Stability: yearly E net = −6.2 % (2021), +0.6 % (2022), +9.8 % (2023), +6.9 % (2024),
+6.2 % (2025), −4.8 % (2026 partial) → 4/6 positive. Date-cohorts: 10/18 positive, range
−27.4 % to +26.4 %. **Date-level t = 0.47** — the whole reason judgment is forward-only.
Basket of 10 same-day names, 50 000 draws: E +1.4 %, median +0.9 %, worst-5 % −26.6 %,
P(winning basket) 52 %.

### A.4 Market × stock square (1-month direction) — why the market condition exists

| Cell | P(crash) | E net fwd63 |
|---|---|---|
| Market ↓ · stock ↓ | 2.8 % | **+0.3 %** |
| Market ↓ · stock ↑ (lone riser) | 6.7 % | −5.7 % |
| Market ↑ · stock ↓ (lone faller) | 6.2 % | −7.3 % |
| Market ↑ · stock ↑ | 4.0 % | −6.7 % |

### A.5 Beta test — the oversold gradient inside the v4 entry (mechanism, §1)

Residual = 1-month return − (126-day beta × IWM 21-day return):

| Sub-group of v4 entry | n | P(expl) | P(crash) | E net | Median |
|---|---|---|---|---|---|
| Beta-explained fall (resid > −3 %) | 381 | 1.6 % | 2.6 % | +2.9 % | −0.3 % |
| Mixed (−3 % to −10 %) | 366 | 1.4 % | 1.6 % | +5.1 % | +2.4 % |
| **Deep overshoot (resid < −10 %)** | 406 | **3.2 %** | 1.7 % | **+11.2 %** | **+5.3 %** |

Recorded per cohort name (observational, §4) — never an entry rule without a v4.1 revision.

### A.6 Checkpoints — trajectories, conditional probabilities, and why exits are display-only

Median cumulative return from t0 (161 explosions / 740 crashes):

| Horizon | Exploders | Crashers |
|---|---|---|
| 3 days | +5.6 % | −1.2 % |
| 1 week | +5.9 % | −5.7 % |
| 2 weeks | +10.9 % | −10.6 % |
| 1 month | +19.7 % | −23.1 % |
| 2 months | +79.5 % | −45.0 % |
| 3 months | +127.3 % | −59.3 % |
| 6 months | +103.1 % | **−63.9 %** |

Explosions mostly hold at 6 months (median keeps +103 %; 1/3 keep rising); crashes keep
falling (majority lower at 6 months). **Whipsaw cost of early exits**: 32 % of future
exploders were still negative at 3 days, 30 % at 2 weeks, 20 % at 1 month.

Conditional on position at the 1-week checkpoint (all stocks):

| At 1 week | P(explosion by 3 mo) | P(crash) | E[remaining return → 3 mo] |
|---|---|---|---|
| ≥ +3 % | **1.9 %** | **2.4 %** | −3.0 % |
| < +3 % | 0.5 % | 4.2 % | −2.7 % |

The checkpoint moves **probabilities** (×4 explosion odds, ÷2 crash odds) but not
**expectancy**: the post-checkpoint residual return is negative everywhere and *worsens* as
the bar rises (at 3 days: −3.2 % for keep-if-≥−10 % → −10.2 % for keep-if-≥+15 %) — early
jumpers mean-revert. Exit-rule simulation (10-name baskets, 50 000 draws):

| Rule | E (Phénix basket) | Worst 5 % | E (v4 combo basket) |
|---|---|---|---|
| Hold 63 days | −7.4 % | −36.8 % | **+1.4 %** |
| Exit at 2 w if < 0 % | −7.0 % | −20.7 % | — |
| Tight stop (3 d < 0, then 2 w < +5 %) | −3.3 % | −13.0 % | **−0.4 %** |

On the v4 combo the tight stop **destroys** the return (it cuts the reversion that generates
it) → §3: checkpoints inform, they never trigger exits.
