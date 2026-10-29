# API Reference

Base URL (workstation, Docker Compose, published on loopback): `http://127.0.0.1:8000`; on the
VPS, `http://127.0.0.1:8019` through an SSH tunnel ([deployment.md](deployment.md)). All routes
are under `/api`. The former scan, watchlist, stock and performance routes were removed in
Epic 15 S2.

## `GET /api/alerts`

Read-only journal of the earnings alerts (`data/earnings/alerts.jsonl`, written by
`run_earnings.py`), read at each request. Served on the VPS (`docs/deployment.md`).

```json
{
  "last_session": "YYYY-MM-DD",
  "horizons": [5, 21, 63],
  "net": {"5": "<measured return, config/local.yml; {} by default>"},
  "lines": [{"ticker": "…", "session": "YYYY-MM-DD", "entry": "YYYY-MM-DD", "sue": 0.0, "risk": [],
             "ret_5": null, "iwm_5": null, "exit": {"5": "YYYY-MM-DD", "21": "…", "63": "…"}}]
}
```

`exit[h]` = the h-th session after `session`: a cell still empty with `exit[h]` before
`last_session` is shown as "no price" and counted apart from the average.

## `GET /api/health`

Health check endpoint.

Response:

```json
{
  "status": "ok",
  "timestamp": "2026-05-05T10:00:00+00:00"
}
```

## CORS

The FastAPI app allows all origins, methods and headers. This is acceptable because the API
listens on loopback only (VPS: `127.0.0.1:8019`; workstation: `127.0.0.1:8000`). Restrict it
before any public exposure.
