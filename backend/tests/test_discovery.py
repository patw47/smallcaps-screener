"""
Tests offline de la découverte d'univers (Sprint 1 — univers complet et stable).

Déterministes, sans réseau : on monkeypatch `screener_backend.requests.get` pour
simuler l'API NASDAQ screener sur les 3 places (nasdaq / nyse / amex) et on vérifie
la couverture multi-place, la déduplication, la stabilité inter-scan et la soupape
`max_tickers`.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_discovery.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")  # évite makedirs("/app/data")

import screener_backend
from screener_backend import discover_tickers, FILTERS


class _FakeResp:
    """Réponse HTTP minimale : seule .json() est utilisée par discover_tickers."""
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _rows(*symbols):
    return {"data": {"table": {"rows": [{"symbol": s} for s in symbols]}}}


def _install_fake_nasdaq(monkeypatch, mapping):
    """
    mapping : exchange -> liste de symboles (mêmes symboles pour Small et Micro).
    Retourne la liste des URLs appelées (pour asserter la couverture des places).
    """
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        for exch, syms in mapping.items():
            if f"exchange={exch}" in url:
                return _FakeResp(_rows(*syms))
        return _FakeResp(_rows())

    monkeypatch.setattr(screener_backend.requests, "get", fake_get)
    return calls


# ---------------------------------------------------------------------------
# Couverture multi-place (NASDAQ + NYSE + AMEX)
# ---------------------------------------------------------------------------

def test_discovery_covers_three_exchanges(monkeypatch):
    calls = _install_fake_nasdaq(monkeypatch, {
        "nasdaq": ["AAA", "BBB"],
        "nyse":   ["CCC"],
        "amex":   ["DDD"],
    })
    monkeypatch.setitem(FILTERS, "max_tickers", None)

    result = discover_tickers()

    assert set(result) == {"AAA", "BBB", "CCC", "DDD"}
    # chaque place est interrogée (sur Small ET Micro)
    assert any("exchange=nasdaq" in u for u in calls)
    assert any("exchange=nyse" in u for u in calls)
    assert any("exchange=amex" in u for u in calls)
    # une requête par (place × catégorie de cap)
    assert len(calls) == len(FILTERS["discovery_exchanges"]) * len(FILTERS["discovery_marketcaps"])


def test_discovery_dedupes_across_exchanges_and_caps(monkeypatch):
    # "DUP" apparaît sur les 3 places et pour Small+Micro → doit rester unique.
    _install_fake_nasdaq(monkeypatch, {
        "nasdaq": ["DUP", "AAA"],
        "nyse":   ["DUP", "BBB"],
        "amex":   ["DUP"],
    })
    monkeypatch.setitem(FILTERS, "max_tickers", None)

    result = discover_tickers()

    assert result.count("DUP") == 1
    assert set(result) == {"DUP", "AAA", "BBB"}


def test_discovery_filters_malformed_symbols(monkeypatch):
    _install_fake_nasdaq(monkeypatch, {
        "nasdaq": ["GOOD", "BRK.B", "AA/B", "", "  "],
        "nyse":   [],
        "amex":   [],
    })
    monkeypatch.setitem(FILTERS, "max_tickers", None)

    result = discover_tickers()

    assert result == ["GOOD"]  # les symboles avec "." "/" ou vides sont écartés


# ---------------------------------------------------------------------------
# Stabilité inter-scan : même univers, aucun échantillonnage aléatoire
# ---------------------------------------------------------------------------

def test_discovery_stable_across_scans(monkeypatch):
    _install_fake_nasdaq(monkeypatch, {
        "nasdaq": [f"T{i}" for i in range(30)],
        "nyse":   [f"N{i}" for i in range(10)],
        "amex":   [f"A{i}" for i in range(5)],
    })
    monkeypatch.setitem(FILTERS, "max_tickers", None)
    monkeypatch.setitem(FILTERS, "shuffle_seed", None)  # mélange aléatoire actif

    a = discover_tickers()
    b = discover_tickers()

    # Même univers d'un scan à l'autre malgré le shuffle (l'ordre seul peut différer).
    assert set(a) == set(b)
    assert len(a) == len(b) == 45


# ---------------------------------------------------------------------------
# max_tickers : soupape optionnelle, plus une troncature par défaut
# ---------------------------------------------------------------------------

def test_discovery_full_universe_when_cap_none(monkeypatch):
    _install_fake_nasdaq(monkeypatch, {
        "nasdaq": [f"T{i}" for i in range(1000)],
        "nyse":   [],
        "amex":   [],
    })
    monkeypatch.setitem(FILTERS, "max_tickers", None)

    result = discover_tickers()

    assert len(result) == 1000  # aucune troncature : univers complet


def test_discovery_cap_is_optional_safety_valve(monkeypatch):
    _install_fake_nasdaq(monkeypatch, {
        "nasdaq": [f"T{i}" for i in range(50)],
        "nyse":   [],
        "amex":   [],
    })
    monkeypatch.setitem(FILTERS, "max_tickers", 20)
    monkeypatch.setitem(FILTERS, "shuffle_seed", 42)

    result = discover_tickers()

    assert len(result) == 20  # cap appliqué comme garde-fou explicite


# ---------------------------------------------------------------------------
# Robustesse : l'échec d'une place n'invalide pas les autres
# ---------------------------------------------------------------------------

def test_discovery_survives_partial_exchange_failure(monkeypatch):
    def fake_get(url, **kwargs):
        if "exchange=nyse" in url:
            raise RuntimeError("boom NYSE")
        if "exchange=nasdaq" in url:
            return _FakeResp(_rows("AAA"))
        return _FakeResp(_rows())

    monkeypatch.setattr(screener_backend.requests, "get", fake_get)
    monkeypatch.setitem(FILTERS, "max_tickers", None)

    result = discover_tickers()

    assert "AAA" in result  # l'échec NYSE n'empêche pas la récolte NASDAQ


def test_discovery_no_finviz_source(monkeypatch):
    calls = _install_fake_nasdaq(monkeypatch, {"nasdaq": ["AAA"], "nyse": [], "amex": []})
    monkeypatch.setitem(FILTERS, "max_tickers", None)

    discover_tickers()

    assert not any("finviz" in u.lower() for u in calls)  # source Finviz retirée
