"""Tests offline du suivi de performance (snapshots + agrégation), sans réseau."""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import json
from datetime import date

import pandas as pd

import screener_backend as sb
from track import load_first_flagged, _value_on_or_after, _stats


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
