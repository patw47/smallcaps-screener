# Architecture

## Overview

SmallCaps Screener produces one alert: a top-quintile earnings surprise (SUE Q5) on micro
caps, after the 10-Q / 10-K that carries the EPS (variant B of
[backtest_protocol_v6.md](backtest_protocol_v6.md)). It runs on a VPS, independent of the
workstation, and keeps a journal of what it alerted.

```text
EDGAR (8-K 2.02, 10-Q / 10-K, companyfacts)      Finviz export (market cap)
            \                                        /
             v                                      v
         backend/earnings.py  detect(session) -> SUE, quintile, entry date
                         |
                         v
         backend/run_earnings.py  (systemd timer, VPS)
            |-> Telegram message (one per new Q5 release)
            |-> data/earnings/alerts.jsonl  (journal)
            '-> realized return + IWM at 5 / 21 / 63 sessions (Yahoo chart API)
                         |
                         v
         backend/api.py  GET /api/alerts (read only)  ->  frontend page
                         127.0.0.1:8019, SSH tunnel only
```

## Repository layout

```text
backend/       earnings.py, run_earnings.py, api.py, edgar.py, finviz.py, lifecycle.py,
               alerts.py, screener_backend.py (config), study/ (lake studies), tests/
frontend/      the alerts page (React / Vite), i18n/, journal.js
deploy/        systemd units of the VPS (earnings-alert, earnings-bounds, screener-web)
scripts/       gates: check-edge, check-secrets, check-jargon, i18n
config/        local.example.yml (the real local.yml is gitignored)
docs/          this documentation
```

## Components

- **Detection** (`earnings.py`): the 10-Q / 10-K that first carries the quarter's EPS, linked to an
  8-K item 2.02 of the previous 90 days, one event per (CIK, period end); SUE; quintile against
  the bounds of the previous calendar quarter; entry date. Details: [backend.md](backend.md).
- **Job** (`run_earnings.py`): alert, dedup, journal, realized returns. One run per session.
- **Page** (`api.py` + `frontend/`): the journal read at each request, plus the measured gain
  from `config/local.yml`.
- **Study** (`backend/study/`): the decision study on the ta-patterns lake, read only, run on
  the workstation with the Windows venv of ta-patterns. It is not part of the runtime.

## Data

Runtime files live in `DATA_DIR` (`/opt/apps/smallcaps-screener/data` on the VPS): the journal
`earnings/alerts.jsonl`, the cached bounds `earnings/bounds_<quarter>.json`, `edgar_cache/`.
Study outputs go to `data/study/`. All gitignored.

## Edge outside the repo

The kept tiers, the measured gain, the Finviz link and the lake path are in `config/local.yml`
(gitignored); the code ships neutral defaults and `make check-edge` guards the repo.

## Known trade-offs

- The page is readable only through an SSH tunnel; public access would need DNS, Traefik and
  basic auth ([deployment.md](deployment.md)).
- A session whose job did not run at all (VPS down more than a day) is not replayed: the timer
  restarts one missed run only.
- CORS allows all origins; the API listens on loopback only, which is what protects it.
