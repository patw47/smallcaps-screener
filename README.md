# SmallCaps Screener

One product: a **Telegram alert after an earnings release whose surprise is in the top
quintile (SUE Q5), on US micro caps**, and a page that lists these alerts with the returns
realized afterwards. It does **not** trade and does not claim a guaranteed edge: it
reproduces one measured pattern and keeps a public-by-construction forward journal of what
it alerted. The page is in French and English; this documentation is in English.

Everything else the project used to do (daily scan, 0-10 score, Fusée / Phénix profiles,
washout cohorts, performance tracker) was removed in Epic 15; the earlier theses failed
their pre-registered tests and stay documented as history in
[docs/backtest_protocol_v2.md](docs/backtest_protocol_v2.md) and
[docs/backtest_protocol_v3.md](docs/backtest_protocol_v3.md).

## The mechanism, without jargon

When a company publishes quarterly results better than its own pattern, the market does not
price the whole news on day one: the price keeps moving in the same direction for weeks.
This is the **post-earnings announcement drift**, documented since 1968 (Ball & Brown 1968,
*Journal of Accounting Research* 6(2); Bernard & Thomas 1989, *Journal of Accounting
Research* 27). Small companies are followed by few analysts, so the effect is where the
market should be slowest.

"Better than its own pattern" is measured without analyst forecasts, with the **seasonal
SUE** (standardized unexpected earnings, Bernard & Thomas 1990, *Journal of Accounting and
Economics* 13(4)):

```
SUE = (EPS this quarter - EPS same quarter last year)
      / standard deviation of the 8 previous such differences (4 at least)
```

Each release is then ranked against all releases of the previous calendar quarter; the top
fifth is **Q5** and triggers the alert. The evidence threshold is a t-statistic of at least
3 on the return net of the bid-ask spread (Harvey, Liu & Zhu 2016, *Review of Financial
Studies* 29(1)), because testing many ideas makes t >= 2 too easy to reach by chance.

## What exactly alerts

- **Variant B**: the alert fires after the **10-Q / 10-K** that carries the quarter's EPS,
  not at the press release. The EPS is read in the SEC's XBRL data, which arrives with that
  filing; the entry is the open of the session after the first public close following it.
  Variant A (entry at the press release, as in the reference study) is the benchmark: it
  cannot be traded from XBRL data, which is not yet public at that date. Variant C (EPS
  read from Finviz) was rejected because Finviz and XBRL EPS did not agree often enough.
  The rule that decided is in [docs/backtest_protocol_v6.md](docs/backtest_protocol_v6.md).
- **Universe**: the market-cap tiers kept by the study (micro caps only, nano caps never),
  read in the Finviz export. No other filter (no price cap, no score): the alert is exactly
  the measured population.
- **Risk file**: EDGAR flags (going-concern doubt, dilution filing, late filing) are
  displayed next to the alert. They filter nothing: filtering on risk traits was not shown
  to help. (Price-based markers need a price series, which the alert does not carry.)

## Limits (read before using)

- **Retained variant only**: B is the only measured version that can be bought in real
  time; the figures of the reference study (entry at the press release) are not the ones an
  alert can earn.
- **Entry delay**: the entry happens after the 10-Q / 10-K, days to weeks after the press
  release. Part of the drift is already gone; the measured return accounts for it.
- **One tier**: only micro caps pass the decision rule with enough cases. Small caps are
  not in the universe, and nano caps (illiquid, high spread) are excluded.
- **Not stable over time**: variant B is negative over 2016-2020 at the 21-session horizon.
  The decision rule does not judge by period, so there is no verdict per period: an edge
  absent for 5 years out of 15 is accepted knowingly.
- **Realized returns are gross and short**: the journal shows simple returns from the entry
  open to the horizon close, against IWM. The "measured gain" shown beside them is another
  kind of number (gap to same-size, same-volatility stocks, net of spread); the two are not
  comparable. The journal is information, it triggers no automatic decision.
- This is a research tool, **not financial advice**.

## Reading the page

The alerts page is served on the VPS and is reachable **only through an SSH tunnel**
(nothing is exposed to the internet, because it shows the measured gain, which is private):

```bash
ssh -N -L 8019:127.0.0.1:8019 hetzner-vps    # then open http://localhost:8019
```

It shows the releases of the last closed session, the journal of every alert with its
realized return at 5 / 21 / 63 sessions against IWM, the average and the number of due
alerts per horizon, and the risk flags. Details: [docs/guide_interface.md](docs/guide_interface.md).

## How it runs

