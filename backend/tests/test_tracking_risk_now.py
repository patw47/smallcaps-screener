"""
Risque ACTUEL des lignes de suivi (Epic 12 S1) — champ `risk_markers_now`.

Le dossier d'entrée (`risk_markers`) est figé au jour de l'entrée ; celui-ci est
recalculé à chaque construction du suivi depuis la série de prix DÉJÀ en main
(scan du jour + complément Epic 9 S1), donc sans un seul appel réseau de plus.
Les deux familles passent par `lifecycle.track_row` : chaque test tourne sur les
deux blocs de suivi.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_tracking_risk_now.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import json

import pandas as pd
import pytest

import screener_backend as sb
import v4
import v5

FLOOR = sb.FILTERS["sub_dollar_price"]          # plancher de cotation
MIN_DAYS = sb.FILTERS["sub_dollar_min_days"]    # longueur de série qui fait mordre la règle
ENTRY_DAY = "2025-06-02"

# Jeu de clés d'une ligne de suivi AVANT ce sprint (état de `main`, hors `ret_5`/`ret_63`
# qui dépendent de la phase) : le contrat servi ne doit que croître.
V4_PRIOR_KEYS = {"ticker", "entry_date", "entry_price", "resid", "beta", "risk_markers",
                 "days_held", "days_left", "ret", "checkpoint", "phase", "status"}
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


def _df(closes, splits=None, start="2025-06-03"):
    """Série postérieure à l'entrée, avec la colonne d'opérations sur titre au besoin."""
    idx = pd.bdate_range(start, periods=len(closes))
    data = {"Close": pd.Series(closes, index=idx)}
    if splits is not None:
        data["Stock Splits"] = pd.Series(splits, index=idx)
    return pd.DataFrame(data)


def _by_ticker(rows):
    return {r["ticker"]: r for r in rows}


# ---------------------------------------------------------------------------
# Cours sous le plancher de cotation — la LONGUEUR de série voyage, pas un booléen
# ---------------------------------------------------------------------------

def test_sub_dollar_run_carries_its_length(tmp_path, family):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    n = MIN_DAYS + 10
    row = build_tracking({"AAA": _df([FLOOR - 0.5] * n)}, tmp_path)[0]

    (m,) = [x for x in row["risk_markers_now"] if x["code"] == "sub_dollar"]
    assert m["days"] == n           # la gravité que porte la série, pas un simple drapeau
    assert m["level"] == "low"


def test_price_above_the_floor_carries_no_marker(tmp_path, family):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    row = build_tracking({"AAA": _df([FLOOR + 4.0] * (MIN_DAYS + 10))}, tmp_path)[0]
    assert row["risk_markers_now"] == []


def test_short_run_under_the_floor_stays_silent(tmp_path, family):
    """Série trop courte : la règle de cotation ne mord pas — un plongeon d'un jour
    ne vaut pas des mois de végétation."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    closes = [FLOOR + 4.0] * 10 + [FLOOR - 0.5] * (MIN_DAYS - 1)
    row = build_tracking({"AAA": _df(closes)}, tmp_path)[0]
    assert [m["code"] for m in row["risk_markers_now"]] == []


# ---------------------------------------------------------------------------
# Regroupement d'actions — niveau haut, daté depuis la série déjà parcourue
# ---------------------------------------------------------------------------

def test_reverse_split_is_flagged_high_and_dated(tmp_path, family):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    splits = [0.0] * 10
    splits[3] = 0.1                                  # regroupement 1 pour 10
    df = _df([FLOOR + 4.0] * 10, splits)

    row = build_tracking({"AAA": df}, tmp_path)[0]
    (m,) = row["risk_markers_now"]
    assert m["code"] == "reverse_split" and m["level"] == "high"
    assert m["date"] == str(df.index[3].date())


def test_no_reverse_split_no_marker(tmp_path, family):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    row = build_tracking({"AAA": _df([FLOOR + 4.0] * 10, [0.0] * 10)}, tmp_path)[0]
    assert [m["code"] for m in row["risk_markers_now"]] == []


