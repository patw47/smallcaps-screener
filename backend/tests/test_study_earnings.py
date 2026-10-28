"""Epic 15 S1 — étude SUE Q5 réalisable : règles sur données synthétiques, lac en option.

Les tests `lake` lisent le lac ta-patterns désigné par `study.ta_patterns_dir`
(CONFIG_FILE) ; sans lac ils sont sautés. Aucune valeur mesurée ici : les
populations sont fabriquées.
"""
import numpy as np
import pandas as pd
import pytest

from study import earnings as se
from study.lake import PINNED_COMMIT, head_commit, lake_dir

LAKE = lake_dir()
lake = pytest.mark.skipif(LAKE is None, reason="lac ta-patterns absent (study.ta_patterns_dir)")

SESSIONS = pd.DataFrame(
    {"symbol": "AAA", "date": pd.to_datetime(["2024-05-01", "2024-05-02", "2024-05-03", "2024-05-06"])}
)


def _event(eps_filed: str, accepted: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    ev = pd.DataFrame({"symbol": ["AAA"], "cik": [1], "t": pd.to_datetime(["2024-04-25 16:05"])})
    eps = pd.DataFrame(
        {
            "cik": [1],
            "period_end": pd.to_datetime(["2024-03-31"]),
            "filed": pd.to_datetime([eps_filed]),
            "accepted": pd.to_datetime([accepted]),
        }
    )
    return ev, eps


def test_b_filing_after_16h_enters_next_session_close():
    b, n = se.variant_b(*_event("2024-05-02", "2024-05-02 17:00"), SESSIONS)
    assert b["date_b"].tolist() == [pd.Timestamp("2024-05-03")]
    assert n["no_eps"] == 0


def test_b_filing_before_16h_enters_same_day_close():
    b, _ = se.variant_b(*_event("2024-05-02", "2024-05-02 10:00"), SESSIONS)
    assert b["date_b"].tolist() == [pd.Timestamp("2024-05-02")]


def test_b_filing_at_16h_sharp_enters_next_session_close():
    b, _ = se.variant_b(*_event("2024-05-02", "2024-05-02 16:00"), SESSIONS)
    assert b["date_b"].tolist() == [pd.Timestamp("2024-05-03")]


def test_b_filing_on_friday_evening_enters_monday():
    b, _ = se.variant_b(*_event("2024-05-03", "2024-05-03 18:30"), SESSIONS)
    assert b["date_b"].tolist() == [pd.Timestamp("2024-05-06")]


def test_case_without_eps_within_90_days_dropped_as_no_eps():
    ev, eps = _event("2024-07-25", "2024-07-25 10:00")  # 91 jours après le 8-K
    b, n = se.variant_b(ev, eps, SESSIONS)
    assert b.empty
    assert n["no_eps"] == 1


def test_eps_agreement_within_one_cent():
    x = pd.DataFrame(
        {"symbol": ["A", "A", "B"], "period_end": pd.to_datetime(["2024-03-31", "2024-06-30", "2024-03-31"]),
         "eps": [0.50, 0.40, 1.00]}
    )
    f = pd.DataFrame(
        {"symbol": ["A", "A", "B"], "fiscal_end": pd.to_datetime(["2024-03-31", "2024-06-29", "2024-03-31"]),
         "eps_actual": [0.51, 0.45, 1.00]}
    )
    m = se.eps_agreement(x, f)
    assert len(m) == 3
    assert m["ok"].sum() == 2


def _cluster_se(e: np.ndarray, g: np.ndarray) -> float:
    s = np.bincount(g, weights=e - e.mean())
    return float(np.sqrt(s @ s) / len(e))


def _net_rows(shift: float, seed: int, n: int = 20_000) -> pd.DataFrame:
    """horizons-like rows of a synthetic population: gain - spread per case, clustered se."""
    rng = np.random.default_rng(seed)
    sym = rng.integers(0, 2_000, n)
    rows = []
    for h in se.HORIZONS:
        spread = rng.uniform(0.0, 0.01, n)
        dev = shift + rng.normal(0.0, 0.08, n)
        e = dev - spread + spread.mean()  # spread payé en moyenne, gain net = shift
        rows.append(("A", "ex_nano", h, n, e.mean(), _cluster_se(e, sym)))
    return pd.DataFrame(rows, columns=["rule", "tier", "horizon", "n", "long_net", "se_long"])


def test_population_at_plus_3_points_is_kept():
    v = se.verdict_table(_net_rows(0.03, seed=1), agreement=1.0)
    row = v[(v["variant"] == "A") & (v["tier"] == "ex_nano")].iloc[0]
    assert row["t_21"] >= se.T_MIN
    assert row["verdict"] == "garder"
    assert v[v["variant"] == "C"]["verdict"].tolist() == ["garder"]


def test_random_population_is_not_proven():
    v = se.verdict_table(_net_rows(0.0, seed=2), agreement=1.0)
    assert v[v["variant"] == "A"]["verdict"].tolist() == ["non prouvé"]


def test_c_not_kept_under_agreement_threshold():
    v = se.verdict_table(_net_rows(0.03, seed=1), agreement=se.AGREEMENT_MIN - 0.01)
    assert v[v["variant"] == "C"]["verdict"].tolist() == ["accord insuffisant"]


def test_decide_rule():
    assert se.decide(3.0, 0.0, se.MIN_N) == "garder"
    assert se.decide(0.0, 3.0, se.MIN_N - 1) == "non prouvé"  # n < min_n : jamais gardé
    assert se.decide(-3.0, 1.0, se.MIN_N) == "réfuté"
    assert se.decide(2.9, -2.9, se.MIN_N) == "non prouvé"


def test_rule_text_is_the_epic_rule():
    assert se.RULE.startswith("Règle de décision pré-enregistrée")
    assert "t ≥ +3" in se.RULE and "n ≥ 2 000" in se.RULE


def test_lake_dir_unset_is_none(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("filters: {}\n")
    assert lake_dir(f) is None
    assert lake_dir(tmp_path / "absent.yml") is None


def test_head_commit_reads_packed_refs(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text(f"# pack-refs\n{'a' * 40} refs/heads/main\n")
    assert head_commit(tmp_path) == "a" * 40


@lake
def test_lake_head_is_readable():
    commit = head_commit(LAKE)
    assert len(commit) == 40
    if commit != PINNED_COMMIT:
        pytest.skip(f"lac à {commit}, étude épinglée sur {PINNED_COMMIT}")


@lake
def test_lake_has_events_and_measure_tools():
    for rel in ("data/derived/events.parquet", "tools/measure/compare.py", "tools/measure/costs.py"):
        assert (LAKE / rel).exists(), rel


def test_backend_accepts_study_section(tmp_path):
    import copy

    import screener_backend as sb

    f = tmp_path / "local.yml"
    f.write_text("study:\n  ta_patterns_dir: /nulle/part\n")
    sb.load_local_config(path=f, filters=copy.deepcopy(sb.FILTERS))  # ne lève pas
