"""
SmallCaps Screener — API FastAPI.

Le scan, son cache et le suivi de performance ont été supprimés par la refonte de
l'Epic 15 (Sprint 2) ; les routes de la page des alertes arrivent au Sprint 5.
"""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import screener_backend  # noqa: F401  charge config/local.yml au démarrage (refus si invalide)

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
