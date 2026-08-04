"""
Tests offline de l'overlay de config locale (Epic 6 S1) — aucun réseau.

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_config.py -v
"""
import os
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import copy
import re

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


def test_display_texts_default_to_empty():
    """
    Sans config privée, TOUT texte d'affichage (glossaire, infobulles `tip_*`
    ajoutées à l'Epic 8 S3) vaut chaîne vide : le dépôt public ne porte aucun
    texte citant un seuil. Le frontend masque les blocs vides.
    """
    import v4
    import v5
    for cfg in (v4.CFG, v5.CFG):
        for key, value in cfg["display"]["gloss"].items():
            assert value == "", f"{key} devrait etre vide dans les defaults publics"
    assert "tip_checkpoint" in v4.CFG["display"]["gloss"]
    assert "tip_flash" in v5.CFG["display"]["gloss"]


def test_unknown_v4_key_raises(tmp_path, monkeypatch):
    import v4
    monkeypatch.setattr(v4, "CFG", copy.deepcopy(v4.CFG))
    f = tmp_path / "local.yml"
    f.write_text("v4:\n  price_max_typo: 1.0\n")
    with pytest.raises(sb.LocalConfigError, match="v4.price_max_typo"):
        sb.load_local_config(path=f, filters=_fresh_filters())


# ---------------------------------------------------------------------------
# Mode présentation (Epic 8 S6). Les valeurs utilisées ici sont celles de
# conftest.py — volontairement différentes des valeurs gelées réelles.
# ---------------------------------------------------------------------------

def _scan_payload() -> dict:
    """Réponse de scan de forme complète : bloc d'affichage réel + une entrée de
    cohorte telle que la produit le constructeur (margins comprises)."""
    return {
        "scanned_at": "2026-08-04T12:00:00+00:00",
        "display": sb._display_params(),
        "v4_cohort": [{"ticker": "AAA", "price": 5.0, "change_1m": -0.2,
                       "margins": {"price": 2.0, "change_1m": -0.15}}],
        "stocks": [{"ticker": "AAA", "price": 5.0}],
    }


