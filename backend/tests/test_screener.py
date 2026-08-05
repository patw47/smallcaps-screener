"""
Tests unitaires offline du screener (Niveaux 1–2 du plan de validation).

Déterministes, sans réseau : on nourrit les helpers purs et la Passe A avec des
pd.Series/DataFrame synthétiques et on assert les sorties exactes.

Lancer : DATA_DIR=/tmp/screener_test pytest backend/tests/ -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")  # évite makedirs("/app/data")

import ast
import json
from pathlib import Path

import pandas as pd
import pytest

import scoring
import screener_backend
from scoring import score_candidates
from screener_backend import (
    FILTERS,
    _sma, _ma_rising, _median_dollar_volume, _rs_metrics,
    _atr, _obv_rising, _pct_of_high, _accum_fraction,
    _rank_pct, _factor_composite, TECH_FACTORS,
    _score_candidates, _build_positives_flags, analyze_prices,
)


# ---------------------------------------------------------------------------
# Niveau 1 — helpers purs
# ---------------------------------------------------------------------------

def test_median_dollar_volume_robust_to_spike():
    close = pd.Series([10.0] * 20)
    volume = pd.Series([100] * 19 + [100_000])  # un spike de fin
    # médiane = 10 * 100 = 1000, non tirée par le pic (contrairement à la moyenne)
    assert _median_dollar_volume(close, volume, 20) == 1000.0


def test_ma_rising_uptrend():
    close = pd.Series(range(1, 101), dtype=float)  # strictement croissant
    assert _ma_rising(close, 50, 10) is True


def test_ma_rising_downtrend():
    close = pd.Series(range(100, 0, -1), dtype=float)  # strictement décroissant
    assert _ma_rising(close, 50, 10) is False


def test_ma_rising_insufficient_history():
    close = pd.Series(range(1, 40), dtype=float)  # < window + lookback
    assert _ma_rising(close, 50, 10) is None


def test_sma_last_window():
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _sma(close, 3) == 4.0  # mean(3,4,5)


def test_rs_metrics_outperformance():
    # titre ~+20% vs benchmark ~+5% sur la fenêtre → surperforme, RS-line monte, magnitude > 0
    stock = pd.Series([100 * (1.20 ** (i / 63)) for i in range(64)])
    bench = pd.Series([100 * (1.05 ** (i / 63)) for i in range(64)])
    outperf, rising, strength = _rs_metrics(stock, bench, 63, 21)
    assert outperf is True
    assert rising is True
    assert strength > 0.10          # ~+15% de surperf


def test_rs_metrics_underperformance():
    stock = pd.Series([100 * (0.90 ** (i / 63)) for i in range(64)])  # baisse
    bench = pd.Series([100 * (1.05 ** (i / 63)) for i in range(64)])  # hausse
    outperf, rising, strength = _rs_metrics(stock, bench, 63, 21)
    assert outperf is False
    assert rising is False
    assert strength < 0


def test_rs_metrics_no_benchmark():
    assert _rs_metrics(pd.Series([1.0] * 100), None, 63, 21) == (None, None, None)


# ---------------------------------------------------------------------------
# Palier 2 — ATR, OBV, position 52 semaines
# ---------------------------------------------------------------------------

def test_atr_needs_high_low():
    idx = pd.date_range("2025-01-01", periods=30, freq="B")
    df = pd.DataFrame({"Close": range(30), "Volume": [1] * 30}, index=idx)  # pas de High/Low
    assert _atr(df, 20) is None


def test_atr_constant_range():
    idx = pd.date_range("2025-01-01", periods=30, freq="B")
    close = pd.Series([10.0] * 30, index=idx)
    df = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close}, index=idx)
    # range quotidien constant = 2, pas de gap → ATR = 2
    assert abs(_atr(df, 20) - 2.0) < 1e-9


def test_obv_rising_on_uptrend():
    close = pd.Series([10.0 + i for i in range(30)])   # hausse continue
    volume = pd.Series([1000] * 30)
    assert _obv_rising(close, volume, 21) is True


def test_obv_falling_on_downtrend():
    close = pd.Series([40.0 - i for i in range(30)])   # baisse continue
    volume = pd.Series([1000] * 30)
    assert _obv_rising(close, volume, 21) is False


def test_pct_of_high():
    close = pd.Series([50.0, 80.0, 100.0, 90.0])       # dernier = 90, plus-haut = 100
    assert abs(_pct_of_high(close, 252) - 0.90) < 1e-9


# ---------------------------------------------------------------------------
# Niveau 2 — régression sur les bugs corrigés
# ---------------------------------------------------------------------------

def test_cash_positive_none_no_debt_flag():
    """Donnée bilan absente → cash_positive None → PAS de faux flag dette."""
    stock = {"cash_positive": None}
    _, flags = _build_positives_flags(stock)
    assert not any("Dette" in f for f in flags)


def test_cash_positive_false_emits_flag():
    stock = {"cash_positive": False}
    _, flags = _build_positives_flags(stock)
    assert any("Dette" in f for f in flags)


# ---------------------------------------------------------------------------
# Scoring PERCENTILE de facteurs continus
# ---------------------------------------------------------------------------

def test_rank_pct_orders_and_neutral_none():
    p = _rank_pct([10.0, 30.0, 20.0])
    assert p[1] == 1.0 and p[0] == 0.0        # plus grand → 1, plus petit → 0
    assert 0.0 < p[2] < 1.0
    assert _rank_pct([5.0, None])[1] == 0.5   # None → neutre


def test_accum_fraction_sign():
    vol = pd.Series([1000] * 30)
    assert _accum_fraction(pd.Series([10.0 + i for i in range(30)]), vol, 21) > 0.9    # tout acheteur
    assert _accum_fraction(pd.Series([40.0 - i for i in range(30)]), vol, 21) < -0.9   # tout vendeur


def test_factor_composite_best_item_tops():
    # item 1 = meilleur sur TOUS les facteurs (accum/rs/pivot hauts ; atr_ratio/ext bas)
    items = [
        {"f_accum": 0.1, "f_atr_ratio": 0.9, "f_pct_recent": 0.5, "f_ext": 0.30, "f_rs": 0.0},
        {"f_accum": 0.9, "f_atr_ratio": 0.4, "f_pct_recent": 0.99, "f_ext": 0.01, "f_rs": 0.5},
        {"f_accum": 0.3, "f_atr_ratio": 0.7, "f_pct_recent": 0.70, "f_ext": 0.20, "f_rs": 0.1},
    ]
    comp = _factor_composite(items, TECH_FACTORS)
    assert comp[1] == max(comp)               # le meilleur sur tout → composite max
    assert comp[1] > comp[0]


def test_scoring_mode_switch():
    # le fort > le faible dans les deux modes ; en continu, décile sur 2 items → 10 et 0
    strong = {
        "accumulation": True, "compressed": True, "near_pivot": True, "low_ext": True,
        "rs_turning": True, "price_above_ma50": True, "insider_buying": True,
        "cash_positive": True, "revenue_growth": 0.5, "low_float": True, "short_interest_pct": 20.0,
        "f_accum": 0.9, "f_atr_ratio": 0.4, "f_pct_recent": 0.99, "f_ext": 0.01, "f_rs": 0.5,
        "cash_bin": 1.0, "insider_pct": 30.0, "float_shares": 1e6,
    }
    weak = {
        "f_accum": 0.1, "f_atr_ratio": 0.9, "f_pct_recent": 0.4, "f_ext": 0.3, "f_rs": 0.0,
        "cash_bin": None, "insider_pct": 0.0, "float_shares": 9e8,
    }
    old = FILTERS["scoring_mode"]
    try:
        FILTERS["scoring_mode"] = "binary"
        c = [dict(strong), dict(weak)]
        _score_candidates(c)
        assert c[0]["score"] > c[1]["score"]

        FILTERS["scoring_mode"] = "continuous"
        c2 = [dict(strong), dict(weak)]
        _score_candidates(c2)
        assert c2[0]["score"] == 10 and c2[1]["score"] == 0   # rang décile sur 2 items
    finally:
        FILTERS["scoring_mode"] = old


# ---------------------------------------------------------------------------
# Niveau 1/2 — Passe A intégrée (offline, DataFrame synthétique)
# ---------------------------------------------------------------------------

def _make_df(closes, volumes):
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


def test_pass_a_rejects_downtrend_legacy():
    # Comportement funnel v1 (pool "legacy") : baisse douce 35 → 15, dans la bande 2-25,
    # mais pente MA50 négative → rejet tendance (garde-fou couteau qui tombe).
    # En mode "tradability" (défaut, Epic 2) ce titre est au contraire GARDÉ (cf. test_profiles).
    closes = [35.0 - i * 0.1 for i in range(200)]
    df = _make_df(closes, [500_000] * len(closes))
    old = FILTERS["pool_mode"]
    try:
        FILTERS["pool_mode"] = "legacy"
        signals, reason = analyze_prices("DOWN", df, None)
    finally:
        FILTERS["pool_mode"] = old
    assert signals is None
    assert reason == "trend:down"


def test_pass_a_rejects_illiquid():
    # uptrend dans la bande de prix mais volume ridicule → rejet liquidité
    closes = [10.0 + i * 0.05 for i in range(200)]  # 10 → ~20
    volumes = [10] * 200  # ~15 * 10 = 150 USD/j « dollar-volume »
    df = _make_df(closes, volumes)
    signals, reason = analyze_prices("ILLIQ", df, None)
    assert signals is None
    assert reason.startswith("liquidity")


def test_pass_a_accepts_healthy_uptrend():
    # uptrend doux dans la bande de prix, liquide, perf 1m modérée
    closes = [10.0 + i * 0.05 for i in range(200)]  # ~10 → ~20, pente positive
    volumes = [200_000] * 200  # dollar-vol ~ 20*200k = 4M > seuil
    df = _make_df(closes, volumes)
    signals, reason = analyze_prices("UP", df, None)
    assert reason == "ok"
    assert signals is not None
    assert signals["price_above_ma50"] is True
    assert FILTERS["price_min"] <= signals["price"] <= FILTERS["price_max"]


def test_reverse_split_flag_from_actions_column():
    # Epic 3 S2 : reverse_split_flag lu depuis la colonne 'Stock Splits' du download (actions=True).
    closes = [10.0 + i * 0.05 for i in range(200)]
    df = _make_df(closes, [200_000] * 200)
    s, _ = analyze_prices("NOSPLIT", df, None)
    assert s["reverse_split_flag"] is None                      # pas de colonne → neutre

    df2 = df.copy()
    df2["Stock Splits"] = 0.0
    df2.iloc[-30, df2.columns.get_loc("Stock Splits")] = 0.1    # 1-for-10 reverse → ratio ∈ ]0,1[
    s2, _ = analyze_prices("REV", df2, None)
    assert s2["reverse_split_flag"] is True

    df3 = df.copy()
    df3["Stock Splits"] = 0.0
    df3.iloc[-30, df3.columns.get_loc("Stock Splits")] = 10.0   # forward split → PAS un reverse
    s3, _ = analyze_prices("FWD", df3, None)
    assert s3["reverse_split_flag"] is False


def test_pass_a_accepts_price_below_rising_ma():
    # MA50 en hausse, prix repassé sous la MA50 (pullback tôt) : DÉSORMAIS accepté
    # (prix>MA50 n'est plus un filtre dur → on capte le début, pas seulement le déjà-reparti)
    closes = [10.0 + i * 0.1 for i in range(200)]  # uptrend franc
    closes[-1] = 22.0                              # dip final sous la MA50 (~27), dans 2-25
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("PB", df, None)
    assert reason == "ok"
    assert signals["price_above_ma50"] is False    # sous la MA50, mais gardé


def test_pass_a_weak_rs_not_rejected():
    # RS n'est plus un filtre dur (rs_require=False) → un titre qui sous-performe passe,
    # avec rs_turning=False (la RS ne repart pas) → il sera juste moins bien classé
    idx = pd.date_range("2025-01-01", periods=200, freq="B")
    closes = [10.0 + i * 0.01 for i in range(200)]        # uptrend mou
    df = _make_df(closes, [300_000] * 200)
    bench = pd.Series([100.0 * (1.6 ** (i / 199)) for i in range(200)], index=idx)  # benchmark fort
    signals, reason = analyze_prices("WEAKRS", df, bench)
    assert reason == "ok"
    assert signals["rs_turning"] is False


def test_pass_a_no_benchmark_ok():
    # benchmark absent → RS neutralisée, titre gardé
    closes = [10.0 + i * 0.05 for i in range(200)]
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("NOBENCH", df, None)
    assert reason == "ok"


def test_scoring_contract_p_explode_null_and_survival_risk_bool():
    # Epic 7 S2 : le modèle v3 est supprimé, le CONTRAT ne bouge pas — p_explode reste
    # présent à None (aucune probabilité inventée), survival_risk reste un vrai booléen.
    risky = {"ticker": "AAA", "going_concern_flag": True}
    healthy = {"ticker": "BBB", "going_concern_flag": False}
    before = set(risky)
    score_candidates([risky, healthy])
    assert risky["p_explode"] is None and healthy["p_explode"] is None
    assert risky["survival_risk"] is True and healthy["survival_risk"] is False
    # Epic 10 S1 : le détail S'AJOUTE (risk_markers), le booléen garde nom et sémantique.
    assert set(risky) - before == {"p_explode", "survival_risk", "risk_markers"}


# ---------------------------------------------------------------------------
# Epic 10 S1 — DÉTAIL des marqueurs à la place du badge unique
#
# Le booléen agrégé écrasait cinq faits hétérogènes : un doute sur la continuité
# d'exploitation y pesait autant qu'un rapport déposé en retard. La liste détaillée
# s'AJOUTE à côté, en codes + variables — jamais de texte d'affichage côté backend.
# ---------------------------------------------------------------------------

def test_risk_markers_empty_list_when_no_marker():
    # Une sélection sans marqueur porte une LISTE VIDE, pas une absence de clé : le
    # frontend n'a pas à distinguer « rien à signaler » de « champ oublié ».
    sain = {"ticker": "SAIN"}
    score_candidates([sain])
    assert sain["risk_markers"] == []
    assert sain["survival_risk"] is False


def test_risk_markers_two_markers_produce_exactly_two_entries():
    # Deux marqueurs levés → exactement deux entrées, chacune un code + ses variables.
    s = {"ticker": "AAA", "going_concern_flag": True, "late_filing_flag": True,
         "dilution_flag": False, "sub_dollar_flag": False, "reverse_split_flag": None}
    score_candidates([s])
    assert [m["code"] for m in s["risk_markers"]] == ["going_concern", "late_filing"]
    for m in s["risk_markers"]:
        # Codes et variables SEULEMENT : aucune chaîne destinée à l'affichage.
        assert set(m) <= {"code", "level", "date", "days"}
        assert m["code"] in scoring.MARKER_LEVELS


def test_risk_markers_carry_dates_when_available_and_survive_without():
    # Date disponible → portée telle quelle ; date absente → le marqueur reste dans la
    # liste, sans clé `date` et sans exception.
    date, sans_date = (
        {"going_concern_flag": True, "going_concern_date": "2026-05-15",
         "reverse_split_flag": True, "reverse_split_date": "2026-03-02"},
        {"going_concern_flag": True, "reverse_split_flag": True, "dilution_flag": True},
    )
    score_candidates([date, sans_date])
    assert {m["code"]: m.get("date") for m in date["risk_markers"]} == {
        "going_concern": "2026-05-15", "reverse_split": "2026-03-02"}
    assert [m["code"] for m in sans_date["risk_markers"]] == [
        "going_concern", "reverse_split", "dilution"]
    assert all("date" not in m for m in sans_date["risk_markers"])


def test_risk_markers_carry_severity_level():
    # Le niveau est une DONNÉE émise par le backend, pas du style : un marqueur sans
    # niveau fait échouer ce test.
    s = {f"{code}_flag": True for code in scoring.MARKER_LEVELS}
    s["sub_dollar_days"] = 42
    score_candidates([s])
    niveaux = {m["code"]: m["level"] for m in s["risk_markers"]}
    assert len(niveaux) == len(scoring.MARKER_LEVELS)
    assert niveaux["going_concern"] == "high"      # continuité d'exploitation
    assert niveaux["reverse_split"] == "high"      # regroupement d'actions
    assert niveaux["dilution"] == "medium"         # émission d'actions à venir
    assert niveaux["late_filing"] == "low"         # retard de dépôt
    assert niveaux["sub_dollar"] == "low"          # cours sous le plancher
    assert all(m.get("level") for m in s["risk_markers"])


def test_sub_dollar_marker_carries_run_length_not_a_boolean():
    # La gravité voyage en VALEUR : la longueur de série, pas un booléen de plus.
    s = {"sub_dollar_flag": True, "sub_dollar_days": 37}
    score_candidates([s])
    marker = next(m for m in s["risk_markers"] if m["code"] == "sub_dollar")
    assert marker["days"] == 37
    assert not isinstance(marker["days"], bool)


def test_reverse_split_marker_dates_the_operation():
    # La date de l'opération sort de la série DÉJÀ parcourue — aucun appel réseau.
    closes = [10.0 + i * 0.05 for i in range(200)]
    df = _make_df(closes, [200_000] * 200)
    df["Stock Splits"] = 0.0
    df.iloc[-30, df.columns.get_loc("Stock Splits")] = 0.1
    flag, date = screener_backend._reverse_split_marker(df)
    assert flag is True
    assert date == str(df.index[-30].date())
    # Colonne absente → capteur muet, aucune date inventée.
    assert screener_backend._reverse_split_marker(_make_df(closes, [200_000] * 200)) == (None, None)


def test_scan_payload_keys_frozen():
    # Clés top-level du JSON de scan, gelées : lues dans le littéral `output` de run_scan
    # (pas de réseau). Une clé perdue au fil d'un refactor casserait le frontend en silence.
    src = Path(screener_backend.__file__).read_text(encoding="utf-8")
    output = next(n.value for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "output")
    assert {k.value for k in output.keys} == {
        "scanned_at", "universe_size", "total_scanned", "survivors_price_filter",
        "profile_members", "pool_mode", "v3_model", "v4_cohort", "v4_note", "v4_mkt21",
        "v4_prelist", "v4_tracking", "v5", "display", "enriched", "candidates",
        "stocks", "rejection_stats",
    }


def test_snapshot_top_level_keys_frozen(tmp_path, monkeypatch):
    # Non-régression du snapshot quotidien (Epic 8 S1) : l'invariant porte sur le JEU
    # DE CLÉS de premier niveau, JAMAIS sur les valeurs — le scan quotidien les
    # renouvelle par construction. Tolérance zéro clé ajoutée ou retirée : l'historique
    # est la matière première du jugement forward, il se relit sur des années.
    monkeypatch.setattr(screener_backend, "HISTORY_DIR", tmp_path)
    screener_backend._write_snapshot({
        "scanned_at": "2026-08-04T12:00:00+00:00",
        "stocks": [],
        "v4_cohort": [],
        "v4_note": {"code": "market_bullish", "w": 21, "mkt": 0.01},
        "v5": {"windows": {}, "flash": False, "flash_ret3": None},
    })
    snap = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert set(snap) == {"scanned_at", "candidates", "picks", "v4_cohort", "v4_note", "v5"}


def test_pass_a_near_pivot_and_low_ext_signals():
    # uptrend doux, dernier prix proche du plus-haut récent et proche de la MA50
    closes = [10.0 + i * 0.03 for i in range(200)]  # ~10 → ~16, dans 2-25
    df = _make_df(closes, [200_000] * 200)
    signals, reason = analyze_prices("EARLY", df, None)
    assert reason == "ok"
    # dernier prix = plus-haut récent (série croissante) → près du pivot
    assert signals["near_pivot"] is True
    # pente douce → prix reste proche de la MA50 → peu étiré
    assert signals["low_ext"] is True


# ---------------------------------------------------------------------------
# Drapeaux de contexte (Epic 1 S7) — INFORMATION seulement, jamais une exclusion.
# Ils disent à l'humain qu'un signal technique se lit autrement sur ce titre-là.
# ---------------------------------------------------------------------------

def test_binary_event_sector_detected_on_industry_and_sector():
    """Une biotech porte le drapeau ; un industriel non. `industry` est plus précis que
    `sector` (qui range toute la santé ensemble) — les deux sont lus."""
    biotech = {"industry": "Biotechnology", "sector": "Healthcare"}
    pharma = {"industry": "Drug Manufacturers — Specialty & Generic", "sector": "Healthcare"}
    dispositif = {"industry": "Medical Devices", "sector": "Healthcare"}
    acier = {"industry": "Steel", "sector": "Industrials"}

    assert screener_backend._is_binary_event_sector(biotech) is True
    assert screener_backend._is_binary_event_sector(pharma) is True
    # Santé ≠ évènement binaire : un fabricant de dispositifs ne vit pas sur un verdict FDA
    assert screener_backend._is_binary_event_sector(dispositif) is False
    assert screener_backend._is_binary_event_sector(acier) is False
    # Donnée absente : silencieux, jamais une exception
    assert screener_backend._is_binary_event_sector({}) is False
    assert screener_backend._is_binary_event_sector({"industry": None, "sector": None}) is False


def test_days_to_earnings_best_effort():
    """La date est détectée quand elle existe ; absente, illisible ou passée → None,
    jamais une erreur (yfinance ne la sert que pour une partie des micro-caps)."""
    from datetime import datetime, timedelta, timezone as tz
    maintenant = datetime(2026, 8, 4, tzinfo=tz.utc)
    dans_5j = (maintenant + timedelta(days=5)).timestamp()
    passe = (maintenant - timedelta(days=3)).timestamp()

    assert screener_backend._days_to_earnings({"earningsTimestamp": dans_5j}, maintenant) == 5
    # `earningsTimestampStart` est prioritaire (yfinance le sert plus souvent)
    assert screener_backend._days_to_earnings(
        {"earningsTimestampStart": dans_5j, "earningsTimestamp": passe}, maintenant) == 5
    assert screener_backend._days_to_earnings({"earningsTimestamp": passe}, maintenant) is None
    assert screener_backend._days_to_earnings({}, maintenant) is None
    assert screener_backend._days_to_earnings({"earningsTimestamp": None}, maintenant) is None
    # Valeur aberrante : ne doit pas remonter d'exception
    assert screener_backend._days_to_earnings({"earningsTimestamp": 1e30}, maintenant) is None


def test_context_flags_are_codes_never_french_sentences():
    """Les deux drapeaux sortent en CODE + variables, traduits par le frontend — le
    backend ne fabrique plus de phrase affichable (Epic 8 S1)."""
    _, flags = screener_backend._build_positives_flags(
        {"binary_event": True, "days_to_earnings": 3})
    codes = {f["code"]: f for f in flags if isinstance(f, dict)}
    assert codes["binary_event"] == {"code": "binary_event"}
    assert codes["earnings_soon"] == {"code": "earnings_soon", "d": 3}


def test_context_flags_silent_when_data_missing_or_far():
    """Donnée absente ou résultats lointains : aucun drapeau, aucune erreur."""
    _, flags = screener_backend._build_positives_flags({})
    assert [f for f in flags if isinstance(f, dict)] == []

    loin = screener_backend.FILTERS["earnings_soon_days"] + 1
    _, flags = screener_backend._build_positives_flags(
        {"binary_event": False, "days_to_earnings": loin})
    assert [f for f in flags if isinstance(f, dict)] == []

    # Frontière exacte : le jour du seuil est encore signalé
    _, flags = screener_backend._build_positives_flags(
        {"days_to_earnings": screener_backend.FILTERS["earnings_soon_days"]})
    assert {"code": "earnings_soon", "d": screener_backend.FILTERS["earnings_soon_days"]} in flags


def test_context_flags_never_exclude_a_name():
    """Le critère central du sprint : ces drapeaux n'excluent RIEN. Un titre biotech avec
    résultats imminents produit les mêmes positifs qu'un titre neutre par ailleurs."""
    base = {"cash_positive": True, "revenue_growth": 0.5}
    pos_neutre, flags_neutre = screener_backend._build_positives_flags(dict(base))
    pos_flague, flags_flague = screener_backend._build_positives_flags(
        {**base, "binary_event": True, "days_to_earnings": 2})

    # Mêmes points positifs : le contexte n'enlève ni n'ajoute rien au reste
    assert pos_flague == pos_neutre
    # Et il n'ajoute que les deux drapeaux d'information
    ajoutes = [f for f in flags_flague if f not in flags_neutre]
    assert ajoutes == [{"code": "binary_event"}, {"code": "earnings_soon", "d": 2}]


