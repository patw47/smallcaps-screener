# Deployment and Operations

## Earnings alert on the VPS (Epic 15)

The alert does not depend on the workstation: a Python job and two systemd timers run on
the VPS (`ssh hetzner-vps`, UTC clock, schedules written in New York time).

| Unit | When | What |
| --- | --- | --- |
| `earnings-alert.timer` → `.service` | Mon–Fri 18:00 New York | `run_earnings.py`: releases of the last closed session (`earnings.detect`); each top-quintile release not yet in the journal → one Telegram message + one line of `data/earnings/alerts.jsonl`; journal lines whose 5 / 21 / 63-session horizon has closed get their realized return and IWM's. |
| `earnings-bounds.timer` → `.service` | every day 03:00 New York | `run_earnings.py --bounds`: quintile bounds of the current and previous quarter, cached in `data/earnings/` (a new quarter takes 7–9 min, kept off the evening run). |
| `screener-web.service` | always (restarted at each redeploy) | `uvicorn api:app` on `127.0.0.1:8019`: the alerts page (`frontend/dist`, built on the VPS) and its read-only route `GET /api/alerts`. |

- **Why 18:00**: a 10-Q accepted before the 16:00 close has its first public close that
  day and its entry at the next open; 2 h leave the EDGAR full-text search time to index
  it. A 10-Q filed overnight has its first close the next day: the next evening run
  catches it before its entry, so no morning run is needed.
- `Persistent=true`: a run missed while the VPS was down starts at boot. A holiday run
  finds the previous session already in the journal (dedup on CIK + quarter end): no message.
- **Failure**: any exception sends one Telegram message and exits 1 (`systemctl --failed`).
  A send that fails is logged and the journal line keeps `"telegram": false`.
- **Prices of the realized returns**: Yahoo chart API (`query1.finance.yahoo.com/v8/finance/chart`,
  no key), same source for the stock and IWM; open of the entry session to close of the
  horizon session, both adjusted for splits and dividends (`adjclose / close` applied to
  the open). A missing bar leaves the cell empty; it is retried at the next run.

### Layout

| Path | Owner / mode | Content |
| --- | --- | --- |
| `/opt/apps/smallcaps-screener/` | `queenp:apps`, `2770` | git clone (public HTTPS), `.venv/` (`requirements.txt`) |
| `.env` | `screener`, `0600` | `EDGAR_USER_AGENT`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — never in git |
| `config/local.yml` | `screener`, `0600` | sections `finviz` (export link + token) and `earnings` (`tiers`, `net`, `notify_empty`) of the workstation's file |
| `data/` | `screener:apps`, `2770` | `earnings/alerts.jsonl` (journal), `earnings/bounds_<quarter>.json`, `edgar_cache/` |

Service user `screener` (system, no login, groups `screener` + `apps`).

### First install

```bash
ssh hetzner-vps
sudo useradd --system --no-create-home --shell /usr/sbin/nologin --groups apps screener
cd /opt/apps && git clone https://github.com/patw47/smallcaps-screener.git && cd smallcaps-screener
sudo chgrp -R apps . && chmod -R g+rwX,o-rwx . && find . -type d -exec chmod g+s {} +
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
sudo install -d -o screener -g apps -m 2770 data
# secrets, from the workstation (values never printed):
#   grep -E '^(EDGAR_USER_AGENT|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=' .env \
#     | ssh hetzner-vps 'sudo install -o screener -g screener -m 0600 /dev/stdin /opt/apps/smallcaps-screener/.env'
#   (same for config/local.yml, sections finviz + earnings only)
sudo install -m 0644 deploy/earnings-*.service deploy/earnings-*.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now earnings-alert.timer earnings-bounds.timer
# alerts page (Epic 15 S5)
(cd frontend && npm install -s --no-audit --no-fund --no-package-lock && npx vite build)
sudo install -m 0644 deploy/screener-web.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now screener-web
```

### Redeploy `main` (after each merge)

```bash
ssh hetzner-vps 'cd /opt/apps/smallcaps-screener && git fetch -q origin && git checkout -q main && git reset -q --hard origin/main && .venv/bin/pip install -q -r requirements.txt && (cd frontend && npm install -s --no-audit --no-fund --no-package-lock && npx vite build) && sudo install -m 0644 deploy/earnings-*.service deploy/earnings-*.timer deploy/screener-web.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart screener-web && git log --oneline -1 && systemctl list-timers "earnings-*" --no-pager && systemctl is-active screener-web'
```

