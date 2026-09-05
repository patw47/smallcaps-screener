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
# Seuils jamais servis (Epic 8 S6, révisé au S7 : plus de mode, un seul chemin).
# Les valeurs utilisées ici sont celles de conftest.py — volontairement différentes
# des valeurs gelées réelles.
# ---------------------------------------------------------------------------

# Clés qui portent une valeur de seuil et ne doivent jamais atteindre le navigateur.
FORBIDDEN = {"price_max", "chg1m_max", "chg_max", "cmf_min", "volcalm_max",
             "thr", "primary_window", "margins"}


def _scan_payload() -> dict:
    """Réponse de scan de forme complète : bloc d'affichage réel + une entrée de
    cohorte telle que la produit le constructeur."""
    return {
        "scanned_at": "2026-08-04T12:00:00+00:00",
        "display": sb._display_params(),
        "v4_cohort": [{"ticker": "AAA", "price": 5.0, "change_1m": -0.2}],
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


def test_no_threshold_key_is_ever_served():
    """
    Aucune clé de seuil dans la réponse, À AUCUNE PROFONDEUR — c'est la réponse
    sérialisée qui compte, pas ce que le JSX choisit d'afficher. Il n'y a plus de mode :
    ces clés ne sont plus construites, donc plus rien à désactiver par erreur.
    """
    served = _scan_payload()
    leaked = [p for p, k, _ in _walk(served) if k in FORBIDDEN]
    assert leaked == [], f"seuils servis : {leaked}"
    # Ce qui doit rester : calendrier d'observation, fenêtres du sélecteur, résultats.
    assert set(served["display"]["v4"]["checkpoint"]) == {"day", "horizon"}
    assert set(served["display"]["v5"]["checkpoint"]) == {"day", "horizon"}
    assert served["display"]["v5"]["windows"]
    assert served["display"]["v4"]["rules"] == {"mkt_window": v4_mod().CFG["mkt_window"]}
    # La valeur du titre reste visible (décision d'epic) : elle BORNE le plafond sans le
    # donner. `margins`, elle, le redonnait exactement — elle n'est plus produite.
    assert served["v4_cohort"][0]["price"] == 5.0


def test_no_threshold_value_leaks_through_a_served_text():
    """
    Non-fuite par les TEXTES — le chemin de fuite principal : les seuils sont écrits en
    toutes lettres au milieu de leur justification. Chaque texte servi est comparé aux
    valeurs de règle effectivement chargées ; l'une d'elles dans un texte le fait vider.
    """
    import copy as _copy
    v4 = v4_mod()
    cfg = _copy.deepcopy(v4.CFG)
    cfg["display"]["gloss"]["rule_price"] = (
        f"Prix ≤ {cfg['price_max']:g} $ : les explosions étaient bon marché.")
    original, v4.CFG = v4.CFG, cfg
    try:
        served = sb._display_params()
    finally:
        v4.CFG = original

    pats = [re.compile(p) for v, unit in sb.hidden_values()
            for p in sb.value_patterns(v, loose=True, unit=unit)]
    assert pats, "aucun seuil chargé : le test ne prouverait rien"
    for fam in ("v4", "v5"):
        for key, text in served[fam]["gloss"].items():
            assert not any(p.search(text) for p in pats), f"{fam}.gloss.{key} cite un seuil"
    # Le filet vide le texte fautif plutôt que de le servir : une explication manquante
    # coûte moins cher qu'une fuite, et le message nomme la clé.
    assert served["v4"]["gloss"]["rule_price"] == ""


def test_display_key_set_is_frozen():
    """
    Jeu de clés du bloc d'affichage figé : zéro ajoutée, zéro retirée. L'invariant porte
    sur les CLÉS — les valeurs viennent d'une config non versionnée dont le dépôt ne peut
    pas vérifier l'égalité.
    """
    display = sb._display_params()
    assert set(display) == {"v4", "v5"}
    assert set(display["v4"]) == {"rules", "checkpoint", "depth_scale", "stats", "gloss"}
    assert set(display["v5"]) == {"rules", "checkpoint", "windows", "stats", "gloss"}
    assert set(display["v4"]["rules"]) == {"mkt_window"}
    assert display["v5"]["rules"] == {}
    assert set(display["v4"]["checkpoint"]) == {"day", "horizon"}
    assert set(display["v5"]["checkpoint"]) == {"day", "horizon"}
    # La fenêtre de référence est la seule fenêtre dont la valeur réelle soit privée.
    assert "primary_window" not in display["v5"]


def v4_mod():
    import v4
    return v4




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
                 'filters:\n  enrich_source: finviz\n  enrich_max_snapshot: null\n')
    filters = _fresh_filters()

    sb.load_local_config(path=f, filters=filters)     # ne lève pas

    assert finviz.CFG["token"] and finviz.CFG["export_url"]      # la source est active
    assert filters["enrich_source"] == "finviz"
    assert filters["enrich_max_snapshot"] is None                # soupape levée