# ---------------------------------------------------------------------------
# Epic 9 S2 — marqueur « cours sous le plancher de cotation », en SÉRIE CONSÉCUTIVE
#
# La règle de cotation ne mord qu'après une série ininterrompue sous le plancher.
# Le drapeau d'avant valait « a effleuré le plancher au moins une fois dans la
# fenêtre » : un après-midi de panique y comptait autant que six mois de végétation.
# La longueur de la série est exposée à côté du booléen — c'est elle qui porte la
# gravité, et un seuil brut la jette.
# ---------------------------------------------------------------------------

def _sub_dollar_history(pattern_under: list[bool], n: int = 200) -> pd.DataFrame:
    """Titre à 3 $ dont les dernières séances suivent `pattern_under` (True = sous 1 $).
    Le cours FINAL reste au-dessus du plancher de tradabilité : le titre passe la Passe A,
    donc le drapeau est bien lu sur un candidat réel et non sur un rejet."""
    closes = [3.0] * (n - len(pattern_under))
    closes += [0.50 if under else 3.0 for under in pattern_under]
    return _make_df(closes, [500_000] * n)


def test_sub_dollar_flag_raised_after_consecutive_run():
    # Effet injecté : la série atteint exactement la longueur de la règle → drapeau levé.
    n = FILTERS["sub_dollar_min_days"]
    df = _sub_dollar_history([True] * n + [False] * 20)
    signals, reason = analyze_prices("RUN", df, None)
    assert reason == "ok"
    assert signals["sub_dollar_days"] == n
    assert signals["sub_dollar_flag"] is True


