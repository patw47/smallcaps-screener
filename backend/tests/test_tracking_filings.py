"""
Dépôts officiels au dossier de risque actuel des lignes de suivi (Epic 12 S2).

Le S1 a posé `risk_markers_now` avec les seuls drapeaux prix ; ce sprint y fusionne les
trois faits des dépôts (doute sur la continuité d'exploitation, retard de dépôt, émission
d'actions), balayés AU PLUS une fois par jour calendaire et par titre, mémo daté persistant
dans le répertoire de données. EDGAR muet ou en erreur ⇒ suivi complet servi quand même.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_tracking_filings.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

import edgar
import lifecycle
import screener_backend as sb
import v4
import v5

FLOOR = sb.FILTERS["sub_dollar_price"]          # plancher de cotation
MIN_DAYS = sb.FILTERS["sub_dollar_min_days"]    # longueur de série qui fait mordre la règle
ENTRY_DAY = "2025-06-02"
DAY = "2026-08-06"                              # jour calendaire simulé du balayage

# Clés antérieures d'une ligne de suivi (état livré au S1, hors `ret_5`/`ret_63` qui
# dépendent de la phase) : le contrat servi ne doit que croître.
V4_PRIOR_KEYS = {"ticker", "entry_date", "entry_price", "resid", "beta", "risk_markers",
                 "risk_markers_now", "days_held", "days_left", "ret", "checkpoint",
                 "phase", "status"}
V5_PRIOR_KEYS = (V4_PRIOR_KEYS - {"resid", "beta"}) | {"window", "chg"}


def _v4_snap(tmp_path, tickers=("AAA",), markers=None):
    entry = {"price": 10.0, "resid": -0.12, "beta": 1.1}
    if markers is not None:
        entry["risk_markers"] = markers
    (tmp_path / "20250602_200000.json").write_text(json.dumps(
        {"scanned_at": f"{ENTRY_DAY}T20:00:00+00:00",
         "v4_cohort": [{"ticker": tk, **entry} for tk in tickers]}))


def _v5_snap(tmp_path, tickers=("AAA",), markers=None):
    entry = {"price": 10.0, "chg": -0.20}
    if markers is not None:
        entry["risk_markers"] = markers
    (tmp_path / "20250602_200000.json").write_text(json.dumps(
        {"scanned_at": f"{ENTRY_DAY}T20:00:00+00:00",
         "v5": {"windows": {"7": {"cohort": [{"ticker": tk, **entry} for tk in tickers]}}}}))


@pytest.fixture(params=[(_v4_snap, v4.build_tracking, V4_PRIOR_KEYS),
                        (_v5_snap, v5.build_tracking, V5_PRIOR_KEYS)],
                ids=["market", "quiet"])
def family(request):
    """(écriture du snapshot d'entrée, construction du suivi, clés antérieures)."""
    return request.param


@pytest.fixture(autouse=True)
def frozen_day(monkeypatch):
    """Horloge du balayage figée : la cadence se juge sur un jour calendaire choisi."""
    monkeypatch.setattr(lifecycle, "_today", lambda: DAY)


def _df(closes, start="2025-06-03"):
    return pd.DataFrame({"Close": pd.Series(
        closes, index=pd.bdate_range(start, periods=len(closes)))})


def _prices(*tickers, closes=None):
    return {tk: _df(closes or [FLOOR + 4.0] * 10) for tk in tickers}


def _codes(row):
    return [m["code"] for m in row["risk_markers_now"]]


def _by_ticker(rows):
    return {r["ticker"]: r for r in rows}


def _signals(ticker, **flags):
    """Retour de `survival_signals` : les trois drapeaux bas sauf ceux demandés."""
    out = {"ticker": ticker, "cik": 1,
           "dilution_flag": False, "late_filing_flag": False, "going_concern_flag": False,
           "dilution_date": None, "late_filing_date": None, "going_concern_date": None}
    out.update(flags)
    return out


@pytest.fixture
def edgar_log(monkeypatch):
    """Doublure des signaux de survie + journal des tickers interrogés."""
    calls = []

    def spy(ticker, *a, **k):
        calls.append(ticker)
        return _signals(ticker, going_concern_flag=True, going_concern_date="2026-07-15")

    monkeypatch.setattr(edgar, "survival_signals", spy)
    return calls


# ---------------------------------------------------------------------------
# Cadence — au plus un balayage par jour calendaire et par titre
# ---------------------------------------------------------------------------

def test_second_build_same_day_asks_edgar_nothing(tmp_path, family, edgar_log):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path, ("AAA", "BBB"))

    first = build_tracking(_prices("AAA", "BBB"), tmp_path)
    assert sorted(edgar_log) == ["AAA", "BBB"]          # le premier scan du jour paie

    second = build_tracking(_prices("AAA", "BBB"), tmp_path)
    assert sorted(edgar_log) == ["AAA", "BBB"]          # tolérance zéro : aucun appel de plus
    assert [_codes(r) for r in first] == [_codes(r) for r in second]  # même dossier servi


