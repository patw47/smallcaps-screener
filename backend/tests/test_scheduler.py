"""
Tests offline du planificateur de scan automatique (Sprint 2).

On vérifie la porte « jours de bourse » (`_is_trading_day`) sans démarrer le serveur :
l'import de `api` ne déclenche aucun scan ni réseau (les handlers startup ne tournent
que sous uvicorn).

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_scheduler.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")  # évite makedirs("/app/data")

from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")  # api.py dépend de FastAPI ; test sauté si absent (env offline nu)

import api


def test_is_trading_day_weekday():
    # 2026-07-02 = jeudi
    assert api._is_trading_day(datetime(2026, 7, 2, tzinfo=timezone.utc)) is True


def test_is_trading_day_weekend():
    # 2026-07-04 = samedi, 2026-07-05 = dimanche
    assert api._is_trading_day(datetime(2026, 7, 4, tzinfo=timezone.utc)) is False
    assert api._is_trading_day(datetime(2026, 7, 5, tzinfo=timezone.utc)) is False


def test_trading_days_flag_default_true():
    # activé par défaut : 1 scan par jour de bourse (week-ends sautés)
    assert api.SCAN_TRADING_DAYS_ONLY is True
