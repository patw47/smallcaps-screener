"""
SmallCaps Screener — API FastAPI.

Le scan, son cache et le suivi de performance ont été supprimés par la refonte de
l'Epic 15 (Sprint 2). Reste la page des alertes (Sprint 5) : `/api/alerts` lit le
journal écrit par `run_earnings.py`, et, sur le VPS, la page compilée
(`frontend/dist`) est servie par la même application.
"""

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import screener_backend  # noqa: F401  charge config/local.yml au démarrage (refus si invalide)
import earnings as er
import run_earnings as rj

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

app = FastAPI(title="SmallCaps Screener API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", summary="Health check")
async def health():
    return {"status": "ok", "timestamp": datetime.now(tz=timezone.utc).isoformat()}


@app.get("/api/alerts", summary="Journal des alertes (lecture seule)")
def alerts():
    """Journal tel qu'écrit par le job, plus la séance de sortie de chaque horizon (`exit`)
    pour que la page distingue « pas encore échu » de « échu sans cours ». `net` = rendement
    mesuré sur l'historique, lu dans config/local.yml (vide par défaut)."""
    lines = rj.read_journal()
    for x in lines:
        fc = date.fromisoformat(x["session"])
        x["exit"] = {h: f"{rj.exit_session(fc, h):%Y-%m-%d}" for h in rj.HORIZONS}
    return {"last_session": f"{er.last_session():%Y-%m-%d}", "horizons": list(rj.HORIZONS),
            "net": er.CFG["net"], "lines": lines}


# Page compilée (VPS) : montée en dernier, les routes /api passent avant. Absente sur le
# poste (vite dev sert la page et relaie /api) : rien n'est monté.
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="page")