The timers need no restart: each run starts a fresh process that reads the code on disk.
`screener-web` keeps the code in memory, hence the `restart`.

### Alerts page

- **Source = read-only route, not a published file**: `GET /api/alerts` (`backend/api.py`)
  reads `data/earnings/alerts.jsonl` at each request and adds, per line, the session of
  each horizon (`exit`) so the page can tell "not yet due" from "due, no price"; `net`
  (measured return, `config/local.yml`) comes in the same payload. A static file would
  need a second write step in the job and still a process to serve it (Traefik serves no
  files): no saving, one more thing to keep in sync.
- **Who can see it**: nobody from the internet. `screener-web` listens on `127.0.0.1:8019`
  only (no ufw rule, no Traefik router), because the page shows the measured return, which
  is private. Read it from any machine holding the `hetzner-vps` SSH key:

  ```bash
  ssh -N -L 8019:127.0.0.1:8019 hetzner-vps    # then open http://localhost:8019
  ```

- **Public access later** (not done): the VPS Traefik (`/root/infra/traefik/dynamic/*.yml`,
  file provider, Let's Encrypt) can route a host to `http://172.18.0.1:8019` behind a
  `basicAuth` middleware, as `booking-concierge.yml` does. It needs an `A` record
  (`*.code-art.ch` resolves to another host), `--host 172.18.0.1` in the unit and a ufw rule
  `allow from 172.18.0.0/16 to any port 8019`.
- On the workstation, `vite dev` serves the page and relays `/api` to the local backend,
  whose journal is empty: the real journal lives only on the VPS.

### Checks

```bash
ssh hetzner-vps 'systemctl list-timers "earnings-*" --no-pager'                # next runs
ssh hetzner-vps 'sudo journalctl -u earnings-alert -u earnings-bounds -n 50 --no-pager'
ssh hetzner-vps 'sudo systemctl start earnings-alert.service'                   # run now (blocks until done)
ssh hetzner-vps 'sudo tail -n 3 /opt/apps/smallcaps-screener/data/earnings/alerts.jsonl'
```

## Local Docker run (workstation)

The workstation runs only the page and an empty local API (its journal is empty: the real
journal lives on the VPS). Ports are published on `127.0.0.1` only: the route `/api/alerts`
serves the measured gain, which is private.

```bash
cp .env.example .env
docker compose up --build
```

| Service | Address | Description |
| --- | --- | --- |
| `backend` | `127.0.0.1:8000` | FastAPI (`/api/health`, `/api/alerts`), `uvicorn --reload`. |
| `frontend` | `127.0.0.1:5173` | Vite dev server, relays `/api` to `backend`. |

The backend image (`backend/Dockerfile`, `python:3.11-slim`) copies `backend/` and runs
`uvicorn api:app`; the frontend image (`frontend/Dockerfile`, `node:20-alpine`) runs
`npm run dev -- --host`. `docker-compose.yml` mounts the named volume `data` at `/app/data`
and `./config` at `/app/config`.

## Private config overlay

The edge values (kept tiers, measured gain, Finviz link and token, lake path) are **not in the
repo**: they load at startup from `config/local.yml` (gitignored, template
`config/local.example.yml`). Copy a complete file onto the host before starting the code, and
set `REQUIRE_LOCAL_CONFIG=1` so a start without it is refused. On the VPS the file holds the
sections `finviz` and `earnings` only (`0600`, user `screener`).

## Environment

`.env.example` carries the variable names, never values.

| Variable | Used by | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Job | Alert and failure messages. Absent: sending disabled. |
| `EDGAR_USER_AGENT` | Job, study | SEC identifying UA (name + email). Absent: EDGAR disabled. |
| `REQUIRE_LOCAL_CONFIG` | Backend | `1`: refuse to start without `config/local.yml`. |
| `DATA_DIR` | Backend | Journal, bounds and caches (default `/app/data`). |

## Operational checks (workstation)

```bash
curl http://127.0.0.1:8000/api/health
docker compose logs -f backend
make check-secrets     # no secret value in a versioned file
```

## Hardening checklist

- Restrict CORS origins in `backend/api.py` before any public exposure.
- Disable Uvicorn `--reload` outside development.
- Public access to the page needs DNS, a Traefik router and basic auth (see *Alerts page*).
