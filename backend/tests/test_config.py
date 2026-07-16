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
    f.write_text("filters:\n  price_min: 3.5\n  score_weights:\n    compression: 9\n")
    filters = _fresh_filters()
    sb.load_local_config(path=f, filters=filters)
    assert filters["price_min"] == 3.5
    assert filters["score_weights"]["compression"] == 9
    # merge PROFOND : les clés sœurs non surchargées survivent
    assert filters["score_weights"]["accumulation"] == sb.FILTERS["score_weights"]["accumulation"]
    assert filters["price_max"] == sb.FILTERS["price_max"]


def test_unknown_filter_key_raises(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("filters:\n  price_mim: 3.5\n")  # typo volontaire
    with pytest.raises(sb.LocalConfigError, match="price_mim"):
        sb.load_local_config(path=f, filters=_fresh_filters())


def test_unknown_nested_key_raises(tmp_path):
    f = tmp_path / "local.yml"
    f.write_text("filters:\n  score_weights:\n    compresion: 9\n")
    with pytest.raises(sb.LocalConfigError, match="score_weights.compresion"):
        sb.load_local_config(path=f, filters=_fresh_filters())


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


def test_v4_v5_sections_merge_into_module_cfg(tmp_path, monkeypatch):
    import v4
    import v5
    monkeypatch.setattr(v4, "CFG", copy.deepcopy(v4.CFG))
    monkeypatch.setattr(v5, "CFG", copy.deepcopy(v5.CFG))
    f = tmp_path / "local.yml"
    f.write_text(
        "v4:\n  price_max: 9.9\n  display:\n    stats:\n      esperance: 'x'\n"
        "v5:\n  flash_thr: -0.5\n"
    )
    filters = _fresh_filters()
    sb.load_local_config(path=f, filters=filters)
    assert v4.CFG["price_max"] == 9.9
    assert v4.CFG["display"]["stats"]["esperance"] == "x"
    # merge PROFOND : les clés sœurs non surchargées survivent
    assert v4.CFG["display"]["stats"]["mediane"] == ""
    assert v5.CFG["flash_thr"] == -0.5
    assert filters == sb.FILTERS


def test_unknown_v4_key_raises(tmp_path, monkeypatch):
    import v4
    monkeypatch.setattr(v4, "CFG", copy.deepcopy(v4.CFG))
    f = tmp_path / "local.yml"
    f.write_text("v4:\n  price_max_typo: 1.0\n")
    with pytest.raises(sb.LocalConfigError, match="v4.price_max_typo"):
        sb.load_local_config(path=f, filters=_fresh_filters())