def test_next_day_triggers_the_sweep_again(tmp_path, family, edgar_log, monkeypatch):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)

    build_tracking(_prices("AAA"), tmp_path)
    build_tracking(_prices("AAA"), tmp_path)
    assert edgar_log == ["AAA"]

    monkeypatch.setattr(lifecycle, "_today", lambda: "2026-08-07")   # lendemain
    row = build_tracking(_prices("AAA"), tmp_path)[0]
    assert edgar_log == ["AAA", "AAA"]                  # le mémo d'hier ne vaut plus
    assert _codes(row) == ["going_concern"]


def test_the_two_families_share_one_sweep(tmp_path, edgar_log):
    """Un même titre suivi des deux côtés n'est interrogé qu'une fois dans le scan."""
    _v4_snap(tmp_path)
    v4.build_tracking(_prices("AAA"), tmp_path)
    assert edgar_log == ["AAA"]

    _v5_snap(tmp_path)
    row = v5.build_tracking(_prices("AAA"), tmp_path)[0]
    assert edgar_log == ["AAA"]                         # la seconde famille ne repaie rien
    assert _codes(row) == ["going_concern"]             # et sert le même dossier


def test_a_new_ticker_is_swept_even_after_a_first_sweep(tmp_path, family, edgar_log):
    """Cadence par TITRE : une entrée apparue après le balayage du jour est balayée."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    build_tracking(_prices("AAA"), tmp_path)

    write_snap(tmp_path, ("AAA", "BBB"))
    build_tracking(_prices("AAA", "BBB"), tmp_path)
    assert edgar_log == ["AAA", "BBB"]


# ---------------------------------------------------------------------------
# Persistance du mémo — il doit survivre au redémarrage du conteneur
# ---------------------------------------------------------------------------

def test_memo_file_is_written_in_the_data_directory(tmp_path, family, edgar_log):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    build_tracking(_prices("AAA"), tmp_path)

    memo = lifecycle._memo_path()
    assert memo.exists() and memo.parent == Path(sb.DATA_DIR)
    saved = json.loads(memo.read_text())
    assert saved["day"] == DAY
    assert saved["tickers"]["AAA"]["going_concern_flag"] is True


def test_reimporting_the_module_still_reads_the_memo(tmp_path, family, edgar_log,
                                                     monkeypatch):
    """Redémarrage simulé : le module de suivi est rechargé, tout mémo mémoire est
    perdu — seul le fichier daté peut éviter un second balayage."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    build_tracking(_prices("AAA"), tmp_path)
    assert edgar_log == ["AAA"]

    importlib.reload(lifecycle)
    monkeypatch.setattr(lifecycle, "_today", lambda: DAY)   # le reload a repris l'horloge réelle
    row = build_tracking(_prices("AAA"), tmp_path)[0]

    assert edgar_log == ["AAA"]                             # tolérance zéro au second passage
    assert _codes(row) == ["going_concern"]                 # servi depuis le mémo relu


def test_an_unreadable_memo_just_sweeps_again(tmp_path, family, edgar_log):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    build_tracking(_prices("AAA"), tmp_path)
    lifecycle._memo_path().write_text("{ pas du json")

    row = build_tracking(_prices("AAA"), tmp_path)[0]
    assert edgar_log == ["AAA", "AAA"]                      # re-balayage, jamais une exception
    assert _codes(row) == ["going_concern"]


# ---------------------------------------------------------------------------
# Fusion — un seul dossier, ordonné par gravité décroissante
# ---------------------------------------------------------------------------

def test_filing_and_price_markers_merge_by_severity(tmp_path, family, edgar_log):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    n = MIN_DAYS + 10
    row = build_tracking({"AAA": _df([FLOOR - 0.5] * n)}, tmp_path)[0]

    assert _codes(row) == ["going_concern", "sub_dollar"]   # haut avant faible
    gc, sub = row["risk_markers_now"]
    assert gc["level"] == "high" and gc["date"] == "2026-07-15"
    assert sub["level"] == "low" and sub["days"] == n        # variables des deux couches


def test_all_three_filing_markers_travel_with_their_dates(tmp_path, family, monkeypatch):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    monkeypatch.setattr(edgar, "survival_signals", lambda tk, *a, **k: _signals(
        tk, going_concern_flag=True, going_concern_date="2026-07-15",
        dilution_flag=True, dilution_date="2026-07-20",
        late_filing_flag=True, late_filing_date="2026-07-25"))

    row = build_tracking(_prices("AAA"), tmp_path)[0]
    assert _codes(row) == ["going_concern", "dilution", "late_filing"]
    assert [m["date"] for m in row["risk_markers_now"]] == ["2026-07-15", "2026-07-20",
                                                            "2026-07-25"]


def test_quiet_filings_add_nothing(tmp_path, family, monkeypatch):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    monkeypatch.setattr(edgar, "survival_signals", lambda tk, *a, **k: _signals(tk))

    row = build_tracking(_prices("AAA"), tmp_path)[0]
    assert row["risk_markers_now"] == []


