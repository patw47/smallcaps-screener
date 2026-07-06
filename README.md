# SmallCaps Screener

A Dockerized dashboard that discovers and ranks US small-cap stocks. The goal is
to surface promising names **early** — quiet accumulation and tight bases, *before*
the move — rather than stocks that have already run.

It is a decision-support tool: it discovers, scores, and ranks. It does not trade.
The final call stays human. The interface is in French; this documentation is in
English.

> **⚠️ Thesis pivot (Epic 3, in progress).** Two pre-registered theses have failed. **v1**
> ("catch quiet accumulation early", described below): every score decile negative net-of-cost
> vs IWM, every year. **v2** (tail-hunting profiles **Fusée** / **Phénix**,
> [docs/backtest_protocol_v2.md](docs/backtest_protocol_v2.md)): both FAIL Validation A — Fusée
> no real lift, Phénix a real +100 % lift (4.59×) but a barbell eaten by the left tail
> (net expectancy −11 %). The right tail is *found*; the failure is **not dying** (left tail) and
> **honest measurement** under free, survivor-biased data. **Epic 3** pivots to
> **survival-conditioned right-tail scoring**: an interpretable, calibrated `P(fwd63 ≥ +100 %)`
> model over frozen price features **plus SEC/EDGAR survival signals** (dilution, going-concern,
> reverse split, cash runway), validated by **purged walk-forward** and the live tracker. The
> binding spec is **[docs/backtest_protocol_v3.md](docs/backtest_protocol_v3.md)**. The sections
> below still describe the v1 screener that stays in production while v3 is built.

## How it works

The scan is a **two-pass funnel** driven by **scoring, not strict elimination**.

```
NASDAQ + NYSE + AMEX (NASDAQ screener API)  →  dedupe  →  full universe (~2–3k)
    (Small + Micro cap · identical every scan · shuffle only sets download order)
    │
    ▼  Pass A  (analyze_prices) — batch yf.download, no per-ticker cost
    │     minimal hard filters:  price 2–25 · 1-month perf · liquidity ≥ $1M ·
    │                            falling-knife guard (MA50 slope ≥ 0)
    │     technical signals:     accumulation (OBV) · compression (ATR) ·
    │                            near recent-base pivot · low extension · RS turning
    │
    ▼  rank survivors by technical score (accumulation weighted highest)
    │     → keep the top ~150 (bounds the expensive .info calls)
    │
    ▼  Pass B  (enrich_ticker) — yfinance .info on the top-scored names only
    │     hard filters:  market cap 50M–2B · exchange
    │     fundamentals:  insider · cash/debt · revenue growth · float · short interest
    │
    ▼  0–10 score (see scoring modes)  →  sorted list  →  data/screener_data.json
```

**Why scoring instead of hard filters?** Requiring "already strong" signals (high
relative strength, near the 52-week high) selects stocks that have *already moved* —
you arrive after the party. Keeping the hard filters minimal and letting the **score**
rank means early setups aren't eliminated; the accumulation-led score floats the best
candidates to the top.

## Scoring model

The scoring approach is **not settled** — it is a config flag (`FILTERS["scoring_mode"]`),
to be decided by a larger backtest:

- **`binary` (default)** — the original additive "checkbox" score. Known and conservative,
  but caps around 8 (some signals are near-unreachable).
- **`continuous`** — each signal is a continuous factor, percentile-ranked across the
  candidates, combined and shown as a **decile 0–10** ("how good among today's candidates").
  Fixes the scale; edge not yet validated.

Both modes use the same weights below (`FILTERS["score_weights"]`, tunable).

**Technical factors** (computed in Pass A; also used to rank which survivors get enriched):

| Factor | Weight | Meaning |
| --- | ---: | --- |
| Accumulation (Chaikin Money Flow + up/down volume) | **4** | Money quietly coming in — the strongest pre-move tell |
| Compression (ATR20/ATR90 self-percentile) | 2 | Volatility contracting *relative to the stock's own history* |
| Near recent-base pivot | 2 | Close to breaking out of its recent base |
| Low extension (near MA50) | 2 | Still early in the move, not 40% extended |
| Relative-strength magnitude | 2 | Outperforming the market |
| Price above MA50 | — | (kept as a signal for display) |

**Fundamental factors** (added in Pass B, on the top-scored names):

| Factor | Weight |
| --- | ---: |
| Insider net buying (Form 4 open-market purchases) | 2 |
| Cash > debt | 1 |
| Revenue growth | 1 |
| Low float | 1 |
| High short interest (squeeze) | 1 |