def test_sub_dollar_flag_not_raised_one_session_short():
    # Effet insuffisant : une séance de moins → pas de non-conformité, série exposée quand même.
    n = FILTERS["sub_dollar_min_days"] - 1
    df = _sub_dollar_history([True] * n + [False] * 20)
    signals, reason = analyze_prices("SHORT", df, None)
    assert reason == "ok"
    assert signals["sub_dollar_days"] == n
    assert signals["sub_dollar_flag"] is False


def test_sub_dollar_flag_ignores_isolated_contact():
    # Bruit pur : un contact isolé entouré de clôtures au-dessus du plancher.
    # C'est le cas que l'ancien drapeau (minimum de la fenêtre) levait à tort.
    df = _sub_dollar_history([False] * 10 + [True] + [False] * 20)
    signals, reason = analyze_prices("SPIKE", df, None)
    assert reason == "ok"
    assert signals["sub_dollar_days"] == 1
    assert signals["sub_dollar_flag"] is False
    assert float(df["Close"].tail(FILTERS["sub_dollar_window"]).min()) < FILTERS["sub_dollar_price"]


# ---------------------------------------------------------------------------
# Epic 9 S2 — non-régression de la SÉLECTION, tolérance zéro
#
# Artefact : la séquence ORDONNÉE des tickers sélectionnés, produite depuis des
# fixtures de prix figées. Invariant : égalité exacte de la séquence et de son ordre.
# Brancher un marqueur de détresse dans la sélection ou le classement fait échouer
# ce test — la mesure de prévalence est descriptive, elle n'entre nulle part.
#
# Le même test verrouille le report du S1 (finding 1) : le complément de prix des
# titres suivis mute `prices` EN PLACE, et les constructeurs de cohorte le reçoivent
# enrichi de titres HORS UNIVERS. C'est inoffensif tant qu'ils itèrent sur les
# tradables et n'utilisent `prices` qu'en lookup — rien ne le testait. La fixture
# injecte ici un intrus par ce chemin exact (entrée de cohorte historique hors
# univers), calibré pour qualifier partout s'il était vu : le test rougit dès qu'un
# constructeur se met à itérer sur `prices`.
# ---------------------------------------------------------------------------

