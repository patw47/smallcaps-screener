"""
Test d'invariance de l'extraction de l'edge (Epic 6 S2) — offline, local uniquement.

Preuve que déplacer les constantes gelées v5 vers config/local.yml est une
RELOCALISATION et pas un tuning : avec la vraie config chargée,
① chaque entrée de cohorte consignée dans data/history/ (produite par le code
  d'AVANT l'extraction) satisfait bit à bit les règles configurées, et
② les seuils configurés pilotent réellement build_cohorts (sémantique ≤ / <
  du protocole vérifiée aux bornes).

Lancer : make test-invariance. Skip propre si config/local.yml absent (donc
skippé en CI — la vraie config n'est jamais versionnée).
"""
import os

os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import screener_backend as sb
import v5

REPO = Path(__file__).resolve().parents[2]
CONFIG = Path(os.environ.get("CONFIG_FILE", REPO / "config" / "local.yml"))
HISTORY = Path(os.environ.get("HISTORY_DIR", REPO / "data" / "history"))

pytestmark = pytest.mark.skipif(
    not CONFIG.exists(),
    reason="config/local.yml absent — invariance vérifiable en local seulement",
)


@pytest.fixture
def real_cfg(monkeypatch):
    """v4.CFG / v5.CFG rechargés depuis la VRAIE config (écrase les valeurs de test)."""
    import v4
    monkeypatch.setattr(v4, "CFG", copy.deepcopy(v4.CFG))
    monkeypatch.setattr(v5, "CFG", copy.deepcopy(v5.CFG))
    filters = copy.deepcopy(sb.FILTERS)
    sb.load_local_config(path=CONFIG, filters=filters)
    return filters


def _v5_snapshots():
    snaps = []
    for f in sorted(HISTORY.glob("*.json")):
        try:
            snap = json.loads(f.read_text())
        except Exception:
            continue
        if (snap.get("v5") or {}).get("windows"):
            snaps.append((f.name, snap["v5"]))
    return snaps


def test_recorded_cohorts_satisfy_configured_rules(real_cfg):
    """Rejeu : les cohortes historiques restent qualifiées sous les règles configurées."""
    snaps = _v5_snapshots()
    if not snaps:
        pytest.skip("aucun snapshot v5 dans data/history/")
    cfg = v5.CFG
    checked = 0
    for name, block in snaps:
        assert set(block["windows"]) <= {str(w) for w in cfg["windows"]}, name
        for w, wb in block["windows"].items():
            for e in wb.get("cohort") or []:
                # tolérance = un demi-pas d'arrondi des valeurs consignées
                assert e["price"] <= cfg["price_max"], (name, w, e)
                assert e["chg"] <= cfg["chg_max"] + 5e-5, (name, w, e)
                assert e["cmf"] > cfg["cmf_min"] - 5e-4, (name, w, e)
                assert e["vol_calm"] <= cfg["volcalm_max"] + 5e-3, (name, w, e)
                assert wb["mkt"] < 0, (name, w)
                checked += 1
    if checked == 0:
        pytest.skip("aucune entrée de cohorte v5 consignée pour l'instant")


def _df(chg7: float, vol_mult: float = 1.0, n: int = 140) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=n)
    closes = np.full(n, 1.0)
    closes[-7:] = np.linspace(1.0, 1.0 + chg7, 7)
    vols = np.full(n, 100_000.0)
    vols[-7:] *= vol_mult
    return pd.DataFrame({"Close": pd.Series(closes, index=idx),
                         "Volume": pd.Series(vols, index=idx)})


def test_configured_thresholds_drive_cohorts(real_cfg, monkeypatch):
    """Bornes : chaque règle inclut/exclut selon la valeur configurée (≤ / < du protocole)."""
    import edgar
    monkeypatch.setattr(edgar, "survival_signals",
                        lambda tk, now=None, window_days=None: {"dilution_flag": False})
    cfg = v5.CFG
    bench = pd.Series(np.cumprod([1.0] + [1 - 0.002] * 200),
                      index=pd.bdate_range("2024-06-01", periods=201))
    ok_cmf = cfg["cmf_min"] + 0.01
    deep = cfg["chg_max"] - 0.01
    tradables = [
        ("ATPRICE", {"price": cfg["price_max"], "cmf": ok_cmf}),          # prix = seuil → inclus (≤)
        ("OVPRICE", {"price": cfg["price_max"] + 0.01, "cmf": ok_cmf}),   # au-dessus → exclu
        ("SHALLOW", {"price": 1.0, "cmf": ok_cmf}),                       # chute > seuil → exclu
        ("ATCMF",   {"price": 1.0, "cmf": cfg["cmf_min"]}),               # CMF = seuil → exclu (strict >)
        ("LOUD",    {"price": 1.0, "cmf": ok_cmf}),                       # volume > seuil → exclu
    ]
    prices = {
        "ATPRICE": _df(deep), "OVPRICE": _df(deep),
        "SHALLOW": _df(cfg["chg_max"] + 0.02),
        "ATCMF": _df(deep),
        "LOUD": _df(deep, vol_mult=cfg["volcalm_max"] + 0.2),
    }
    out = v5.build_cohorts(tradables, prices, bench)
    b7 = out["windows"]["7"]
    assert [e["ticker"] for e in b7["cohort"]] == ["ATPRICE"], b7
    # drapeau ⚡ : juste sous le seuil configuré → levé ; baisse ordinaire → non
    tail = (1 + cfg["flash_thr"] - 0.005) ** (1 / 3) - 1
    flashy = pd.Series(np.cumprod([1.0] + [1.001] * 190 + [1 + tail] * 3),
                       index=pd.bdate_range("2024-06-01", periods=194))
    assert v5.build_cohorts([], {}, flashy)["flash"] is True
    assert out["flash"] is False