Accumulation (4) is the top signal. **Sensors v2** (Sprint 4) reworked the two pillars
without changing any weight: **compression** is now the self-percentile of ATR20/ATR90
against the stock's *own* 252-day history (v1's raw `< 0.70` threshold fired on ~0.8 % of
names — effectively dead), and **accumulation** is Chaikin Money Flow + the up/down volume
ratio (more robust than v1's binary OBV on gappy names). The v1 sensors stay switchable via
`FILTERS["sensors_version"]` for the Sprint 6 backtest. Weight calibration is Sprint 8.

See [docs/backend.md](docs/backend.md) for the exact factors and functions.

## Validation & monitoring

- **The study** (`backend/backtest.py --study`): a **rolling multi-date cross-section** over
  the full universe — at each monthly as-of date it replays `analyze_prices` on data known at
  `t` and records forward returns (21d/63d) vs IWM. It reports the **Spearman IC** (score →
  return) with a **t-stat on non-overlapping windows**, a **decile table in excess of IWM**
  (means + medians), a **per-year breakdown**, results **with and without costs** (−1 %
  round-trip + a 1 %-of-ADV capacity filter), and baselines (**binary vs continuous vs best
  single factor vs random**). It follows a **pre-registered protocol** —
  [docs/backtest_protocol.md](docs/backtest_protocol.md) — with a **calibration / validation
  split** and success criteria fixed *before* the first run. This study, and it alone,
  authorizes the Sprint 8 weight calibration. Every report prints the **survivorship-bias**
  warning (results are an upper bound). The older single-window `--sweep` / default modes
  remain for quick checks.
- **The v2 tail-hunting study** (`backend/backtest.py --study-v2`): the study for the current
  thesis. On the **tradable** universe (no thesis filters), at each monthly as-of date it labels
  the full cross-section with the **production detectors** (`profiles.detect_profiles` — the same
  code as the badges, zero duplication) and measures, **per profile × window**, the **+50 %/+100 %
  forward tail lifts** with a bootstrap 95 % CI, the **≤ −50 % left-tail guard**, mean **net
  expectancy**, the **break-even hidden-delisting rate** (survivorship fragility, protocol §5), and
  an explicit **PASS/FAIL/CONDITIONAL verdict** against the pre-registered criteria. It splits
  **Validation A** (2021-07→2023-06, judged once) from the spent **exploration** window. The frozen
  spec is [docs/backtest_protocol_v2.md](docs/backtest_protocol_v2.md); the Validation A run log is
  its §9.
  - **Verdict (Validation A, run 2026-07-05, full universe 2519 tickers): both profiles FAIL.**
    **Fusée** — no material +100 % lift at 63d (1.03×, CI95 [0.46, 1.71] spans 1.0×), net expectancy
    −9.56 %, fragile (break-even delisting 2.7 %) → the momentum-tail sub-thesis is **dropped, no
    re-fit** (§6). **Phénix** — a real right-tail lift (+100 % 4.59×, CI95 [2.30, 7.21] excludes 1.0×)
    but a **barbell eaten by the left tail** (≤ −50 % guard 2.27× over the 1.5× cap, net expectancy
    −11.02 %) → fails criteria (2) and (3); it stays **research-only, money-gated** pending
    delisted-inclusive data (**purchase deferred** — see §9). Both badges therefore carry a **"non
    validé"** marker. Validation B (the live tracker) keeps running and can still overturn this
    forward.
- **The v3 survival-conditioned study** (`backend/backtest.py --study-v3`): purged walk-forward
  (K=5, 73-day embargo) over the tradable universe, training the frozen 13-feature logistic model
  and measuring **value-of-survival** — does the EDGAR survival veto beat the same model on
  technicals alone? Frozen spec: [docs/backtest_protocol_v3.md](docs/backtest_protocol_v3.md);
  the judged run log is its §10.
  - **Verdict (judged run 2026-07-06, 2519 tickers, 5y, 58,229 obs): TERMINAL_FAIL.** Ranking
    works (top-decile +100 % lift 3.15×, CI95 [2.66, 3.63]) but the survival features **worsen**
    net expectancy (−8.7 % vs −7.4 % technicals-only), the ≤ −50 % guard blows (3.66× vs 1.5× cap)
    and the model loses to random picks (−8.7 % vs −3.4 %). Pre-registered terminal kill: **the
    micro-cap right tail is not scoreable on free survivor-only data.** No model is deployed
    (`p_explode` stays `null`); the product is a **watchlist / research tool** (§12 branch 5+6).
- **The measured odds, in plain numbers** (all from the judged studies; all are **optimistic
  ceilings** — free data contains only companies that survived):
  - A random tradable small/micro cap: **~1 in 100** chance of a +100 % move within 3 months
    (v3 base rate over 5 years; single windows vary with regime — the 2021-23 diagnostic
    measured up to 2.7 %).
  - The v3 model's preferred decile: **~3 in 100** (3.15× base, CI95 [2.66, 3.63]).
  - A pure v2 Phénix profile: **4.59× base** — order of 4–5 in 100 (CI95 [2.30, 7.21]).
  - **The other side of the coin**: the same names lose half their value **2.27×** (Phénix) to
    **3.66×** (v3 top decile) more often than average, and mean net expectancy per position is
    **−9 % to −11 %** — worse than random picks. Higher doubling odds never translated into
    positive expectancy in any of the three studies.
  - **Total loss (bankruptcy/delisting) is not measurable here**: dead companies are absent from
    free data by construction, so even the left-tail numbers above are *underestimates*. This is
    the survivorship ceiling that caps every number in this README.
  - **Basket math — the goal was never to beat the index on average** (an ETF does that); it was
    asymmetric bets: cheap shares, many names, one doubler pays for the rest. That intuition is
    computable: `P(≥1 doubler) = 1 − (1−p)^N`. At p≈3 % (v3 top decile) you need **~23 names for a
    coin-flip** chance of catching one doubler and **~76 for 90 %**; at p≈4.6 % (Phénix), ~15 and
    ~49. **The trap**: expectancy is additive — a basket of negative-EV names (−9 % to −11 % each,
    *doublers already included in that mean*) is just a bigger negative-EV basket. Diversification
    narrows the variance around a losing mean; it cannot flip its sign. The basket thesis only
    works with per-name expectancy ≥ 0, which needs the true crash rate (delisted-inclusive data)
    — pre-registered as contingency §12-alt-4, not pursued on free data. (Also: picks cluster in
    time and regime, so the independence assumption makes these N slightly optimistic.)
  - These are descriptive backtest frequencies, not a live score and not investment advice.
- **Live performance tracking**: every scan writes a dated snapshot of its picks to
  `data/history/` (ticker, entry price, score, key signals). `GET /api/performance` then
  measures each pick's return **since it was first flagged** and compares it to IWM — an
  unbiased, real-time read of whether the screener works. It is **robust by design**: a
  delisted or missing ticker, a market-data outage, or a corrupt snapshot never breaks the
  report — the endpoint always returns a well-formed payload (with a `message` on failure).
- **Automatic scans**: the backend re-scans every `SCAN_EVERY_HOURS` (default 24), **only on
  trading days** (Mon–Fri, weekends skipped — `SCAN_TRADING_DAYS_ONLY`, default on), so the
  snapshot history builds up on its own, roughly one snapshot per trading day.
- **Retention**: snapshots are tiny JSON files (a few KB each) — the policy is **keep
  everything**; a longer history only makes the tracker more meaningful.

```bash
# The study — rolling multi-date cross-section (Sprint 6). --n 0 = full universe.
docker compose exec backend python backtest.py --study --n 0 --period 3y

# The v2 tail-hunting study (Fusée/Phénix lifts + Validation A verdict). --n 0 = full universe.
docker compose exec backend python backtest.py --study-v2 --n 0 --period 5y

# The v3 survival-conditioned study (purged walk-forward). Judged ONCE on 2026-07-06:
# TERMINAL_FAIL (protocol §10-§11) — do NOT re-run with --signed-off for judgement.
docker compose exec backend python backtest.py --study-v3 --n 0 --period 5y

# Quick single-window backtest
docker compose exec backend python backtest.py --n 200 --forward 63 --seed 42

# Performance of past selections
curl http://localhost:8000/api/performance
```

## Things to know

- **Setup vs trigger.** `setup_score` (alias of `score`) says *"the spring is coiled"* —
  a watchlist candidate. `triggered` says *"the breakout is happening now"* (close above the
  recent pivot **and** a volume surge). Every candidate carries both plus `days_since_trigger`.
  A **Telegram alert** pings newly triggered names (`setup_score ≥ alert_min_score`,
  deduped); set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` to enable — absent, it's silently off.
- **Yahoo rate-limits `.info` hard.** Hitting it with many parallel requests bans the
  IP (`YFRateLimitError`). Pass B therefore uses a small thread pool (2) + backoff, and
  only enriches the top ~150 survivors. This is by design — do not raise `enrich_workers`.
- **`GET /api/scan` is non-blocking.** It returns the current cache immediately (or an
  empty `scanning: true` payload on a cold start) and scans in the background. Poll
  `GET /api/scan/status` for `phase`/`progress`. No multi-minute freeze on first load.
- A scan sweeps the **entire eligible universe** (~2,000–3,000 tickers across NASDAQ,
  NYSE and AMEX, identical from one scan to the next — no random sampling), takes
  ~5–10 minutes, and caches results for 30 minutes. Pass A downloads price/volume in
  batches (free); only the top ~150 survivors reach the costly `.info` calls.
- Market data comes from public endpoints and `yfinance`; field quality varies by
  ticker (small caps especially). The reliable signals are price/volume based.
- The dashboard shows each stock's **tail-hunting profile** prominently: a 🚀 **Fusée** or
  🔥 **Phénix** badge (both if it qualifies for both), with a profile filter (All / Fusée /
  Phénix) and per-profile counts. **Both badges carry a "non validé" marker** since Validation A
  failed for each (§6, see the study section above): the badges are **research signals, not
  validated edges** — the hover tooltip carries the Sprint 5 numbers. They remain useful for
  surfacing candidates; Validation B (the tracker) may still confirm a profile forward.
- This is a screening tool, **not financial advice**.

## Stack

- Backend: Python 3.11, FastAPI, yfinance, pandas, requests
- Frontend: React 18, Vite 5
- Runtime: Docker Compose; scan cache and history on a Docker volume at `/app/data`

## Quick start

Prerequisite: Docker Desktop or Docker Engine with Compose.

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY in .env only if you want the per-stock Claude analysis button.
docker compose up --build
```

Services:

- Frontend: http://localhost:5173
- API scan: http://localhost:8000/api/scan
- Performance: http://localhost:8000/api/performance
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/health

## Commands

```bash
docker compose up --build                                  # start everything
curl -X POST http://localhost:8000/api/scan/force          # force a fresh scan
docker compose exec backend python screener_backend.py     # run a scan directly
docker compose exec backend python backtest.py --n 200     # backtest
docker compose logs -f backend                             # follow logs
docker compose down                                        # stop
docker compose down -v                                     # stop + wipe cache/history

# Tests (offline, deterministic, no network)
DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/
```

## Configuration

Screener thresholds and weights live in the `FILTERS` dict at the top of
`backend/screener_backend.py` (no magic numbers in the logic).

| Variable | Used by | Required | Description |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | Frontend (`VITE_ANTHROPIC_API_KEY`) | Only for AI analysis | Key for the browser-side Claude analysis button. |
| `SCAN_EVERY_HOURS` | Backend | No (default 24) | Interval between automatic background scans. |
| `SCAN_TRADING_DAYS_ONLY` | Backend | No (default `true`) | Skip weekend auto-scans (market closed → redundant snapshots). |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Backend | No | Enable breakout alerts. Absent → alerting silently disabled. |
| `EDGAR_USER_AGENT` | Backend | No | SEC-compliant identifying UA (name + email) for Form 4 insider data. Absent → EDGAR disabled (neutral). |
| `DATA_DIR` | Backend | No (default `/app/data`) | Where the cache and history are written (used by tests). |

## API endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/scan` | GET | Ranked results (non-blocking; triggers a background scan if stale). |
| `/api/scan/status` | GET | `scanning` / `phase` / `progress`. |
| `/api/scan/force` | POST | Force a fresh background scan. |
| `/api/performance` | GET | Return of past selections since first flagged, vs IWM. |
| `/api/stock/{ticker}` | GET | One ticker from the latest result. |
| `/api/watchlist` | GET/POST/DELETE | Read / set / clear a custom watchlist (POST overrides discovery). |
| `/api/health` | GET | Health check. |

## Project structure

```
backend/
├── screener_backend.py   # discovery, two-pass funnel, scoring, snapshots
├── api.py                # FastAPI app (non-blocking scan, daily scheduler, endpoints)
├── backtest.py           # offline forward-return validation
├── track.py              # live performance tracking of past selections
└── tests/                # offline deterministic unit tests
frontend/
├── smallcap-screener.jsx # dashboard UI (Fusée/Phénix profile badges; editable since Epic 2)
└── src/main.jsx
docs/                     # architecture, backend, api, frontend, deployment
```

## Documentation

- [Architecture](docs/architecture.md)
- [Backend screener & scoring](docs/backend.md)
- [API reference](docs/api.md)
- [Frontend](docs/frontend.md)
- [Deployment and operations](docs/deployment.md)

## Security note

The per-stock Claude analysis currently calls the Anthropic API **directly from the
browser**, which exposes the API key to browser code. This is convenient for local use
only. For production, proxy AI requests through the backend.
