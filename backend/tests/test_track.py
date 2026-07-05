"""Tests offline du suivi de performance (snapshots + agrégation), sans réseau."""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import json
from datetime import date
from pathlib import Path

import pandas as pd

import screener_backend as sb
import track
from track import load_first_flagged, _value_on_or_after, _stats, run_tracker, _parse_date


def test_write_snapshot_roundtrip(tmp_path):
    sb.HISTORY_DIR = tmp_path / "history"        # rediriger vers un dossier propre
    output = {
        "scanned_at": "2026-07-01T00:00:00+00:00",
        "stocks": [{
            "ticker": "AAA", "score": 8, "price": 10.0, "sector": "Tech",
            "accumulation": True, "compressed": True, "near_pivot": True, "rs_strength": 0.3,
        }],
    }
    sb._write_snapshot(output)
    files = list((tmp_path / "history").glob("*.json"))
    assert len(files) == 1
    snap = json.loads(files[0].read_text())
    assert snap["candidates"] == 1
    assert snap["picks"][0]["ticker"] == "AAA"
    assert snap["picks"][0]["price"] == 10.0


def test_load_first_flagged_uses_earliest(tmp_path):
    hd = tmp_path / "h"
    hd.mkdir()
    # nom chronologique = ordre de lecture ; A apparaît d'abord à 10, puis à 12
    (hd / "20260101_000000.json").write_text(json.dumps(
        {"scanned_at": "2026-01-01T00:00:00+00:00", "picks": [{"ticker": "A", "price": 10.0, "score": 7}]}))
    (hd / "20260102_000000.json").write_text(json.dumps(
        {"scanned_at": "2026-01-02T00:00:00+00:00",
         "picks": [{"ticker": "A", "price": 12.0, "score": 8}, {"ticker": "B", "price": 5.0, "score": 6}]}))
    picks = load_first_flagged(hd)
    assert picks["A"]["price"] == 10.0                 # première apparition, pas la plus récente
    assert picks["A"]["date"].startswith("2026-01-01")
    assert picks["B"]["price"] == 5.0


def test_value_on_or_after():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
    assert _value_on_or_after(s, date(2026, 1, 3)) == 3.0   # pile
    assert _value_on_or_after(s, date(2026, 1, 10)) is None  # rien après


def test_stats_hit_rate():
    s = _stats([0.2, -0.1, 0.3])   # 2 gagnants sur 3
    assert s["n"] == 3
    assert abs(s["hit"] - 2 / 3) < 1e-9


# ---------------------------------------------------------------------------
# Snapshot — capture tout ce dont le tracker a besoin (Sprint 2)
# ---------------------------------------------------------------------------

def test_snapshot_captures_tracker_fields(tmp_path):
    sb.HISTORY_DIR = tmp_path / "history"
    output = {
        "scanned_at": "2026-07-01T00:00:00+00:00",
        "stocks": [{"ticker": "AAA", "score": 8, "price": 10.0, "sector": "Tech",
                    "accumulation": True, "compressed": False, "near_pivot": True, "rs_strength": 0.3}],
    }
    sb._write_snapshot(output)
    snap = json.loads(next((tmp_path / "history").glob("*.json")).read_text())
    p = snap["picks"][0]
    # le tracker exige au minimum : date (via scanned_at), price, score
    assert snap["scanned_at"] == "2026-07-01T00:00:00+00:00"
    for key in ("ticker", "price", "score", "accumulation", "compressed", "near_pivot", "rs_strength"):
        assert key in p


# ---------------------------------------------------------------------------
# Durcissement run_tracker — /api/performance ne doit JAMAIS casser (Sprint 2)
# ---------------------------------------------------------------------------

def _write_snap(hd: Path, name: str, payload: dict):
    hd.mkdir(exist_ok=True)
    (hd / name).write_text(json.dumps(payload))


def test_parse_date_tolerant():
    assert _parse_date(None) is None
    assert _parse_date("pas-une-date") is None
    assert _parse_date("2026-01-01T00:00:00+00:00") is not None


def test_run_tracker_empty_history(tmp_path):
    r = run_tracker(tmp_path / "vide", quiet=True)
    assert r["n_picks"] == 0
    assert "message" in r
    # forme homogène avec les autres retours (pas de payload dégradé)
    for key in ("n_tracked", "overall", "excess_mean", "high_score", "low_score", "rows", "as_of"):
        assert key in r
    assert r["n_tracked"] == 0 and r["overall"]["n"] == 0


def test_run_tracker_survives_download_failure(tmp_path, monkeypatch):
    hd = tmp_path / "h"
    _write_snap(hd, "20260101_000000.json",
                {"scanned_at": "2026-01-01T00:00:00+00:00",
                 "picks": [{"ticker": "AAA", "price": 10.0, "score": 8}]})

    def boom(*a, **k):
        raise RuntimeError("réseau indispo")
    monkeypatch.setattr(track, "_download_prices", boom)

    r = run_tracker(hd, quiet=True)   # ne doit pas lever
    assert r["n_picks"] == 1
    assert r["n_tracked"] == 0
    assert "message" in r
    assert r["overall"]["n"] == 0     # réponse bien formée, exploitable par l'API


