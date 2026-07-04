"""
Tests offline des détecteurs de profils Fusée & Phénix (Epic 2, Sprint 2).

Déterministes, sans réseau : cross-sections synthétiques construites à la main, aux
valeurs choisies pour que les seuils de percentile tombent à des positions connues.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_profiles.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import re
from pathlib import Path

import pandas as pd

from screener_backend import FILTERS, analyze_prices
from profiles import detect_profiles, profile_thresholds, rank_members


def _sig(rs=None, perf=None, p52=0.9, atr=9.0, price=10.0, sma20=11.0, triggered=False,
         dollar_volume=1_000_000):
    """
    Signal synthétique. Défauts NEUTRES : rs/perf None → jamais Fusée ; sma20 (11) > price (10)
    → jamais Phénix (garde close ≥ SMA20 fausse). Chaque test active le profil visé.
    """
    return {"rs_strength": rs, "change_1m": perf, "pct_52w_high": p52, "atr_ratio": atr,
            "price": price, "sma20": sma20, "triggered": triggered, "dollar_volume": dollar_volume}


# ---------------------------------------------------------------------------
# Appartenance Fusée — top 80e percentile sur rs63 ET perf_1m
# ---------------------------------------------------------------------------

def test_fusee_membership_top_percentile():
    # rs=perf=0..9 : quantile(0.8) = 7.2 → seuls 8 et 9 sont ≥ P80 sur les DEUX axes.
    sigs = [_sig(rs=float(i), perf=float(i)) for i in range(10)]
    detect_profiles(sigs)
    assert [i for i, s in enumerate(sigs) if s["is_fusee"]] == [8, 9]
    assert not any(s["is_phenix"] for s in sigs)          # garde SMA20 → aucun Phénix
    # force croissante avec la profondeur du momentum
    assert sigs[9]["fusee_strength"] >= sigs[8]["fusee_strength"]
    assert sigs[9]["profile"] == "fusee" and sigs[9]["profiles"] == ["fusee"]


def test_fusee_needs_both_axes():
    # rs et perf ANTI-corrélés : le meilleur en perf est le pire en rs (et inversement)
    # → personne n'est simultanément ≥ P80 sur les DEUX axes → aucun Fusée.
    sigs = [_sig(rs=float(9 - i), perf=float(i)) for i in range(10)]
    detect_profiles(sigs)
    assert not any(s["is_fusee"] for s in sigs)


# ---------------------------------------------------------------------------
# Appartenance Phénix — bas 20e (pct_52w) ET bas 40e (atr) ET close ≥ SMA20
# ---------------------------------------------------------------------------

def test_phenix_membership_bottom_percentile():
    # rs/perf None → pas de Fusée. p52=i/10 : quantile(0.2)=0.18 → i∈{0,1}.
    # atr=0..9 : quantile(0.4)=3.6 → i∈{0,1,2,3}. close(10) ≥ sma20(9). ∩ = {0,1}.
    sigs = [_sig(p52=i / 10, atr=float(i), price=10.0, sma20=9.0) for i in range(10)]
    detect_profiles(sigs)
    assert [i for i, s in enumerate(sigs) if s["is_phenix"]] == [0, 1]
    assert not any(s["is_fusee"] for s in sigs)
    # plus bas dans le range 52 sem. = plus « massacré » = force plus élevée
    assert sigs[0]["phenix_strength"] >= sigs[1]["phenix_strength"]


def test_phenix_requires_stabilization_gate():
    # même population Phénix mais close < SMA20 partout → la garde de stabilisation coupe tout.
    sigs = [_sig(p52=i / 10, atr=float(i), price=10.0, sma20=11.0) for i in range(10)]
    detect_profiles(sigs)
    assert not any(s["is_phenix"] for s in sigs)


# ---------------------------------------------------------------------------
# Les deux profils possibles simultanément
# ---------------------------------------------------------------------------

def test_both_profiles_possible():
    sigs = [
        _sig(rs=1.0, perf=1.0, p52=0.8, atr=8.0, price=10.0, sma20=11.0),
        _sig(rs=2.0, perf=2.0, p52=0.7, atr=7.0, price=10.0, sma20=11.0),
        _sig(rs=3.0, perf=3.0, p52=0.6, atr=6.0, price=10.0, sma20=11.0),
        _sig(rs=4.0, perf=4.0, p52=0.5, atr=5.0, price=10.0, sma20=11.0),
        # extrême de momentum ET massacré/comprimé/stabilisé → les deux profils
        _sig(rs=9.0, perf=9.0, p52=0.05, atr=0.5, price=10.0, sma20=9.0),
    ]
    detect_profiles(sigs)
    assert sigs[4]["is_fusee"] and sigs[4]["is_phenix"]
    assert sigs[4]["profile"] == "both"
    assert set(sigs[4]["profiles"]) == {"fusee", "phenix"}
    assert sigs[4]["profile_strength"] == max(sigs[4]["fusee_strength"], sigs[4]["phenix_strength"])


# ---------------------------------------------------------------------------
# Variant événement Fusée (membre + cassure le jour même)
# ---------------------------------------------------------------------------

def test_fusee_event_requires_trigger():
    sigs = [_sig(rs=float(i), perf=float(i)) for i in range(10)]
    sigs[9]["triggered"] = True
    detect_profiles(sigs)
    assert sigs[9]["is_fusee"] and sigs[9]["fusee_event"] is True
    assert sigs[8]["is_fusee"] and sigs[8]["fusee_event"] is False   # membre mais pas de cassure


# ---------------------------------------------------------------------------
# Robustesse : valeurs manquantes, univers vide
# ---------------------------------------------------------------------------

def test_missing_values_never_member():
    sigs = [_sig(rs=float(i), perf=float(i)) for i in range(9)]
    sigs.append(_sig(rs=None, perf=None))          # pas de RS → jamais Fusée
    detect_profiles(sigs)
    assert sigs[-1]["is_fusee"] is False

    ph = [_sig(p52=0.01, atr=None, price=10.0, sma20=9.0) for _ in range(5)]  # atr None → jamais Phénix
    detect_profiles(ph)
    assert all(s["is_phenix"] is False for s in ph)


def test_empty_universe_guard():
    assert detect_profiles([]) is None            # ne lève pas, ne renvoie rien


# ---------------------------------------------------------------------------
# Sélection run_scan : ne garde que les membres, classés par force
# ---------------------------------------------------------------------------

def test_rank_members_keeps_only_members_sorted():
    sigs = [_sig(rs=float(i), perf=float(i)) for i in range(10)]   # membres = 8, 9
    detect_profiles(sigs)
    survivors = [(f"T{i}", s) for i, s in enumerate(sigs)]
    members = rank_members(survivors)
    assert [tk for tk, _ in members] == ["T9", "T8"]   # membres seuls, force décroissante


# ---------------------------------------------------------------------------
# Cohérence détecteur ↔ protocole v2 §3 (lit LES DEUX sources)
# ---------------------------------------------------------------------------

def _protocol_text() -> str:
    proto = Path(__file__).resolve().parents[2] / "docs" / "backtest_protocol_v2.md"
    return proto.read_text(encoding="utf-8")


def _pctile(text: str, metric: str) -> int:
    m = re.search(rf"{re.escape(metric)}\s*[≥≤]\s*(\d+)(?:st|nd|rd|th)\s+percentile", text)
    assert m is not None, f"seuil de percentile introuvable pour {metric} dans le protocole"
    return int(m.group(1))


def test_detector_thresholds_match_protocol():
    text = _protocol_text()
    P = FILTERS["profiles"]
    assert _pctile(text, "rs63") == round(P["fusee"]["rs63_pctile_min"] * 100)
    assert _pctile(text, "perf_1m") == round(P["fusee"]["perf_1m_pctile_min"] * 100)
    assert _pctile(text, "pct_52w") == round(P["phenix"]["pct_52w_pctile_max"] * 100)
    assert _pctile(text, "atr_ratio") == round(P["phenix"]["atr_ratio_pctile_max"] * 100)
    m = re.search(r"close\s*≥\s*SMA(\d+)", text)
    assert m is not None and int(m.group(1)) == P["phenix_sma_window"]


def test_profile_thresholds_ignore_none():
    # une valeur None dans la population ne casse pas le calcul de seuil
    sigs = [_sig(rs=float(i), perf=float(i)) for i in range(5)] + [_sig(rs=None, perf=None)]
    thr = profile_thresholds(sigs)
    assert thr["rs63_min"] is not None


# ---------------------------------------------------------------------------
# Pool tradability vs legacy — Passe A (régression du funnel v1)
# ---------------------------------------------------------------------------

def _ohlcv(closes, vol=500_000):
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"High": [c + 0.2 for c in closes], "Low": [c - 0.2 for c in closes],
                         "Close": closes, "Volume": [vol] * n}, index=idx)


def test_tradability_keeps_downtrend_and_exposes_sma20():
    # défaut tradability : un couteau qui tombe (pente MA50 < 0) reste TRADABLE (gardé),
    # là où le funnel v1 le rejetait. Le champ sma20 (garde Phénix) est exposé.
    df = _ohlcv([35.0 - i * 0.1 for i in range(200)])
    sig, reason = analyze_prices("DOWN", df, None)
    assert reason == "ok"
    assert sig["sma20"] is not None


def test_legacy_pool_reproduces_v1_hard_filters():
    # pool "legacy" : le même couteau qui tombe est rejeté (pente MA50 négative) — funnel v1.
    df = _ohlcv([35.0 - i * 0.1 for i in range(200)])
    old = FILTERS["pool_mode"]
    try:
        FILTERS["pool_mode"] = "legacy"
        sig, reason = analyze_prices("DOWN", df, None)
    finally:
        FILTERS["pool_mode"] = old
    assert sig is None and reason == "trend:down"


def test_tradability_price_ceiling_lifted():
    # prix > price_max (25) : rejeté en legacy, gardé en tradability (plafond levé, protocole §2).
    df = _ohlcv([30.0 + i * 0.01 for i in range(200)])   # ~30-32$, liquide
    sig_trad, reason_trad = analyze_prices("HIGH", df, None)
    assert reason_trad == "ok"
    old = FILTERS["pool_mode"]
    try:
        FILTERS["pool_mode"] = "legacy"
        sig_leg, reason_leg = analyze_prices("HIGH", df, None)
    finally:
        FILTERS["pool_mode"] = old
    assert sig_leg is None and reason_leg.startswith("price")
