"""
SmallCaps Screener — API FastAPI
Expose les données du screener au dashboard React.
Tous les endpoints sont préfixés /api/*.
"""

import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from screener_backend import run_scan, scan_state, FILTERS, OUTPUT_FILE
from track import run_tracker

# Scan automatique périodique (heures) — les snapshots s'accumulent pour le suivi de perf
SCAN_EVERY_HOURS = float(os.environ.get("SCAN_EVERY_HOURS", "24"))

app = FastAPI(title="SmallCaps Screener API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# État interne de l'API
# ---------------------------------------------------------------------------
_custom_watchlist: list[str] | None = None  # None = découverte dynamique
_last_scan_time: datetime | None = None
_cached_data: dict | None = None
_bg_scan_inflight = False  # garde : un seul scan background à la fois (event loop mono-thread)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json_cache() -> dict | None:
    if not OUTPUT_FILE.exists():
        return None
    try:
        data = json.loads(OUTPUT_FILE.read_text())
        scanned_at = datetime.fromisoformat(data["scanned_at"])
        age = datetime.now(tz=timezone.utc) - scanned_at
        if age < timedelta(minutes=FILTERS["cache_minutes"]):
            return data
    except Exception:
        pass
    return None


def _run_scan_sync():
    global _cached_data, _last_scan_time
    result = run_scan(_custom_watchlist)  # None → découverte dynamique
    _cached_data = result
    _last_scan_time = datetime.now(tz=timezone.utc)


async def _ensure_background_scan():
    """
    Démarre un scan en arrière-plan s'il n'y en a pas déjà un, sans bloquer la requête.
    La vérif+pose du drapeau est atomique (event loop mono-thread) → pas de double scan.
    """
    global _bg_scan_inflight
    if _bg_scan_inflight or scan_state["scanning"]:
        return
    _bg_scan_inflight = True

    def _job():
        global _bg_scan_inflight
        try:
            _run_scan_sync()
        finally:
            _bg_scan_inflight = False

    asyncio.get_event_loop().run_in_executor(None, _job)


def _last_result() -> dict | None:
    """Dernier résultat connu : mémoire, sinon fichier (même périmé)."""
    if _cached_data is not None:
        return _cached_data
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text())
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _warm_cache():
    """Préchauffe le cache au démarrage : lance un scan background si aucun résultat frais."""
    if _load_json_cache() is None:
        await _ensure_background_scan()


@app.on_event("startup")
async def _daily_scanner():
    """Scan automatique toutes les SCAN_EVERY_HOURS → l'historique (snapshots) s'accumule seul."""
    async def loop():
        while True:
            await asyncio.sleep(SCAN_EVERY_HOURS * 3600)
            await _ensure_background_scan()
    asyncio.create_task(loop())


@app.get("/api/scan", summary="Retourne les données (non bloquant, scan en arrière-plan)")
async def get_scan():
    # Cache frais → retour direct
    cached = _load_json_cache()
    if cached:
        return cached

    # Résultat périmé connu → stale-while-revalidate : on le sert et on rafraîchit en fond
    data = _last_result()
    if data is not None:
        await _ensure_background_scan()
        return {**data, "scanning": scan_state["scanning"], "phase": scan_state["phase"], "stale": True}

    # Aucune donnée encore → démarrer un scan et répondre IMMÉDIATEMENT (jamais de blocage)
    await _ensure_background_scan()
    return {
        "scanned_at": None, "universe_size": 0, "candidates": 0,
        "stocks": [], "rejection_stats": {},
        "scanning": scan_state["scanning"], "phase": scan_state["phase"],
    }


@app.get("/api/scan/status", summary="Statut du scan en cours")
async def get_scan_status():
    return {
        "scanning": scan_state["scanning"],
        "progress": scan_state["progress"],
        "total": scan_state["total"],
        "phase": scan_state["phase"],
        "last_scan": _last_scan_time.isoformat() if _last_scan_time else None,
    }


@app.post("/api/scan/force", summary="Force un nouveau scan (ignore le cache)")
async def force_scan():
    if _bg_scan_inflight or scan_state["scanning"]:
        raise HTTPException(409, detail="Un scan est déjà en cours")

    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()

    global _cached_data
    _cached_data = None

    await _ensure_background_scan()
    return {"message": "Nouveau scan démarré en arrière-plan"}


@app.get("/api/performance", summary="Suivi de performance des sélections dans le temps")
async def get_performance(high: int = 7):
    """
    Rendement des sélections réelles depuis leur première apparition, agrégé par
    score et comparé à IWM. Se remplit au fil des scans (historique data/history/).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: run_tracker(high_score=high, quiet=True))


@app.get("/api/stock/{ticker}", summary="Données d'un ticker depuis le dernier scan")
async def get_stock(ticker: str):
    ticker = ticker.upper()
    data = _cached_data or _load_json_cache()
    if not data:
        raise HTTPException(404, detail="Aucune donnée disponible. Lancez /api/scan d'abord.")

    for stock in data.get("stocks", []):
        if stock["ticker"] == ticker:
            return stock

    raise HTTPException(404, detail=f"Ticker {ticker} non trouvé dans les résultats du dernier scan")


@app.get("/api/watchlist", summary="Retourne la watchlist personnalisée courante")
async def get_watchlist():
    return {
        "mode": "custom" if _custom_watchlist else "dynamic",
        "tickers": _custom_watchlist,
        "count": len(_custom_watchlist) if _custom_watchlist else None,
    }


class WatchlistPayload(BaseModel):
    tickers: list[str]


@app.post("/api/watchlist", summary="Définit une watchlist personnalisée (remplace la découverte dynamique)")
async def set_watchlist(payload: WatchlistPayload):
    global _custom_watchlist
    if not payload.tickers:
        raise HTTPException(400, detail="La liste de tickers ne peut pas être vide")

    _custom_watchlist = list(dict.fromkeys(t.upper().strip() for t in payload.tickers))

    return {
        "message": f"Watchlist personnalisée définie ({len(_custom_watchlist)} tickers)",
        "tickers": _custom_watchlist,
    }


@app.delete("/api/watchlist", summary="Supprime la watchlist personnalisée (retour à la découverte dynamique)")
async def reset_watchlist():
    global _custom_watchlist
    _custom_watchlist = None
    return {"message": "Retour à la découverte dynamique"}


@app.get("/api/health", summary="Health check")
async def health():
    return {"status": "ok", "timestamp": datetime.now(tz=timezone.utc).isoformat()}