def test_both_price_markers_ordered_by_severity(tmp_path, family):
    """Les deux drapeaux ensemble : ordre du composeur existant, gravité décroissante."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    n = MIN_DAYS + 10
    splits = [0.0] * n
    splits[2] = 0.05
    row = build_tracking({"AAA": _df([FLOOR - 0.5] * n, splits)}, tmp_path)[0]
    assert [m["code"] for m in row["risk_markers_now"]] == ["reverse_split", "sub_dollar"]


# ---------------------------------------------------------------------------
# Ligne sans donnée de prix — liste vide, jamais une clé absente
# ---------------------------------------------------------------------------

def test_row_without_prices_keeps_an_empty_list(tmp_path, family):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path, ("AAA", "GONE"))
    rows = _by_ticker(build_tracking({"AAA": _df([FLOOR + 4.0] * 10)}, tmp_path))

    assert set(rows) == {"AAA", "GONE"}                 # la ligne muette reste servie
    gone = rows["GONE"]
    assert "risk_markers_now" in gone                   # clé présente…
    assert gone["risk_markers_now"] == []               # …et vide
    assert gone["phase"] == "no_data"                   # phase « données absentes » intacte
    assert gone["status"] == {"code": "no_data"}
    assert gone["days_held"] is None and gone["ret"] is None


def test_prices_stopping_before_entry_stay_no_data_but_are_read(tmp_path, family):
    """Série entièrement ANTÉRIEURE à l'entrée : aucune séance à mesurer (no_data),
    mais les drapeaux prix restent calculables sur ce qui est en main."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    df = _df([FLOOR - 0.5] * (MIN_DAYS + 5), start="2025-01-02")   # tout avant l'entrée
    row = build_tracking({"AAA": df}, tmp_path)[0]
    assert row["phase"] == "no_data"
    assert [m["code"] for m in row["risk_markers_now"]] == ["sub_dollar"]


# ---------------------------------------------------------------------------
# Zéro réseau — journal d'appels de la doublure de téléchargement
# ---------------------------------------------------------------------------

@pytest.fixture
def download_log(monkeypatch):
    """Journal des appels au téléchargement de prix (le complément Epic 9 S1 est le
    SEUL appel légitime pendant une construction de suivi)."""
    calls = []

    def spy(tickers, bench, period=None):
        calls.append(sorted(tickers))
        return {}

    monkeypatch.setattr(sb, "_download_prices", spy)
    return calls


def test_full_universe_triggers_no_download_at_all(tmp_path, family, download_log):
    write_snap, build_tracking, _ = family
    write_snap(tmp_path)
    rows = build_tracking({"AAA": _df([FLOOR - 0.5] * (MIN_DAYS + 5))}, tmp_path)

    assert download_log == []                     # tolérance zéro
    assert [m["code"] for m in rows[0]["risk_markers_now"]] == ["sub_dollar"]


def test_missing_ticker_keeps_the_single_backfill_call(tmp_path, family, download_log):
    """Un titre sorti de l'univers : exactement l'appel du complément préexistant,
    aucun autre — les drapeaux prix ne consultent jamais le réseau."""
    write_snap, build_tracking, _ = family
    write_snap(tmp_path, ("AAA", "GONE"))
    build_tracking({"AAA": _df([FLOOR + 4.0] * 10)}, tmp_path)

    assert download_log == [["GONE"]]


# ---------------------------------------------------------------------------
# Contrat de suivi — le jeu de clés ne fait que croître
# ---------------------------------------------------------------------------

def test_tracking_contract_only_grows(tmp_path, family):
    write_snap, build_tracking, prior_keys = family
    entry_markers = [{"code": "going_concern", "level": "high", "date": "2026-06-30"}]
    write_snap(tmp_path, markers=entry_markers)
    row = build_tracking({"AAA": _df([FLOOR - 0.5] * (MIN_DAYS + 5))}, tmp_path)[0]

    assert prior_keys <= set(row)                       # aucune clé retirée ni renommée
    assert row["risk_markers"] == entry_markers         # l'entrée garde nom ET valeur
    assert [m["code"] for m in row["risk_markers_now"]] == ["sub_dollar"]  # l'actuel diffère