INTRUDER = "ZZOUT"     # jamais dans l'univers scanné, seulement dans l'historique suivi


def _ohlcv_df(closes: list[float], vol: float = 500_000) -> pd.DataFrame:
    """OHLCV complet : les capteurs v2 (flux d'argent, calme du volume) exigent High/Low,
    sans quoi les constructeurs de cohorte v5 écartent TOUT et l'assertion serait vide.
    Clôture au milieu de la bande chaque séance → flux d'argent neutre."""
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"High": [c * 1.02 for c in closes], "Low": [c * 0.98 for c in closes],
                         "Close": closes, "Volume": [vol] * len(closes)}, index=idx)


def _trend_df(start: float, daily: float, n: int = 200, vol: float = 500_000) -> pd.DataFrame:
    return _ohlcv_df([start * (1 + daily) ** i for i in range(n)], vol)


@pytest.fixture
def offline_scan(monkeypatch, tmp_path):
    """Scan complet hors ligne : prix figés, `.info` figé, dépôts officiels muets,
    historique de suivi dans tmp_path. Renvoie l'univers scanné."""
    bench = FILTERS["rs_benchmark"]
    universe = [f"T{i}" for i in range(8)]
    frames = {tk: _trend_df(10.0, 0.0002 * i) for i, tk in enumerate(universe)}
    frames[bench] = _trend_df(100.0, 0.0001)
    # Trois SÉLECTIONS portent un marqueur, un par capteur : sans cela, brancher un
    # marqueur dans la sélection ne changerait rien et le test ne pourrait pas rougir.
    frames["T7"] = _ohlcv_df([0.50] * 170 + [0.50 + i * (2.5 / 29) for i in range(30)])
    frames["T0"] = frames["T0"].assign(**{"Stock Splits": [0.0] * 190 + [0.1] + [0.0] * 9})
    # L'intrus est CALIBRÉ pour qualifier s'il était vu : tradable (prix et liquidité),
    # sous le plafond de prix des règles de cohorte, et en chute franche sur un mois
    # comme sur une semaine. Son absence des listes est donc une preuve, pas un hasard.
    frames[INTRUDER] = _ohlcv_df(
        [5.0] * 170 + [5.0 - i * (1.0 / 22) for i in range(23)]
        + [4.0 - i * (1.0 / 6) for i in range(7)],
        900_000)

    def fake_download(tickers, bench_symbol, period=None):
        out = {tk: frames[tk] for tk in tickers if tk in frames}
        if bench_symbol in frames:
            out[bench_symbol] = frames[bench_symbol]
        return out

    monkeypatch.setattr(screener_backend, "_download_prices", fake_download)
    monkeypatch.setattr(screener_backend, "_fetch_info",
                        lambda tk: {"exchange": "NMS", "marketCap": 300e6, "shortName": tk,
                                    "sector": "Healthcare", "industry": "Biotechnology"})
    import edgar
    # La date de dépôt accompagne le drapeau (Epic 10 S1) : c'est elle qui doit voyager
    # jusqu'à la réponse servie, sans qu'aucun appel réseau supplémentaire soit fait.
    monkeypatch.setattr(edgar, "survival_signals", lambda tk, *a, **k: {
        "dilution_flag": tk == "T1", "late_filing_flag": False, "going_concern_flag": False,
        "dilution_date": "2026-07-14" if tk == "T1" else None})
    monkeypatch.setattr(edgar, "net_insider_buying", lambda *a, **k: None)
    monkeypatch.setattr(screener_backend, "HISTORY_DIR", tmp_path)
    # Entrée de cohorte HORS UNIVERS : c'est elle qui déclenche le complément de prix
    # (Epic 9 S1) et fait entrer l'intrus dans le dictionnaire partagé.
    (tmp_path / "20260101_000000.json").write_text(json.dumps({
        "scanned_at": "2026-01-01T00:00:00+00:00", "candidates": 0, "picks": [],
        "v4_cohort": [{"ticker": INTRUDER, "price": 40.0}], "v4_note": {},
        "v5": {"windows": {}, "flash": False, "flash_ret3": None},
    }))
    return universe


