"""
Tests offline d'EDGAR Form 4 (Sprint 5) — AUCUN appel réseau : `edgar._get` est
monkeypatché pour servir des fixtures JSON/XML enregistrées.

Fixtures (backend/tests/fixtures/edgar/) :
  - company_tickers.json : TEST → CIK 111
  - submissions_CIK0000000111.json : 2 Form 4 (dans la fenêtre) + un 8-K
  - form4_0001.xml : 2 achats P (1000@10, 500@12) + 1 award A (ignoré)
  - form4_0002.xml : 1 vente S (300@11), 1 achat P (200@10), 1 achat P hors fenêtre (999@10, 2025)

Attendu (fenêtre 180j, now=2026-07-01 → cutoff 2026-01-02) :
  buys = 10000 + 6000 + 2000 = 18000 ; sells = 3300 ; net = 14700 ; n_buys=3 ; n_sells=1.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_edgar.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

from datetime import datetime, timezone
from pathlib import Path

import pytest

import edgar
from screener_backend import _fundamental_rules, FILTERS

FIX = Path(__file__).parent / "fixtures" / "edgar"
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


class _Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text


def _make_fake_get(counter):
    def fake_get(url):
        counter["n"] += 1
        if "company_tickers.json" in url:
            return _Resp((FIX / "company_tickers.json").read_text())
        if "submissions/CIK" in url:
            return _Resp((FIX / "submissions_CIK0000000111.json").read_text())
        for doc in ("form4_0002.xml", "form4_0001.xml"):
            if doc in url:
                return _Resp((FIX / doc).read_text())
        return None
    return fake_get


@pytest.fixture
def edgar_env(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar, "EDGAR_CACHE_DIR", tmp_path / "edgar_cache")
    monkeypatch.setattr(edgar, "_USER_AGENT", "SmallCaps Screener test contact@example.com")
    monkeypatch.setattr(edgar, "_cik_map", None)          # reset du cache mémoire inter-tests
    monkeypatch.setattr(edgar, "_last_request_ts", 0.0)
    monkeypatch.setitem(edgar.FILTERS, "edgar_rate_limit_s", 0.0)  # pas de sleep en test
    return tmp_path


# ---------------------------------------------------------------------------
# Agrégation des achats nets (valeur attendue connue)
# ---------------------------------------------------------------------------

def test_net_buying_aggregation(edgar_env, monkeypatch):
    monkeypatch.setattr(edgar, "_get", _make_fake_get({"n": 0}))
    r = edgar.net_insider_buying("TEST", window_days=180, now=NOW)
    assert r is not None
    assert r["buy_dollars"] == 18000.0     # 1000×10 + 500×12 + 200×10 (award A exclu)
    assert r["sell_dollars"] == 3300.0     # 300×11
    assert r["net_buying"] == 14700.0      # 18000 − 3300
    assert r["n_buys"] == 3 and r["n_sells"] == 1
    assert r["cik"] == 111
    # transactions datées → réutilisables point-in-time (Sprint 6)
    assert all("date" in t for t in r["transactions"])
    # l'achat de 2025 (hors fenêtre) est exclu
    assert all(t["date"] >= r["cutoff"] for t in r["transactions"])


def test_filing_url_strips_xsl_render_prefix(edgar_env, monkeypatch):
    # primaryDocument = "xslF345X06/wk-form4_x.xml" (rendu HTML) → l'URL doit viser le XML BRUT.
    seen = []

    def fake_get(url):
        seen.append(url)
        if "company_tickers.json" in url:
            return _Resp((FIX / "company_tickers.json").read_text())
        if "submissions/CIK" in url:
            return _Resp((FIX / "submissions_CIK0000000111.json").read_text())
        for doc in ("form4_0002.xml", "form4_0001.xml"):
            if doc in url:
                return _Resp((FIX / doc).read_text())
        return None

    monkeypatch.setattr(edgar, "_get", fake_get)
    r = edgar.net_insider_buying("TEST", window_days=180, now=NOW)
    assert r["net_buying"] == 14700.0                       # agrégation correcte via XML brut
    archive = [u for u in seen if "/Archives/" in u]
    assert archive
    assert all("xslF345X06" not in u for u in archive)      # préfixe de rendu XSL retiré
    assert any(u.endswith("wk-form4_0002.xml") for u in archive)  # nom nu (dernier segment)


def test_html_response_is_not_cached(edgar_env, monkeypatch):
    # une page HTML rendue ne doit JAMAIS empoisonner le cache permanent des filings.
    def fake_get(url):
        if "company_tickers.json" in url:
            return _Resp((FIX / "company_tickers.json").read_text())
        if "submissions/CIK" in url:
            return _Resp((FIX / "submissions_CIK0000000111.json").read_text())
        return _Resp("<!DOCTYPE html><html><body>rendered Form 4</body></html>")

    monkeypatch.setattr(edgar, "_get", fake_get)
    r = edgar.net_insider_buying("TEST", window_days=180, now=NOW)
    assert r is not None
    assert r["net_buying"] == 0.0                           # HTML → parse [] → aucune transaction
    cache_dir = edgar.EDGAR_CACHE_DIR
    poisoned = list(cache_dir.glob("form4_*.xml")) if cache_dir.exists() else []
    assert poisoned == []                                   # rien mis en cache


def test_parse_form4_open_market_only():
    txs = edgar._parse_form4((FIX / "form4_0001.xml").read_text())
    assert [t["code"] for t in txs] == ["P", "P"]   # l'award « A » (9999) est ignoré
    assert txs[0]["value"] == 10000.0               # 1000 × 10.00


# ---------------------------------------------------------------------------
# Cache : 2e scan = zéro appel EDGAR répété
# ---------------------------------------------------------------------------

def test_second_scan_uses_cache_no_network(edgar_env, monkeypatch):
    counter = {"n": 0}
    monkeypatch.setattr(edgar, "_get", _make_fake_get(counter))
    edgar.net_insider_buying("TEST", window_days=180, now=NOW)
    first = counter["n"]
    assert first > 0                                # 1er scan : appels réseau (map+subs+filings)
    edgar.net_insider_buying("TEST", window_days=180, now=NOW)
    assert counter["n"] == first                    # 2e scan : tout en cache, 0 nouvel appel


# ---------------------------------------------------------------------------
# Robustesse : EDGAR indisponible / désactivé / ticker inconnu → None neutre
# ---------------------------------------------------------------------------

def test_disabled_without_user_agent(edgar_env, monkeypatch):
    monkeypatch.setattr(edgar, "_USER_AGENT", "")

    def boom(url):
        raise AssertionError("aucun réseau ne doit être touché quand EDGAR est désactivé")

    monkeypatch.setattr(edgar, "_get", boom)
    assert edgar.net_insider_buying("TEST", now=NOW) is None


def test_unknown_ticker_returns_none(edgar_env, monkeypatch):
    monkeypatch.setattr(edgar, "_get", _make_fake_get({"n": 0}))
    assert edgar.net_insider_buying("NOPE", now=NOW) is None


def test_edgar_down_returns_none(edgar_env, monkeypatch):
    def fake(url):
        if "company_tickers.json" in url:
            return _Resp((FIX / "company_tickers.json").read_text())
        return None   # soumissions / filings indisponibles

    monkeypatch.setattr(edgar, "_get", fake)
    assert edgar.net_insider_buying("TEST", now=NOW) is None


# ---------------------------------------------------------------------------
# Le point de score insider bascule sur les achats nets, plus sur le % détention
# ---------------------------------------------------------------------------

def test_insider_score_on_net_buying_not_ownership_pct():
    # % détention élevé MAIS aucun achat net → PAS de point insider (1re règle fondamentale)
    high_pct_no_buys = {"insider_buying": True, "insider_pct": 40.0, "insider_net_buying_pos": False}
    assert _fundamental_rules(high_pct_no_buys)[0][0] is False

    # achats nets positifs → point insider accordé (indépendamment du %)
    net_buys = {"insider_net_buying_pos": True}
    assert _fundamental_rules(net_buys)[0][0] is True
    assert _fundamental_rules(net_buys)[0][1] == FILTERS["score_weights"]["insider"]