```
VPS (systemd, not the workstation)
 earnings-bounds.timer  03:00 New York   quintile bounds of the previous quarter (cached)
 earnings-alert.timer   Mon-Fri 18:00    run_earnings.py: detect -> Telegram -> journal
 screener-web.service   127.0.0.1:8019   alerts page + GET /api/alerts (read-only)
```

- `backend/earnings.py`: live detection (10-Q / 10-K first carrying the EPS, linked to an
  8-K item 2.02 of the 90 previous days), SUE, quintile, entry date.
- `backend/run_earnings.py`: the job (Telegram message, journal `data/earnings/alerts.jsonl`,
  realized returns added at 5 / 21 / 63 sessions).
- `backend/study/`: the study on the ta-patterns data lake, **read only** (never modified).
- `backend/edgar.py`, `backend/lifecycle.py`, `backend/finviz.py`: risk file and Finviz export.
- `frontend/`: the page (React 18, Vite 5).

Install and redeploy commands: [docs/deployment.md](docs/deployment.md).

## Commands

```bash
DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/   # offline tests (make test)
make earnings [SESSION=YYYY-MM-DD]       # releases of a session with SUE, quintile, entry date
make earnings-parity [YEAR=2025]         # parity with the ta-patterns lake (Windows venv)
make study-earnings [STEP=...]           # the study on the lake (Windows venv, ~16 min)
make study-earnings-verdict              # decision rule + verdict per variant and tier
```

### Verification targets

| Target | Guards against |
| --- | --- |
| `make test` | Regressions in the offline deterministic suite. |
| `make check-edge` | A measured value, a token or a private-protocol reference reaching the repo (code, tests, docs, `scripts/`, `deploy/`, page). |
| `make check-jargon` | Version numbers or internal vocabulary reaching the screen. |
| `make i18n-parity` / `make check-i18n` | Missing translations; hard-coded UI strings in the JSX. |
| `make test-frontend` | A broken journal summary or label interpolation (`node --test`). |
| `make build-frontend` | JSX that no longer compiles (containerised `vite build`). |
| `make check-runtime` | Python that compiles on the dev interpreter but not on the production 3.11. |
| `make check-secrets` | A secret value reaching a versioned file. Never prints what it finds. |
| `make docs-build` / `make docs-check` | A broken public documentation build; a leak in the rendered site. |

## Configuration

Thresholds of the risk file live in `FILTERS` in `backend/screener_backend.py`. The **edge**
(kept tiers, measured gain shown on the page, Finviz link and token, path of the study
lake) is **not versioned**: the code ships neutral defaults (empty tiers = nobody enters),
and the real values load at startup from `config/local.yml` (gitignored, template in
`config/local.example.yml`). `make check-edge` gates the repo against value leaks.

| Variable | Used by | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Job | Alert and error messages. Absent: sending disabled. |
| `EDGAR_USER_AGENT` | Job, study | SEC-compliant identifying UA (name + email). Absent: EDGAR disabled. |
| `REQUIRE_LOCAL_CONFIG` | Backend | `1`: refuse to start without `config/local.yml`. |
| `DATA_DIR` | Backend | Where the journal, bounds and caches are written (default `/app/data`). |

## API

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/alerts` | GET | Read-only journal of the alerts, with the session of each horizon and the measured gain. |
| `/api/health` | GET | Health check. |

## Sources

- Ball, R. & Brown, P. (1968). An empirical evaluation of accounting income numbers. *Journal of Accounting Research* 6(2).
- Bernard, V. & Thomas, J. (1989). Post-earnings-announcement drift: delayed price response or risk premium? *Journal of Accounting Research* 27.
- Bernard, V. & Thomas, J. (1990). Evidence that stock prices do not fully reflect the implications of current earnings for future earnings. *Journal of Accounting and Economics* 13(4).
- Harvey, C., Liu, Y. & Zhu, H. (2016). ... and the cross-section of expected returns. *Review of Financial Studies* 29(1).
- Decision rule, variants and commands: [docs/backtest_protocol_v6.md](docs/backtest_protocol_v6.md).

## Documentation

Published as a browsable site: https://patw47.github.io/smallcaps-screener/

- [Architecture](docs/architecture.md) · [Backend](docs/backend.md) · [API](docs/api.md)
- [Frontend](docs/frontend.md) · [Deployment and operations](docs/deployment.md)
- [Glossary](docs/glossaire.md) · [Page reading guide](docs/guide_interface.md)
- [Decision protocol](docs/backtest_protocol_v6.md)

## License

All rights reserved. See [LICENSE](LICENSE) — the source is public for portfolio and
evaluation only; no reuse or redistribution is granted.
