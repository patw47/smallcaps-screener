"""
Tests offline de l'export des résultats terminés (Epic 11 S2).

Le service externe est SIMULÉ : `FakeTable` rejoue le contrat de la vraie table —
interrogation paginée, écriture d'une page, et surtout le ALLER-RETOUR de la clé de
déduplication (écrite en `rich_text`, relue en `plain_text`). Un stub qui se contenterait
de compter les appels ne verrait pas une clé écrite dans un format que la relecture ne
retrouve pas — c'est exactement le doublon qu'on cherche à empêcher.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_notion_export.py -v
"""
import json

import pytest
import requests

import notion_export as nx


# ---------------------------------------------------------------------------
# Service externe simulé
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code = status
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeTable:
    """Table externe en mémoire : garde les pages écrites et les ressert à la lecture."""

    def __init__(self, query_status: int = 200, write_status: int = 200):
        self.pages: list[dict] = []
        self.query_status = query_status
        self.write_status = write_status
        self.writes = 0

    def post(self, url: str, headers=None, json=None, timeout=None) -> _Resp:
        if url.endswith("/query"):
            if self.query_status != 200:
                return _Resp(self.query_status)
            return _Resp(200, {"results": self.pages, "has_more": False, "next_cursor": None})
        if self.write_status >= 300:
            return _Resp(self.write_status)
        self.writes += 1
        self.pages.append({"properties": _as_read(json["properties"])})
        return _Resp(200, {"id": f"page-{self.writes}"})

    # -- lectures de confort pour les assertions ---------------------------
    def keys(self) -> list[str]:
        return [p["properties"]["Cle"]["rich_text"][0]["plain_text"] for p in self.pages]

    def written(self, i: int = 0) -> dict:
        return self.pages[i]["properties"]


def _as_read(props: dict) -> dict:
    """Ce que la table renvoie à la lecture : le texte écrit revient en `plain_text`."""
    out = json.loads(json.dumps(props))
    for value in out.values():
        for chunk in value.get("rich_text") or []:
            chunk["plain_text"] = chunk["text"]["content"]
    return out


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(nx.requests, "post", t.post)
    monkeypatch.setenv("NOTION_API_KEY", "cle-de-test")
    monkeypatch.setenv("NOTION_RESULTS_DB_ID", "table-de-test")
    return t


# ---------------------------------------------------------------------------
# Jeux de données
# ---------------------------------------------------------------------------

def _row(ticker="AAA", phase="closed", window=7, entry_date="2026-01-05", **kw) -> dict:
    row = {"ticker": ticker, "window": window, "entry_date": entry_date,
           "entry_price": 2.0, "phase": phase, "ret": 0.1,
           "status": {"code": "closed" if phase == "closed" else "above"}}
    if phase == "closed":
        row["ret_63"] = 0.25
    row.update(kw)
    return row


def _result(rows: list[dict]) -> dict:
    return {"v4_tracking": [], "v5": {"tracking": rows}}


def _history(tmp_path, picks: list[dict], stamp="20260105_120000") -> object:
    hd = tmp_path / "history"
    hd.mkdir(exist_ok=True)
    (hd / f"{stamp}.json").write_text(json.dumps({"scanned_at": "2026-01-05T12:00:00+00:00",
                                                  "picks": picks}))
    return hd


# ---------------------------------------------------------------------------
# Sélection : seules les fenêtres échues sont écrites
# ---------------------------------------------------------------------------

def test_only_closed_windows_are_written(table, tmp_path):
    """Une ligne échue et une ligne en cours : exactement une écriture, l'échue."""
    result = _result([_row("ECHUE", phase="closed"),
                      _row("ENCOURS", phase="open", window=14)])

    assert nx.export_closed_rows(result, _history(tmp_path, [])) == 1

    assert table.writes == 1
    assert table.written()["Ticker"]["title"][0]["text"]["content"] == "ECHUE"
    assert table.keys() == ["ECHUE|2026-01-05|Purge silencieuse|7"]


