# Decision protocol v6 — post-earnings alert (SUE Q5)

**Status: pre-registered.** The decision rule below was written before any measurement of
the realizable alert. This page holds no measured value: verdicts, returns and sample sizes
live in the private local configuration (`config/local.yml`) and are served to the page from
there. v1 to v5 are closed (v1-v3: failed pre-registered studies, see
[backtest_protocol_v2.md](backtest_protocol_v2.md) and
[backtest_protocol_v3.md](backtest_protocol_v3.md); v4 and v5: no verdict, forward tracking
removed with the screener). v6 is the only active thesis.

## 1. Thesis

After an earnings release whose seasonal surprise (SUE) is in the top quintile of the
previous calendar quarter (Q5), the price keeps drifting in the direction of the surprise
(Ball & Brown 1968, *Journal of Accounting Research* 6(2); Bernard & Thomas 1989, *Journal of
Accounting Research* 27). SUE: Bernard & Thomas 1990, *Journal of Accounting and Economics*
13(4):

    SUE = (EPS_q - EPS_q-4) / standard deviation of the 8 previous seasonal differences (4 at least)

## 2. Decision rule (word for word)

> Règle de décision pré-enregistrée, écrite avant toute mesure : une variante de l'alerte est
> GARDÉE si son rendement net du spread, hors nano, à h = 5 ou h = 21, a t ≥ +3 (t = net / se ;
> seuil Harvey, Liu & Zhu 2016, Review of Financial Studies 29(1), règle de ta-patterns depuis
> le 2026-10-10). Sinon : |t| < 3 = « non prouvé », t ≤ −3 = « réfuté ». Aucune variante
> gardée = arrêt de l'epic après le Sprint 1. Un tier n'est dans l'univers de l'alerte que si
> cette règle tient dans ce tier, avec n ≥ 2 000 (`min_n` de ta-patterns, héritage).

The same text is printed by `make study-earnings-verdict` (constant `RULE` in
`backend/study/earnings.py`). The rule judges the whole sample per tier; it does not judge by
sub-period. The alert is exactly the measured population: no unmeasured filter (no price cap,
no slope, no score).

## 3. Variants judged (and only these)

| Variant | Case date | EPS read in | Judged by |
| --- | --- | --- | --- |
| A, reproduction | `drift_date` of ta-patterns: first public close after the 8-K item 2.02 | XBRL (10-Q / 10-K filed up to 90 days later) | the rule, on the lake including delisted names |
| B, XBRL realizable | first public close after the acceptance of the 10-Q / 10-K that carries the quarter's EPS (same 16:00 New York rule) | XBRL | the rule, on the lake |
| C, Finviz realizable | `drift_date` | Finviz (history EPS_q-4 to EPS_q-12 still from EDGAR) | A's verdict, plus agreement between Finviz EPS and XBRL EPS on survivors: kept only if A is kept and agreement is at least 95 % within 0.01 USD |

Why three: ta-patterns dates each case at the 8-K but reads the EPS in the later 10-Q / 10-K.
The information is public at the 8-K (press release), so there is no look-ahead in the
reference study, but an alert reading XBRL can only enter at the 10-Q / 10-K. A is the
benchmark; B and C are the two ways to act in real time. Net return = gap to the same-day,
same-tier, same-volatility cell, net of the Corwin-Schultz spread, at h = 5 / 21 / 63 sessions
(`tools.measure` of ta-patterns).

## 4. What a kept variant changes

- The alert is the Q5 releases of the kept tiers (nano never), read in the Finviz export.
- Quintile bounds: SUE of the 8-K item 2.02 releases of the previous calendar quarter, EPS
  read in `companyfacts.zip` (the XBRL frames API was tried and abandoned: too many quintiles
  different from the lake). Bounds are recomputed live and cached in `data/earnings/`, never
  stored in the repo.
- The risk file (EDGAR flags) is displayed, never used as a filter.
- Forward follow-up = the alert journal (`data/earnings/alerts.jsonl`): entry = next open,
  realized return and IWM's at 5 / 21 / 63 sessions. Displayed, never triggers a decision.

## 5. Commands

```bash
# study on the ta-patterns lake (read only; PY = Windows venv of ta-patterns)
make study-earnings [STEP=cases|net|measure|placebo|verdict]   # whole study, ~16 min
make study-earnings-verdict        # prints the rule, then one line per (variant, tier), the
                                   # 8-K to 10-Q delay and the Finviz / XBRL agreement
make earnings-parity [YEAR=2025]   # live module vs the lake: SUE and quintile, exit 1 under 99 %
make earnings [SESSION=YYYY-MM-DD] # live detection of one session
```

Outputs go to `data/study/` (gitignored). The lake is never modified: no file written, no
commit in ta-patterns.

## 6. Binding constraints

- No threshold, tier list or measured value in code, tests or docs: `make check-edge`.
- A new variant, a new tier or a changed threshold is a new pre-registered epic.
- Realized returns of the journal are information; they never change the universe.
