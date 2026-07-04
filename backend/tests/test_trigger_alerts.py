"""
Tests offline du trigger de cassure et de l'alerte Telegram (Sprint 3).

Déterministes, sans réseau : le trigger est une fonction pure (`_breakout`) nourrie de
DataFrames synthétiques ; l'alerte est testée avec un `send_fn` factice (aucun appel
réseau) et un fichier d'état temporaire.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_trigger_alerts.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")  # évite makedirs("/app/data")

from datetime import datetime, timezone, timedelta

import pandas as pd

import alerts
from screener_backend import _breakout, analyze_prices, FILTERS


# ---------------------------------------------------------------------------
# Trigger — _breakout (pur)
# ---------------------------------------------------------------------------

def _breakout_df(last_close, last_vol, base_high=10.5, base_close=10.0, base_vol=1000, n=60):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    highs = [base_high] * (n - 1) + [max(last_close, base_high)]
    closes = [base_close] * (n - 1) + [last_close]
    lows = [base_close - 1.0] * n
    vols = [base_vol] * (n - 1) + [last_vol]
    return pd.DataFrame({"High": highs, "Low": lows, "Close": closes, "Volume": vols}, index=idx)


def test_breakout_fires_on_price_and_volume():
    df = _breakout_df(last_close=12.0, last_vol=5000)   # close > pivot (10.5) ET volume 5x
    triggered, days, pivot = _breakout(df, df["Close"], df["Volume"])
    assert triggered is True
    assert days == 0           # cassure du jour = 0 séance écoulée
    assert pivot == 10.5       # plus-haut des jours précédents (séance courante exclue)


def test_breakout_needs_volume_confirmation():
    df = _breakout_df(last_close=12.0, last_vol=1000)   # au-dessus du pivot mais volume plat
    triggered, days, pivot = _breakout(df, df["Close"], df["Volume"])
    assert triggered is False
    assert days == 0           # le prix est au-dessus du pivot, mais pas de confirmation volume
    assert pivot == 10.5


def test_breakout_days_since_counts_multiday():
    # 3 séances au-dessus du pivot as-of + rally continu → days_since = 2 (pas dégénéré à 0).
    win = FILTERS["pivot_window"]
    n = win + 3
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    highs = [10.5] * win + [11.0, 12.0, 13.0]
    closes = [10.0] * win + [11.0, 12.0, 13.0]
    lows = [9.0] * n
    vols = [1000] * (n - 1) + [9000]
    df = pd.DataFrame({"High": highs, "Low": lows, "Close": closes, "Volume": vols}, index=idx)
    triggered, days, pivot = _breakout(df, df["Close"], df["Volume"])
    assert days == 2           # cassure il y a 2 séances (compté vs le pivot de chaque jour)
    assert pivot == 12.0       # plus-haut des `win` jours précédant la séance courante
    assert triggered is True


def test_breakout_no_price_break():
    df = _breakout_df(last_close=10.0, last_vol=5000)   # sous le pivot
    triggered, days, pivot = _breakout(df, df["Close"], df["Volume"])
    assert triggered is False
    assert days is None        # prix pas au-dessus du pivot → non défini


def test_breakout_insufficient_history():
    df = _breakout_df(last_close=12.0, last_vol=5000, n=10)  # < pivot_window + 1
    assert _breakout(df, df["Close"], df["Volume"]) == (False, None, None)


def test_analyze_prices_exposes_trigger_fields():
    # uptrend sain (réutilise le motif des tests Passe A) → les champs trigger existent
    closes = [10.0 + i * 0.05 for i in range(200)]
    idx = pd.date_range("2025-01-01", periods=200, freq="B")
    df = pd.DataFrame({"High": [c + 0.2 for c in closes], "Low": [c - 0.2 for c in closes],
                       "Close": closes, "Volume": [200_000] * 200}, index=idx)
    signals, reason = analyze_prices("UP", df, None)
    assert reason == "ok"
    for key in ("triggered", "days_since_trigger", "pivot_level"):
        assert key in signals


# ---------------------------------------------------------------------------
# Alerte Telegram — dedup, min_score, désactivation silencieuse
# ---------------------------------------------------------------------------

def _cand(ticker, fusee_event=True, setup_score=8, price=12.0):
    # Epic 2 : l'alerte fire sur le variant ÉVÉNEMENT de Fusée (membre Fusée + cassure du jour).
    return {"ticker": ticker, "triggered": True, "fusee_event": fusee_event,
            "is_fusee": fusee_event, "setup_score": setup_score,
            "price": price, "pivot_level": 10.5}


def test_alert_fires_exactly_once_then_dedups(tmp_path):
    sent = []
    def fake_send(text):
        sent.append(text)
        return True

    cands = [_cand("AAA")]
    sp = tmp_path / "alerts_state.json"
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    first = alerts.notify_new_triggers(cands, state_path=sp, min_score=7, dedup_days=5,
                                       now=now, send_fn=fake_send)
    assert first == ["AAA"]
    assert len(sent) == 1
    assert sp.exists()

    # même scan peu après → anti-doublon : rien renvoyé, aucun nouvel envoi
    second = alerts.notify_new_triggers(cands, state_path=sp, min_score=7, dedup_days=5,
                                        now=now + timedelta(days=1), send_fn=fake_send)
    assert second == []
    assert len(sent) == 1


def test_alert_refires_after_dedup_window(tmp_path):
    sent = []
    cands = [_cand("AAA")]
    sp = tmp_path / "s.json"
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    alerts.notify_new_triggers(cands, state_path=sp, min_score=7, dedup_days=5,
                               now=now, send_fn=lambda t: sent.append(t) or True)
    later = now + timedelta(days=6)   # au-delà de la fenêtre anti-doublon
    again = alerts.notify_new_triggers(cands, state_path=sp, min_score=7, dedup_days=5,
                                       now=later, send_fn=lambda t: sent.append(t) or True)
    assert again == ["AAA"]
    assert len(sent) == 2


def test_alert_skips_low_score_and_non_fusee_event(tmp_path):
    # LOW : membre Fusée mais setup_score < min → skip.
    # PLAINTRIG : cassure (triggered) mais PAS un événement Fusée → ne doit plus alerter.
    cands = [_cand("LOW", setup_score=3), _cand("PLAINTRIG", fusee_event=False, setup_score=9)]
    out = alerts.notify_new_triggers(cands, state_path=tmp_path / "s.json", min_score=7,
                                     dedup_days=5, send_fn=lambda t: True)
    assert out == []


def test_alert_silently_disabled_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sp = tmp_path / "s.json"
    out = alerts.notify_new_triggers([_cand("AAA")], state_path=sp, min_score=7,
                                     dedup_days=5, send_fn=alerts.send_telegram)
    assert out == []            # aucune alerte
    assert not sp.exists()      # état non écrit → le ticker reste éligible plus tard


def test_alert_failed_send_not_recorded(tmp_path):
    sp = tmp_path / "s.json"
    out = alerts.notify_new_triggers([_cand("AAA")], state_path=sp, min_score=7,
                                     dedup_days=5, send_fn=lambda t: False)
    assert out == []
    assert not sp.exists()      # échec d'envoi → pas d'enregistrement, retry au prochain scan