def _walk(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def test_demo_payload_drops_every_threshold_key():
    """Aucune clé de seuil déclarée ne survit, À AUCUNE PROFONDEUR — c'est la réponse
    sérialisée qui compte, pas ce que le JSX choisit d'afficher."""
    normal = _scan_payload()
    present = {k for _, k, _ in _walk(normal) if k in sb.DEMO_HIDDEN_KEYS}
    assert present, "le payload de test doit porter des clés de seuil, sinon il ne prouve rien"

    demo = sb.demo_payload(normal)
    leaked = [p for p, k, _ in _walk(demo) if k in sb.DEMO_HIDDEN_KEYS]
    assert leaked == []
    # La marge d'un titre reconstituerait le seuil exactement (prix + marge) : elle part
    # avec le reste, alors même que l'écran ne l'affiche pas.
    assert "margins" not in demo["v4_cohort"][0]
    # Ce qui doit rester : calendrier d'observation, fenêtres offertes au choix, résultats.
    assert set(demo["display"]["v4"]["checkpoint"]) == {"day", "horizon"}
    assert set(demo["display"]["v5"]["checkpoint"]) == {"day", "horizon"}
    assert demo["display"]["v5"]["windows"] == list(sb._display_params()["v5"]["windows"])
    assert demo["v4_cohort"][0]["price"] == 5.0


def test_demo_texts_never_cite_a_hidden_value(monkeypatch):
    """
    Non-fuite par les TEXTES — le chemin de fuite principal : les seuils sont écrits en
    toutes lettres au milieu de leur justification. Chaque texte servi en présentation
    est comparé aux valeurs de règle effectivement chargées ; l'une d'elles dans un
    texte fait échouer le test.
    """
    import v4
    monkeypatch.setattr(v4, "CFG", copy.deepcopy(v4.CFG))
    # Texte complet citant le seuil chargé, et sa version expurgée : ce que porte la
    # config privée en production.
    v4.CFG["display"]["gloss"]["rule_price"] = f"Prix ≤ {v4.CFG['price_max']:g} $ : les explosions étaient bon marché."
    v4.CFG["display"]["gloss_demo"]["rule_price"] = "Prix sous un plafond : les explosions étaient bon marché."

    demo = sb.demo_payload(_scan_payload())
    pats = [re.compile(p) for v, unit in sb.hidden_values()
            for p in sb.value_patterns(v, loose=True, unit=unit)]
    assert pats, "aucun seuil chargé : le test ne prouverait rien"

    for fam in ("v4", "v5"):
        for key, text in demo["display"][fam]["gloss"].items():
            assert not any(p.search(text) for p in pats), f"{fam}.gloss.{key} cite un seuil"
    assert demo["display"]["v4"]["gloss"]["rule_price"].startswith("Prix sous un plafond")


def test_demo_empties_a_text_left_without_a_redacted_version(monkeypatch):
    """Filet : un texte citant un seuil dont la version expurgée manque est VIDÉ, jamais
    servi. La config privée n'étant pas versionnée, aucun gate de dépôt ne peut la
    garantir — un oubli doit coûter une explication, pas l'avantage."""
    import v4
    monkeypatch.setattr(v4, "CFG", copy.deepcopy(v4.CFG))
    v4.CFG["display"]["gloss"]["rule_chg"] = f"Chute ≥ {abs(v4.CFG['chg1m_max']) * 100:g} % sur un mois."
    v4.CFG["display"]["gloss_demo"]["rule_chg"] = ""

    demo = sb.demo_payload(_scan_payload())
    assert demo["display"]["v4"]["gloss"]["rule_chg"] == ""


def test_normal_mode_display_keys_unchanged():
    """
    Non-régression du mode normal : le jeu de clés du bloc d'affichage est figé, zéro
    ajoutée, zéro retirée. L'invariant porte sur les CLÉS — les valeurs viennent d'une
    config non versionnée dont le dépôt ne peut pas vérifier l'égalité.
    """
    display = sb._display_params()
    assert set(display) == {"v4", "v5"}
    assert set(display["v4"]) == {"rules", "checkpoint", "depth_scale", "stats", "gloss"}
    assert set(display["v5"]) == {"rules", "checkpoint", "windows", "primary_window",
                                  "stats", "gloss"}
    assert set(display["v4"]["rules"]) == {"price_max", "chg1m_max", "mkt_window"}
    assert set(display["v5"]["rules"]) == {"price_max", "chg_max", "cmf_min", "volcalm_max"}
    assert set(display["v4"]["checkpoint"]) == {"day", "thr", "horizon"}
    assert set(display["v5"]["checkpoint"]) == {"day", "thr", "horizon"}
    # La réserve de textes expurgés ne sort jamais telle quelle : elle remplace `gloss`,
    # elle ne s'y ajoute pas.
    assert "gloss_demo" not in display["v4"] and "gloss_demo" not in display["v5"]
    # Et le mode normal sert bien les valeurs, sans filtrage.
    import v4
    assert display["v4"]["rules"]["price_max"] == v4.CFG["price_max"]


def test_value_patterns_units_and_forms():
    """Le générateur de formes : ce qu'il attrape, ce qu'il laisse passer. Sans lui
    juste, le filet vide des textes de résultat ou en laisse fuiter."""
    pct = [re.compile(p) for p in sb.value_patterns(-0.03, loose=True, unit="%")]
    assert any(p.search("perdu au moins 3 % sur un mois") for p in pct)
    assert any(p.search("chute ≥ 3 %") for p in pct)
    # « 7,3 % » est un résultat mesuré, pas le seuil 3 % : son 3 est une décimale.
    assert not any(p.search("pire cas mesuré : −7,3 %") for p in pct)
    # Un seuil de flux (nombre nu) ne doit pas rougir sur un pourcentage d'indice.
    raw = [re.compile(p) for p in sb.value_patterns(-0.10, loose=True, unit="")]
    assert any(p.search("flux > −0,10") for p in raw)
    assert not any(p.search("l'indice a fait −10 % en trois séances") for p in raw)
    # Forme monétaire, et neutralité des valeurs génériques.
    dollars = [re.compile(p) for p in sb.value_patterns(8.0, loose=True, unit="$")]
    assert any(p.search("prix ≤ 8 $") for p in dollars)
    assert sb.value_patterns(0.0) == set() and sb.value_patterns(1.0) == set()
