# Frontend

One page: the post-earnings alerts and their journal (Epic 15 S5). React 18 + Vite 5, French
and English. The page carries **no threshold and no measured value in the source**: the
measured gain comes from `GET /api/alerts` (read from `config/local.yml`, empty by default),
and every text is an i18n key (`make check-jargon` forbids version numbers and internal
vocabulary on screen).

## Files

- `frontend/src/main.jsx`: React entry point.
- `frontend/smallcap-screener.jsx`: the page (header, language switch, sections "Releases of the day" and "Journal").
- `frontend/journal.js`: pure logic over the `/api/alerts` payload, no DOM, no i18n (tested by `node --test`).
- `frontend/journal.test.js`: 4 tests — 3 alerts with 1 due at 21 sessions, today's releases and sort, "no price" cells outside the average, empty journal.
- `frontend/i18n/`: `fr.json`, `en.json` (strict key parity), `index.js` (`t(key, vars)`, language kept in `localStorage`), `fmt.js` (`{placeholder}` interpolation) + `fmt.test.js`, `check-parity.mjs`.
- `frontend/index.html`, `package.json`, `vite.config.js`, `Dockerfile`: Vite entry and tooling.

## Data flow

`fetch("/api/alerts")` → `summarize(payload)` → render. `summarize` returns the lines sorted
(most recent first), the lines of the last closed session (`today`), and per horizon h (5 / 21 /
63 sessions): number of due alerts, mean realized return, mean IWM return, gap, number "no
price", number "pending", and the measured gain `net` when served.

`cellState` classes each (alert, horizon) cell:

- `done`: the realized return is written;
- `pending`: the horizon session is not closed yet (or closes today, the evening job has not run);
- `missing`: the horizon session is before the last closed session and no price exists
  (delisting, suspended quote). Counted apart, out of the mean — ignoring it would silently
  drop cases that often lose.

## Rules

- Texts only through `t()`; labels `risk.*` translate the codes served by the backend.
- The measured gain is shown in a block marked as not comparable with the realized return.
- `make test-frontend` (`node --test`), `make i18n-parity`, `make check-i18n`, `make check-jargon`
  and `make build-frontend` (containerised `vite build`) are the gates.

## Development

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173, relays /api to the backend
make test-frontend
```

On the workstation the local journal is empty: the real journal lives on the VPS
([deployment.md](deployment.md)).