# Séquence gelée : membres de profil (deux d'une famille, trois de l'autre), classés par
# force de profil décroissante. Identique avant et après le sprint, tolérance zéro.
SELECTION_FROZEN = ["T7", "T6", "T0", "T1", "T2"]


def test_selection_sequence_frozen(offline_scan):
    out = screener_backend.run_scan(offline_scan)
    assert [s["ticker"] for s in out["stocks"]] == SELECTION_FROZEN


def test_backfilled_prices_never_leak_into_selection(offline_scan):
    out = screener_backend.run_scan(offline_scan)
    # Le complément a bien eu lieu : sans lui le test ne prouverait rien.
    assert any(r["ticker"] == INTRUDER for r in out["v4_tracking"])
    # Et l'intrus est bien calibré : il passe la Passe A ET les règles-titre des DEUX
    # familles de cohorte. Sans cette garde, son absence des listes ne prouverait rien.
    import v4
    import v5
    df = screener_backend._download_prices([INTRUDER], FILTERS["rs_benchmark"])[INTRUDER]
    sig, reason = analyze_prices(INTRUDER, df, None)
    assert reason == "ok" and v4._passes_price_rules(sig)
    assert v5._title_entry(INTRUDER, sig, df, min(v5.CFG["windows"])) is not None
    listes = {
        "stocks": [s["ticker"] for s in out["stocks"]],
        "v4_cohort": [e["ticker"] for e in out["v4_cohort"]],
        "v4_prelist": [e["ticker"] for e in out["v4_prelist"]],
    }
    for w, bloc in (out["v5"].get("windows") or {}).items():
        for quoi in ("cohort", "prelist"):
            listes[f"v5[{w}].{quoi}"] = [e["ticker"] for e in bloc.get(quoi) or []]
    for nom, tickers in listes.items():
        assert INTRUDER not in tickers, f"titre hors univers entré dans {nom}"


