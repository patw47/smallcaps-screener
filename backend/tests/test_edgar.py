"""
Tests offline d'EDGAR Form 4 (Sprint 5) — AUCUN appel réseau : `edgar._get` est
monkeypatché pour servir des fixtures JSON/XML enregistrées.

Fixtures (backend/tests/fixtures/edgar/) :
  - company_tickers.json : TEST → CIK 111
  - submissions_CIK0000000111.json : 2 Form 4 (dans la fenêtre) + deux 8-K portant leurs
    `items` (2026-06-20 « 1.01,9.01 » et 2025-12-01 « 8.01 »)
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
    edgar.reset_pit_memos()                                # mémos point-in-time frais par test
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


def test_net_buying_point_in_time_excludes_future_filings(edgar_env, monkeypatch):
    # as_of=2026-05-15 : le Form 4 déposé le 2026-06-10 (form4_0002) est POSTÉRIEUR → invisible.
    # Reste form4_0001 (2026-05-02) : 2 achats P (10000 + 6000), aucune vente → net 16000.
    monkeypatch.setattr(edgar, "_get", _make_fake_get({"n": 0}))
    r = edgar.net_insider_buying("TEST", window_days=180,
                                 now=datetime(2026, 5, 15, tzinfo=timezone.utc))
    assert r["net_buying"] == 16000.0     # sans la vente 3300 ni l'achat 2000 du filing du 06-10
    assert r["n_sells"] == 0


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
# Signaux de survie (Epic 3 S2) — dilution / retard / going-concern, point-in-time
# ---------------------------------------------------------------------------

def _make_survival_get(gc_text=None):
    """fake_get servant company_tickers + submissions + doc 10-Q + companyfacts (cash runway)."""
    def fake_get(url):
        if "company_tickers.json" in url:
            return _Resp((FIX / "company_tickers.json").read_text())
        if "submissions/CIK" in url:
            return _Resp((FIX / "submissions_CIK0000000111.json").read_text())
        if "companyfacts/CIK" in url:
            return _Resp((FIX / "facts_CIK0000000111.json").read_text())
        if "test-10q.htm" in url:
            return _Resp(gc_text if gc_text is not None else (FIX / "test-10q.htm").read_text())
        return None
    return fake_get


def test_survival_flags_full_window(edgar_env, monkeypatch):
    # as_of = 2026-07-01 : S-3 (03-01) + 424B5 (03-05) → dilution ; NT 10-Q (04-20) → retard ;
    # 10-Q (05-15) contient « substantial doubt » → going concern.
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)
    assert r is not None
    assert r["dilution_flag"] is True
    assert r["late_filing_flag"] is True
    assert r["going_concern_flag"] is True
    assert r["cash_runway"] is not None   # XBRL companyfacts câblé (voir test dédié)


def test_survival_point_in_time_excludes_future_filings(edgar_env, monkeypatch):
    # as_of = 2026-04-01 : S-3/424B5 déjà déposés (≤ as_of) → dilution ; MAIS NT 10-Q (04-20)
    # et 10-Q (05-15) sont POSTÉRIEURS → invisibles. Aucun look-ahead.
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    r = edgar.survival_signals("TEST", now=datetime(2026, 4, 1, tzinfo=timezone.utc), window_days=180)
    assert r["dilution_flag"] is True
    assert r["late_filing_flag"] is False      # NT 10-Q pas encore déposé à cette date
    assert r["going_concern_flag"] is False     # aucun 10-Q/10-K ≤ as_of


def test_survival_flags_carry_their_filing_dates(edgar_env, monkeypatch):
    # Epic 10 S1 : la date du fait est CONSERVÉE depuis la boucle des soumissions déjà
    # parcourue — aucune requête supplémentaire. Dilution : le dépôt le plus récent des
    # deux (424B5 du 05-03, après le S-3 du 01-03).
    fake = _make_survival_get()
    calls = {"n": 0}

    def counting_get(url):
        calls["n"] += 1
        return fake(url)

    monkeypatch.setattr(edgar, "_get", counting_get)
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)
    assert r["dilution_date"] == "2026-03-05"
    assert r["late_filing_date"] == "2026-04-20"
    assert r["going_concern_date"] == "2026-05-15"       # dernier 10-Q ≤ as_of

    avant = calls["n"]
    edgar.reset_pit_memos()
    edgar.survival_signals("TEST", now=NOW, window_days=180)
    assert calls["n"] == avant   # tout ressort du cache : les dates ne coûtent aucun appel


def test_survival_dates_absent_when_flag_is_down(edgar_env, monkeypatch):
    # Drapeau bas → aucune date inventée. Point-in-time : à cette date, ni NT 10-Q ni 10-Q.
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    r = edgar.survival_signals("TEST", now=datetime(2026, 4, 1, tzinfo=timezone.utc),
                               window_days=180)
    assert r["late_filing_flag"] is False and r["late_filing_date"] is None
    assert r["going_concern_flag"] is False and r["going_concern_date"] is None
    assert r["dilution_flag"] is True and r["dilution_date"] == "2026-03-05"


def test_survival_going_concern_absent(edgar_env, monkeypatch):
    # 10-Q présent mais SANS « substantial doubt » → going_concern False (dilution/late intacts).
    clean = "<html><body>Operations are profitable. No liquidity issues.</body></html>"
    monkeypatch.setattr(edgar, "_get", _make_survival_get(gc_text=clean))
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)
    assert r["going_concern_flag"] is False
    assert r["dilution_flag"] is True


def test_cash_runway_point_in_time(edgar_env, monkeypatch):
    # cash 1,0 M$ (fin mars, déposé 15/04) ; OCF −0,6 M$ sur 90 j → burn ~0,203 M$/mois →
    # runway ~4,9 mois. as_of=2026-07-01 → visible.
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)
    assert r["cash_runway"] is not None
    assert 4.0 < r["cash_runway"] < 6.0

    # as_of=2026-04-01 : le 10-Q (déposé 15/04) n'est pas encore public → pas d'OCF → None.
    r2 = edgar.survival_signals("TEST", now=datetime(2026, 4, 1, tzinfo=timezone.utc))
    assert r2["cash_runway"] is None


def test_cash_runway_not_burning_is_safe(edgar_env, monkeypatch):
    # OCF positif → ne brûle pas de cash → runway plafonné (sûr), jamais None.
    facts = {"facts": {"us-gaap": {
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            {"end": "2026-03-31", "val": 2000000, "filed": "2026-04-15"}]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            {"start": "2026-01-01", "end": "2026-03-31", "val": 300000, "filed": "2026-04-15"}]}},
    }}}
    import json as _json

    def fake_get(url):
        if "company_tickers.json" in url:
            return _Resp((FIX / "company_tickers.json").read_text())
        if "submissions/CIK" in url:
            return _Resp((FIX / "submissions_CIK0000000111.json").read_text())
        if "companyfacts/CIK" in url:
            return _Resp(_json.dumps(facts))
        if "test-10q.htm" in url:
            return _Resp((FIX / "test-10q.htm").read_text())
        return None

    monkeypatch.setattr(edgar, "_get", fake_get)
    r = edgar.survival_signals("TEST", now=NOW)
    assert r["cash_runway"] == edgar._RUNWAY_CAP


def test_survival_none_when_disabled_or_unknown(edgar_env, monkeypatch):
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    assert edgar.survival_signals("NOPE", now=NOW) is None      # ticker inconnu → neutre
    monkeypatch.setattr(edgar, "_USER_AGENT", "")
    assert edgar.survival_signals("TEST", now=NOW) is None      # EDGAR désactivé → neutre


# ---------------------------------------------------------------------------
# Catalyseurs 8-K typés (Epic 14 S2) — lus dans la MÊME liste de soumissions
# ---------------------------------------------------------------------------

def test_catalyseur_8k_type_et_date_dans_la_fenetre(edgar_env, monkeypatch):
    # as_of = 2026-07-01, fenêtre 180 j : le 8-K du 2026-06-20 porte « 1.01,9.01 ».
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)

    assert r["catalyst_8k_date"] == "2026-06-20"
    assert r["catalyst_8k_items"] == ["1.01", "9.01"]     # typé, pas un simple booléen
    # Les marqueurs de détresse voisins ne bougent pas : la lecture est additive.
    assert r["dilution_flag"] is True and r["late_filing_flag"] is True


def test_sans_8k_dans_la_fenetre_aucun_catalyseur(edgar_env, monkeypatch):
    # Mêmes soumissions PRIVÉES de tout 8-K : le drapeau doit être absent, pas « vide ».
    import json as _json
    sans_8k = _json.loads((FIX / "submissions_CIK0000000111.json").read_text())
    recentes = sans_8k["filings"]["recent"]
    gardes = [i for i, f in enumerate(recentes["form"]) if not f.startswith("8-K")]
    assert len(gardes) < len(recentes["form"]), "aucun 8-K retiré — le test serait vide"
    for colonne, valeurs in recentes.items():
        recentes[colonne] = [valeurs[i] for i in gardes]

    def fake_get(url):
        if "submissions/CIK" in url:
            return _Resp(_json.dumps(sans_8k))
        return _make_survival_get()(url)

    monkeypatch.setattr(edgar, "_get", fake_get)
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)

    assert r["catalyst_8k_date"] is None
    assert r["catalyst_8k_items"] is None
    assert r["dilution_flag"] is True          # le reste de la lecture est intact


def test_un_8k_hors_fenetre_ne_rend_aucun_catalyseur(edgar_env, monkeypatch):
    # as_of = 2026-06-01 : le 8-K du 2026-06-20 n'est pas encore déposé, celui du
    # 2025-12-01 est ANTÉRIEUR au début de fenêtre (2026-06-01 − 180 j = 2025-12-03).
    monkeypatch.setattr(edgar, "_get", _make_survival_get())
    quand = datetime(2026, 6, 1, tzinfo=timezone.utc)
    r = edgar.survival_signals("TEST", now=quand, window_days=180)

    assert r["cutoff"] > "2025-12-01"          # le 8-K ancien est bien hors fenêtre
    assert r["catalyst_8k_date"] is None
    assert r["catalyst_8k_items"] is None

    # Et c'est bien la FENÊTRE qui l'exclut : élargie, le même dépôt ressort, typé.
    edgar.reset_pit_memos()
    large = edgar.survival_signals("TEST", now=quand, window_days=365)
    assert large["catalyst_8k_date"] == "2025-12-01"
    assert large["catalyst_8k_items"] == ["8.01"]


def test_une_colonne_items_trop_courte_ne_perd_aucun_depot(edgar_env, monkeypatch):
    """
    Les colonnes des soumissions sont parallèles. Servie plus courte que `form`, `items`
    tronquerait le `zip` — et emporterait EN SILENCE les marqueurs de détresse déjà en
    place, pas seulement le catalyseur. Elle est donc complétée avant la boucle.
    """
    import json as _json
    tronque = _json.loads((FIX / "submissions_CIK0000000111.json").read_text())
    tronque["filings"]["recent"]["items"] = ["1.01,9.01"]     # 1 valeur pour 8 dépôts

    def fake_get(url):
        if "submissions/CIK" in url:
            return _Resp(_json.dumps(tronque))
        return _make_survival_get()(url)

    monkeypatch.setattr(edgar, "_get", fake_get)
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)

    # Les dépôts au-delà de la première ligne restent vus, avec leurs dates.
    assert r["dilution_flag"] is True and r["dilution_date"] == "2026-03-05"
    assert r["late_filing_flag"] is True and r["late_filing_date"] == "2026-04-20"
    assert r["going_concern_flag"] is True
    assert r["catalyst_8k_items"] == ["1.01", "9.01"]


# URLs attendues d'un enrichissement complet, ÉNONCÉES ICI et pas relevées sur le module :
# mapping des tickers, liste de soumissions, document du dernier rapport périodique
# (going-concern) et faits XBRL (trésorerie). C'est le jeu du code SANS détection 8-K —
# lire les `items` ne doit rien y ajouter, en particulier aucun document de 8-K.
URLS_ATTENDUES = {
    "https://www.sec.gov/files/company_tickers.json",
    "https://data.sec.gov/submissions/CIK0000000111.json",
    "https://www.sec.gov/Archives/edgar/data/111/000000011126000006/test-10q.htm",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000111.json",
}


def test_la_detection_8k_n_ajoute_aucune_requete(edgar_env, monkeypatch):
    journal = []
    fake = _make_survival_get()

    def get_journalise(url):
        journal.append(url)
        return fake(url)

    monkeypatch.setattr(edgar, "_get", get_journalise)
    r = edgar.survival_signals("TEST", now=NOW, window_days=180)

    # La détection est ACTIVE — sans quoi « zéro appel ajouté » serait vrai par vacuité.
    assert r["catalyst_8k_items"] == ["1.01", "9.01"]
    assert set(journal) == URLS_ATTENDUES
    # Aucun document de 8-K n'est téléchargé : seuls les `items` sont lus.
    assert not [u for u in journal if "eightk" in u]


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