def test_both_families_are_exported(table, tmp_path):
    """Les deux blocs de suivi sont figés, et une fenêtre absente ne collisionne pas."""
    result = {"v4_tracking": [_row("AAA", window=None)],
              "v5": {"tracking": [_row("AAA", window=7)]}}

    assert nx.export_closed_rows(result, _history(tmp_path, [])) == 2
    assert sorted(table.keys()) == ["AAA|2026-01-05|Purge de marche|-",
                                    "AAA|2026-01-05|Purge silencieuse|7"]


def test_no_closed_row_never_calls_the_service(table, tmp_path):
    """Aucune fenêtre échue : pas même une interrogation de la table."""
    calls = []
    original = table.post
    table.post = lambda *a, **k: (calls.append(a), original(*a, **k))[1]

    assert nx.export_closed_rows(_result([_row(phase="open")]), _history(tmp_path, [])) == 0
    assert calls == []


# ---------------------------------------------------------------------------
# Idempotence — la déduplication interroge la table, jamais un état local
# ---------------------------------------------------------------------------

def test_second_pass_writes_nothing(table, tmp_path):
    """Artefact : les clés émises. Un second passage sans nouvelle échéance n'écrit rien."""
    result = _result([_row("AAA"), _row("BBB", window=14)])
    hd = _history(tmp_path, [])

    assert nx.export_closed_rows(result, hd) == 2
    emitted = sorted(table.keys())

    assert nx.export_closed_rows(result, hd) == 0        # tolérance : zéro écriture superflue
    assert table.writes == 2
    assert sorted(table.keys()) == emitted               # la table n'a pas bougé


def test_new_deadline_still_gets_written(table, tmp_path):
    """La déduplication ne doit pas non plus tout bloquer : une clé neuve passe."""
    hd = _history(tmp_path, [])
    assert nx.export_closed_rows(_result([_row("AAA")]), hd) == 1
    assert nx.export_closed_rows(_result([_row("AAA"), _row("CCC")]), hd) == 1
    assert sorted(table.keys()) == ["AAA|2026-01-05|Purge silencieuse|7",
                                    "CCC|2026-01-05|Purge silencieuse|7"]


# ---------------------------------------------------------------------------
# Marqueurs d'entrée — verrou anti-réécriture du passé
# ---------------------------------------------------------------------------

def test_flags_come_from_the_entry_snapshot(table, tmp_path):
    """Effet injecté : un marqueur levé à l'entrée figure dans la ligne, avec le profil."""
    hd = _history(tmp_path, [{"ticker": "AAA", "profile": "phenix", "sector": "Biotechnology",
                              "dilution_flag": True, "going_concern_flag": False}])

    assert nx.export_closed_rows(_result([_row("AAA")]), hd) == 1

    props = table.written()
    assert [m["name"] for m in props["Marqueurs a l entree"]["multi_select"]] == ["Dilution a venir"]
    assert props["Profil a l entree"]["select"]["name"] == "Phenix"
    assert props["Secteur"]["rich_text"][0]["text"]["content"] == "Biotechnology"


def test_current_scan_flags_are_never_written(table, tmp_path):
    """Bruit rejeté : un marqueur ABSENT à l'entrée mais levé au scan courant n'y entre pas."""
    hd = _history(tmp_path, [{"ticker": "AAA", "profile": "fusee", "going_concern_flag": False}])
    result = _result([_row("AAA")])
    # Le scan courant voit le titre en doute sur la continuité — l'export l'ignore.
    result["stocks"] = [{"ticker": "AAA", "going_concern_flag": True, "dilution_flag": True}]

    assert nx.export_closed_rows(result, hd) == 1

    assert table.written()["Marqueurs a l entree"]["multi_select"] == []


def test_ticker_absent_from_the_entry_snapshot(table, tmp_path):
    """Les cohortes sont bâties sur le pool complet : un titre hors sélections reste exportable,
    colonnes d'entrée vides plutôt que remplies avec l'état d'aujourd'hui."""
    hd = _history(tmp_path, [{"ticker": "AUTRE", "profile": "fusee", "dilution_flag": True}])

    assert nx.export_closed_rows(_result([_row("AAA")]), hd) == 1

    props = table.written()
    assert props["Marqueurs a l entree"]["multi_select"] == []
    assert "Profil a l entree" not in props and "Secteur" not in props