def test_snapshot_archives_the_five_markers_and_dollar_volume(offline_scan, tmp_path):
    # Les cinq marqueurs et le volume en dollars sont ARCHIVÉS : sans eux, chaque scan
    # jette une observation datée que rien ne reconstitue, et la prévalence n'est plus
    # qu'un cliché. On vérifie le jeu de clés ET les valeurs, sur les trois capteurs.
    screener_backend.run_scan(offline_scan)
    snap = json.loads(sorted(tmp_path.glob("*.json"))[-1].read_text())
    picks = {p["ticker"]: p for p in snap["picks"]}
    nouvelles = {"sub_dollar_flag", "reverse_split_flag", "dilution_flag",
                 "late_filing_flag", "going_concern_flag", "dollar_volume"}
    assert all(nouvelles <= set(p) for p in picks.values())
    assert picks["T7"]["sub_dollar_flag"] is True      # série consécutive sous le plancher
    assert picks["T0"]["reverse_split_flag"] is True   # regroupement d'actions
    assert picks["T1"]["dilution_flag"] is True        # dépôt d'émission d'actions
    assert all(p["dollar_volume"] > 0 for p in picks.values())


def test_markers_never_enter_selection_or_ranking(offline_scan):
    # Le critère central du sprint : les trois titres marqués sont TOUS sélectionnés, et
    # à leur rang. La mesure est descriptive — elle n'exclut ni ne déclasse personne.
    out = screener_backend.run_scan(offline_scan)
    marques = {"T7", "T0", "T1"}
    assert marques <= set(SELECTION_FROZEN)
    assert [s["ticker"] for s in out["stocks"]] == SELECTION_FROZEN
    assert {s["ticker"] for s in out["stocks"] if s["survival_risk"]} == marques


