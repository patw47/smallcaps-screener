"""
Tests offline de l'overlay de config locale (Epic 6 S1) — aucun réseau.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_config.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import copy

import pytest

import screener_backend as sb


def _fresh_filters() -> dict:
    return copy.deepcopy(sb.FILTERS)


def test_absent_file_keeps_defaults(tmp_path):
    filters = _fresh_filters()
    sb.load_local_config(path=tmp_path / "absent.yml", filters=filters)
    assert filters == sb.FILTERS


def test_empty_file_keeps_defaults(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("")
    filters = _fresh_filters()
    sb.load_local_config(path=f, filters=filters)
    assert filters == sb.FILTERS


def test_deep_merge_applied(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("filters:\n  sub_dollar_price: 3.5\n  nested:\n    b: 9\n")
    filters = {**_fresh_filters(), "nested": {"a": 1, "b": 2}}
    sb.load_local_config(path=f, filters=filters)
    assert filters["sub_dollar_price"] == 3.5
    assert filters["nested"] == {"a": 1, "b": 9}     # merge PROFOND : la clé sœur survit
    assert filters["sub_dollar_window"] == sb.FILTERS["sub_dollar_window"]


def test_unknown_filter_key_raises(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("filters:\n  sub_dolar_price: 3.5\n")  # typo volontaire
    with pytest.raises(sb.LocalConfigError, match="sub_dolar_price"):
        sb.load_local_config(path=f, filters=_fresh_filters())


def test_unknown_nested_key_raises(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("filters:\n  nested:\n    c: 9\n")
    with pytest.raises(sb.LocalConfigError, match="nested.c"):
        sb.load_local_config(path=f, filters={"nested": {"a": 1}})


def test_unknown_section_raises(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("telegram:\n  token: x\n")
    with pytest.raises(sb.LocalConfigError, match="telegram"):
        sb.load_local_config(path=f, filters=_fresh_filters())


def test_non_mapping_root_raises(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("- juste\n- une liste\n")
    with pytest.raises(sb.LocalConfigError, match="mapping"):
        sb.load_local_config(path=f, filters=_fresh_filters())


def test_require_local_config_refuses_start(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIRE_LOCAL_CONFIG", "1")
    with pytest.raises(sb.LocalConfigError, match="REQUIRE_LOCAL_CONFIG"):
        sb.load_local_config(path=tmp_path / "absent.yml", filters=_fresh_filters())


def test_require_local_config_ok_with_file(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIRE_LOCAL_CONFIG", "1")
    f = tmp_path / "local.yml"
    f.write_text("filters: {}\n")
    filters = _fresh_filters()
    sb.load_local_config(path=f, filters=filters)
    assert filters == sb.FILTERS


def test_la_section_de_la_source_optionnelle_ne_casse_pas_le_demarrage(tmp_path, monkeypatch):
    """
    Epic 13 S2 — l'activation de la source d'export ajoute une section à la config
    locale. Non enregistrée, elle serait refusée comme inconnue et le backend ne
    démarrerait PAS (c'était la dette bloquante du S1). Le module lit sa propre
    section : une clé inconnue y est ignorée, une source optionnelle ne doit pas
    empêcher un démarrage.
    """
    import finviz
    monkeypatch.setitem(finviz.CFG, "export_url", "")
    monkeypatch.setitem(finviz.CFG, "token", "")
    f = tmp_path / "local.yml"
    f.write_text('finviz:\n  export_url: "https://exemple.invalid/export"\n'
                 '  token: "jeton-de-test-sans-valeur"\n  coquille: 1\n'
)
    filters = _fresh_filters()

    sb.load_local_config(path=f, filters=filters)     # ne lève pas

    assert finviz.CFG["token"] and finviz.CFG["export_url"]      # la source est active


def test_les_sections_supprimees_sont_refusees(tmp_path):
    """Epic 15 S2 — non-régression de suppression : les sections des familles purgées
    ne sont plus acceptées (aucun module ne les lit plus)."""
    for section in ("v4", "v5"):
        f = tmp_path / "local.yml"
        f.write_text(f"{section}:\n  price_max: 1.0\n")
        with pytest.raises(sb.LocalConfigError, match=section):
            sb.load_local_config(path=f, filters=_fresh_filters())


def test_la_config_locale_reelle_se_charge():
    """Le config/local.yml réel passe la config du code (sinon le backend ne démarre pas,
    incident du S1). Lancé avec CONFIG_FILE=$PWD/config/local.yml ; sauté sans lui."""
    path = sb.CONFIG_FILE
    if not path.exists():
        pytest.skip(f"{path} absent")
    sb.load_local_config(path=path, filters=_fresh_filters())