def test_run_tracker_ignores_missing_dates_and_bad_tickers(tmp_path, monkeypatch):
    hd = tmp_path / "h"
    # snapshot SANS scanned_at → date None ; picks avec prix manquant
    _write_snap(hd, "20260101_000000.json",
                {"picks": [{"ticker": "NODATE", "price": 10.0, "score": 8},
                           {"ticker": "NOPRICE", "price": None, "score": 3}]})
    monkeypatch.setattr(track, "_download_prices", lambda *a, **k: {})  # aucun cours

    r = run_tracker(hd, quiet=True)   # ne doit pas lever malgré date None / prix None
    assert r["n_tracked"] == 0


def test_run_tracker_computes_returns(tmp_path, monkeypatch):
    hd = tmp_path / "h"
    _write_snap(hd, "20260101_000000.json",
                {"scanned_at": "2026-01-01T00:00:00+00:00",
                 "picks": [{"ticker": "AAA", "price": 10.0, "score": 8}]})

    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    aaa = pd.DataFrame({"Close": [10.0] * 9 + [12.0]}, index=idx)   # +20%
    iwm = pd.DataFrame({"Close": [100.0] * 10}, index=idx)          # plat
    monkeypatch.setattr(track, "_download_prices",
                        lambda tks, bench, period=None: {"AAA": aaa, sb.FILTERS["rs_benchmark"]: iwm})

    r = run_tracker(hd, quiet=True)
    assert r["n_tracked"] == 1
    assert abs(r["overall"]["mean"] - 0.20) < 1e-9
    assert abs(r["excess_mean"] - 0.20) < 1e-9   # bench plat → excès = rendement


# ---------------------------------------------------------------------------
# Sleeves par profil (Validation B) + métriques de queue +50%/+100% (Sprint 4)
# ---------------------------------------------------------------------------

def test_run_tracker_sleeves_and_tail_counts(tmp_path, monkeypatch):
    hd = tmp_path / "h"
    _write_snap(hd, "20260101_000000.json",
                {"scanned_at": "2026-01-01T00:00:00+00:00",
                 "picks": [
                     {"ticker": "FUS", "price": 10.0, "score": 8, "is_fusee": True, "is_phenix": False},
                     {"ticker": "PHX", "price": 5.0, "score": 6, "is_fusee": False, "is_phenix": True},
                 ]})
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    fus = pd.DataFrame({"Close": [10.0] * 9 + [16.0]}, index=idx)   # +60% → +50% oui, +100% non
    phx = pd.DataFrame({"Close": [5.0] * 9 + [11.0]}, index=idx)    # +120% → +50% et +100%
    iwm = pd.DataFrame({"Close": [100.0] * 10}, index=idx)
    monkeypatch.setattr(track, "_download_prices",
                        lambda tks, bench, period=None: {"FUS": fus, "PHX": phx, sb.FILTERS["rs_benchmark"]: iwm})

    r = run_tracker(hd, quiet=True)
    sl = r["sleeves"]
    assert sl["fusee"]["n"] == 1 and sl["phenix"]["n"] == 1 and sl["overall"]["n"] == 2
    assert sl["fusee"]["n_up50"] == 1 and sl["fusee"]["n_up100"] == 0
    assert sl["phenix"]["n_up50"] == 1 and sl["phenix"]["n_up100"] == 1
    assert sl["overall"]["n_up50"] == 2 and sl["overall"]["n_up100"] == 1
    assert sl["unknown"]["n"] == 0


def test_run_tracker_mixed_history_backfill(tmp_path, monkeypatch):
    # Historique MIXTE : un vieux snapshot SANS champs profil + un nouveau AVEC.
    # Ne doit jamais lever ; l'ancien tombe dans la sleeve "unknown".
    hd = tmp_path / "h"
    _write_snap(hd, "20260101_000000.json",
                {"scanned_at": "2026-01-01T00:00:00+00:00",
                 "picks": [{"ticker": "OLD", "price": 10.0, "score": 7}]})            # pré-profil
    _write_snap(hd, "20260102_000000.json",
                {"scanned_at": "2026-01-02T00:00:00+00:00",
                 "picks": [{"ticker": "NEW", "price": 8.0, "score": 6, "is_fusee": True, "is_phenix": False}]})
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    old = pd.DataFrame({"Close": [10.0] * 10}, index=idx)                 # plat
    new = pd.DataFrame({"Close": [8.0] * 9 + [12.0]}, index=idx)          # +50%
    iwm = pd.DataFrame({"Close": [100.0] * 10}, index=idx)
    monkeypatch.setattr(track, "_download_prices",
                        lambda tks, bench, period=None: {"OLD": old, "NEW": new, sb.FILTERS["rs_benchmark"]: iwm})

    r = run_tracker(hd, quiet=True)      # ne doit pas lever malgré l'historique mixte
    assert r["n_tracked"] == 2
    assert r["sleeves"]["unknown"]["n"] == 1     # OLD (sans profil) → unknown
    assert r["sleeves"]["fusee"]["n"] == 1       # NEW → fusée
    assert r["sleeves"]["fusee"]["n_up50"] == 1  # NEW +50% compté
    assert r["sleeves"]["overall"]["n"] == 2


def test_empty_result_carries_sleeves(tmp_path):
    # Forme homogène : même sans historique, le bloc sleeves existe et est bien formé.
    r = run_tracker(tmp_path / "vide", quiet=True)
    for name in ("overall", "fusee", "phenix", "unknown"):
        assert name in r["sleeves"]
        assert r["sleeves"][name]["n"] == 0
        assert r["sleeves"][name]["n_up50"] == 0 and r["sleeves"][name]["n_up100"] == 0