# ---------------------------------------------------------------------------
# Epic 10 S1 — non-régression du CONTRAT SERVI, et détail transporté jusqu'à la réponse
#
# Artefact : le jeu de clés d'une sélection dans la réponse servie. Invariant : toutes
# les clés antérieures restent présentes, `survival_risk` garde son nom ET sa valeur
# (la disjonction des cinq marqueurs) ; le jeu ne fait que CROÎTRE. Remplacer le booléen
# par le détail au lieu de l'accompagner fait échouer ce test.
# ---------------------------------------------------------------------------

# Jeu de clés d'une sélection AVANT ce sprint (gelé). Tolérance : aucune retirée, aucune
# renommée. Les clés ajoutées, elles, sont libres — c'est le sens de « ne fait que croître ».
STOCK_KEYS_BEFORE_EPIC10 = {
    "accumulation", "atr_ratio", "binary_event", "cash_bin", "cash_positive",
    "catalyst_date", "catalyst_type", "change_1d", "change_1m", "close_vs_sma20", "cmf",
    "compressed", "compression_pct", "days_since_trigger", "days_to_earnings",
    "dilution_flag", "dollar_volume", "exchange", "f_accum", "f_atr_ratio", "f_ext",
    "f_pct_recent", "f_rs", "flags", "float_shares", "fusee_event", "fusee_strength",
    "going_concern_flag", "industry", "insider_buying", "insider_net_buying",
    "insider_net_buying_pos", "insider_pct", "ipo_year", "is_fusee", "is_phenix",
    "late_filing_flag", "low_ext", "low_float", "ma50", "market_cap_m", "name",
    "near_high", "near_pivot", "p_explode", "pct_52w_high", "pct_recent_high",
    "phenix_strength", "pivot_level", "positives", "price", "price_above_ma50",
    "profile", "profile_strength", "profiles", "revenue_growth", "reverse_split_flag",
    "rs_line_rising", "rs_outperf", "rs_signal", "rs_strength", "rs_turning", "score",
    "sector", "setup_score", "short_interest_pct", "sma20", "sub_dollar_days",
    "sub_dollar_flag", "survival_risk", "ticker", "triggered", "updown_vol_ratio",
    "vol_ratio",
}