def test_a_line_without_prices_still_carries_its_filings(tmp_path, family, edgar_log):
    """Titre radié : plus aucune cotation, mais le dépôt reste la dernière information
    disponible — la ligne est servie avec son fait, pas muette."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path, ("AAA", "GONE"))
    rows = _by_ticker(build_tracking(_prices("AAA"), tmp_path))

    assert set(rows) == {"AAA", "GONE"}
    assert rows["GONE"]["phase"] == "no_data"               # phase inchangée
    assert _codes(rows["GONE"]) == ["going_concern"]


# ---------------------------------------------------------------------------
# Dilution — présente au dossier actuel, JAMAIS au dossier d'entrée
# ---------------------------------------------------------------------------

def test_dilution_reaches_the_current_file_only(tmp_path, family, monkeypatch):
    """Les deux familles exigent l'absence de dilution pour entrer : le dossier d'entrée
    n'en porte donc jamais. Un dépôt d'émission POSTÉRIEUR est précisément ce que le
    dossier actuel doit capter."""
    write_snap, build_tracking, _ = family
    entry_markers = [{"code": "sub_dollar", "level": "low", "days": MIN_DAYS}]
    write_snap(tmp_path, markers=entry_markers)
    monkeypatch.setattr(edgar, "survival_signals", lambda tk, *a, **k: _signals(
        tk, dilution_flag=True, dilution_date="2026-07-20"))

    row = build_tracking(_prices("AAA"), tmp_path)[0]

    assert "dilution" in _codes(row)                        # au dossier actuel…
    assert row["risk_markers"] == entry_markers             # …et pas à celui d'entrée
    assert "dilution" not in [m["code"] for m in row["risk_markers"]]


# ---------------------------------------------------------------------------
# Résilience — EDGAR muet ou en erreur ne fait jamais tomber le suivi
# ---------------------------------------------------------------------------

def test_a_raising_edgar_keeps_every_line_and_its_price_flags(tmp_path, family,
                                                              monkeypatch):
    def boom(ticker, *a, **k):
        raise RuntimeError("EDGAR indisponible")

    monkeypatch.setattr(edgar, "survival_signals", boom)
    write_snap, build_tracking, _ = family
    write_snap(tmp_path, ("AAA", "BBB"))
    n = MIN_DAYS + 10
    rows = _by_ticker(build_tracking({"AAA": _df([FLOOR - 0.5] * n),
                                      "BBB": _df([FLOOR + 4.0] * 10)}, tmp_path))

    assert set(rows) == {"AAA", "BBB"}                      # toutes les lignes servies
    assert _codes(rows["AAA"]) == ["sub_dollar"]            # drapeaux prix intacts
    assert rows["AAA"]["risk_markers_now"][0]["days"] == n
    assert rows["BBB"]["risk_markers_now"] == []            # aucun marqueur de dépôt


def test_a_silent_edgar_carries_only_price_flags(tmp_path, family, monkeypatch):
    """EDGAR désactivé (user-agent absent) ou ticker inconnu : `None`, pas une erreur."""
    monkeypatch.setattr(edgar, "survival_signals", lambda tk, *a, **k: None)
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    row = build_tracking({"AAA": _df([FLOOR - 0.5] * (MIN_DAYS + 5))}, tmp_path)[0]
    assert _codes(row) == ["sub_dollar"]


def test_a_silent_edgar_is_not_asked_twice_the_same_day(tmp_path, family, monkeypatch):
    """L'absence de réponse est un résultat : la mémoriser borne aussi la cadence les
    jours où EDGAR ne répond pas — sinon ~250 appels perdus à chaque scan."""
    calls = []

    def silent(ticker, *a, **k):
        calls.append(ticker)
        return None

    monkeypatch.setattr(edgar, "survival_signals", silent)
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    build_tracking(_prices("AAA"), tmp_path)
    build_tracking(_prices("AAA"), tmp_path)
    assert calls == ["AAA"]


def test_the_sweep_never_writes_into_the_payload(tmp_path, family, edgar_log, capsys):
    """Journalisation sobre : la console, jamais la ligne servie."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    row = build_tracking(_prices("AAA"), tmp_path)[0]

    assert "dépôts officiels" in capsys.readouterr().out
    assert not any(isinstance(v, str) and "dépôts" in v for v in row.values())
    assert set(row["risk_markers_now"][0]) <= {"code", "level", "date", "days"}


# ---------------------------------------------------------------------------
# Contrat de suivi — le jeu de clés ne fait que croître
# ---------------------------------------------------------------------------

def test_tracking_contract_only_grows(tmp_path, family, edgar_log):
    write_snap, build_tracking, prior_keys = family
    entry_markers = [{"code": "reverse_split", "level": "high", "date": "2025-06-01"}]
    write_snap(tmp_path, markers=entry_markers)
    row = build_tracking(_prices("AAA"), tmp_path)[0]

    assert prior_keys <= set(row)                   # aucune clé retirée ni renommée
    assert row["risk_markers"] == entry_markers     # l'entrée garde nom ET valeur
    assert _codes(row) == ["going_concern"]         # l'actuel diffère de l'entrée