def test_manual_columns_are_left_empty(table, tmp_path):
    """L'étiquetage manuel appartient à l'owner : jamais écrit, jamais mis à jour."""
    assert nx.export_closed_rows(_result([_row("AAA")]), _history(tmp_path, [])) == 1

    props = table.written()
    assert "Verdict" not in props and "Note" not in props
    assert props["Rendement"]["number"] == 0.25
    assert props["Prix sortie"]["number"] == 2.5      # dérivé du prix d'entrée, jamais relu


# ---------------------------------------------------------------------------
# Non bloquant — aucune exception ne remonte à l'appelant
# ---------------------------------------------------------------------------

def test_service_error_never_raises(table, tmp_path):
    """Écriture refusée par le service : avalée, aucune ligne comptée."""
    table.write_status = 502
    assert nx.export_closed_rows(_result([_row("AAA")]), _history(tmp_path, [])) == 0


def test_timeout_never_raises(monkeypatch, tmp_path):
    """Expiration du service : avalée."""
    monkeypatch.setenv("NOTION_API_KEY", "cle-de-test")
    monkeypatch.setenv("NOTION_RESULTS_DB_ID", "table-de-test")

    def boom(*a, **k):
        raise requests.exceptions.Timeout("délai dépassé")
    monkeypatch.setattr(nx.requests, "post", boom)

    assert nx.export_closed_rows(_result([_row("AAA")]), _history(tmp_path, [])) == 0


def test_missing_secret_disables_silently(monkeypatch, tmp_path):
    """Secret absent : export désactivé, aucun appel, aucune exception."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_RESULTS_DB_ID", raising=False)

    def never(*a, **k):
        raise AssertionError("aucun appel ne doit partir sans secret")
    monkeypatch.setattr(nx.requests, "post", never)

    assert nx.export_closed_rows(_result([_row("AAA")]), _history(tmp_path, [])) == 0


def test_unreadable_table_writes_nothing(table, tmp_path):
    """Table illisible : on s'abstient plutôt que d'écrire à l'aveugle — sans la source de
    vérité de la déduplication, écrire produirait des doublons irrattrapables."""
    table.query_status = 429
    assert nx.export_closed_rows(_result([_row("AAA")]), _history(tmp_path, [])) == 0
    assert table.writes == 0


def test_scan_completes_when_export_fails(tmp_path, monkeypatch):
    """Le traitement appelant (boucle de scan) aboutit malgré un export en échec."""
    pytest.importorskip("fastapi")
    import api

    monkeypatch.setenv("NOTION_API_KEY", "cle-de-test")
    monkeypatch.setenv("NOTION_RESULTS_DB_ID", "table-de-test")

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("service injoignable")
    monkeypatch.setattr(nx.requests, "post", boom)
    monkeypatch.setattr(api, "run_scan", lambda wl: _result([_row("AAA")]))
    monkeypatch.setattr(api, "backup_snapshots", lambda: 0)

    api._run_scan_sync()                                 # ne doit pas lever

    assert api._cached_data["v5"]["tracking"][0]["ticker"] == "AAA"


# ---------------------------------------------------------------------------
# Non-régression du contrat servi
# ---------------------------------------------------------------------------

def test_served_payload_keys_unchanged(monkeypatch):
    """Artefact : le jeu de clés de la réponse servie. L'export n'y ajoute ni n'en retire rien."""
    pytest.importorskip("fastapi")
    import asyncio

    import api

    payload = {"scanned_at": "2026-01-05T12:00:00+00:00", "universe_size": 10,
               "candidates": 1, "stocks": [], "rejection_stats": {},
               "v4_cohort": [], "v4_note": {}, "v4_mkt21": None, "v4_prelist": [],
               "v4_tracking": [_row("AAA")], "v5": {"tracking": [_row("BBB")]},
               "enriched": 1, "display": {}}
    monkeypatch.setattr(api, "_load_json_cache", lambda: payload)

    served = asyncio.run(api.get_scan())

    assert set(served) == set(payload)