def test_served_stock_keys_only_grow_and_boolean_is_kept(offline_scan):
    out = screener_backend.run_scan(offline_scan)
    assert out["stocks"], "aucune sélection : le verrou serait vrai par vacuité"
    for s in out["stocks"]:
        manquantes = STOCK_KEYS_BEFORE_EPIC10 - set(s)
        assert not manquantes, f"{s['ticker']} : clé(s) servie(s) disparue(s) — {sorted(manquantes)}"
        # Le booléen agrégé garde son nom ET sa sémantique : la disjonction des cinq
        # marqueurs, indépendamment du détail qui l'accompagne.
        assert s["survival_risk"] is any(bool(s.get(f)) for f in scoring.RISK_FLAGS)
        assert isinstance(s["risk_markers"], list)   # le détail S'AJOUTE, il ne remplace pas
    # Détail et booléen désignent exactement les mêmes titres.
    assert ({s["ticker"] for s in out["stocks"] if s["risk_markers"]}
            == {s["ticker"] for s in out["stocks"] if s["survival_risk"]})


def test_marker_detail_travels_to_the_served_response(offline_scan):
    # Bout en bout : la liste détaillée arrive dans la réponse servie avec ses variables —
    # la longueur de série en VALEUR, la date du fait quand elle existe, le niveau toujours.
    out = screener_backend.run_scan(offline_scan)
    par_ticker = {s["ticker"]: s["risk_markers"] for s in out["stocks"]}

    # Cours sous le plancher : la gravité voyage en longueur de série, pas en booléen.
    sub = next(m for m in par_ticker["T7"] if m["code"] == "sub_dollar")
    t7 = next(s for s in out["stocks"] if s["ticker"] == "T7")
    assert sub["days"] == t7["sub_dollar_days"] > 1
    assert sub["level"] == "low"

    # Émission d'actions à venir : la date de dépôt est conservée telle quelle.
    dil = next(m for m in par_ticker["T1"] if m["code"] == "dilution")
    assert dil == {"code": "dilution", "level": "medium", "date": "2026-07-14"}

    # Regroupement d'actions : niveau haut, daté depuis la série de prix déjà parcourue.
    rev = next(m for m in par_ticker["T0"] if m["code"] == "reverse_split")
    assert rev["level"] == "high" and rev["date"]

    # Les sélections sans marqueur portent une liste vide, jamais une absence de clé.
    assert all(par_ticker[tk] == [] for tk in par_ticker if tk not in {"T7", "T1", "T0"})


# ---------------------------------------------------------------------------
# Epic 10 S2 — le tri vit dans l'interface, JAMAIS côté serveur
#
# Artefact : la séquence ordonnée des tickers de la réponse servie (le fichier que
# l'API renvoie, pas la valeur de retour). Invariant : identique à celle produite par
# le scan, et le contrat ne porte aucun paramètre de tri ni de filtre. Tolérance zéro.
# Trier côté serveur — dans `run_scan`, avant l'écriture, ou par un paramètre d'API —
# fait échouer ce test.
# ---------------------------------------------------------------------------

def test_served_order_is_the_scan_order(offline_scan):
    out = screener_backend.run_scan(offline_scan)
    servi = json.loads(screener_backend.OUTPUT_FILE.read_text())
    ordre_servi = [s["ticker"] for s in servi["stocks"]]

    # Ce qui est écrit pour l'API est exactement ce que le scan a classé, et rien ne
    # l'a réordonné en chemin.
    assert ordre_servi == [s["ticker"] for s in out["stocks"]] == SELECTION_FROZEN

    # Non-vacuité : trier par nombre de marqueurs DONNERAIT un ordre différent. Sans
    # cette garde, l'égalité ci-dessus pourrait être vraie par coïncidence de fixture.
    par_marqueurs = [s["ticker"] for s in
                     sorted(servi["stocks"], key=lambda s: -len(s["risk_markers"]))]
    assert par_marqueurs != ordre_servi


def test_scan_contract_carries_no_sort_or_filter_param():
    # Lu par AST sur le fichier réel : la route qui sert la liste ne prend AUCUN
    # paramètre. Pas de `sort=`, pas de `filter=` — donc rien à trier côté serveur.
    src = ast.parse((Path(__file__).resolve().parents[1] / "api.py").read_text())
    routes = {}
    for node in ast.walk(src):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and deco.args
                        and isinstance(deco.args[0], ast.Constant)):
                    continue
                routes[deco.args[0].value] = node.args
    args = routes["/api/scan"]
    assert not (args.args or args.posonlyargs or args.kwonlyargs
                or args.vararg or args.kwarg), "la route servant la liste a pris un paramètre"
