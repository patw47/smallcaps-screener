"""
Tests OFFLINE du client d'export Finviz (Epic 13 S1) — aucun appel réseau réel :
`finviz.requests` est remplacé par une doublure qui journalise et refuse, et la seule
sortie réseau du module (`finviz._get`) est doublée sur une fixture CSV enregistrée.

Fixture (backend/tests/fixtures/finviz/export.csv) — 4 lignes :
  AAAA : NASDAQ, toutes les cellules renseignées
  BBBB : NYSE, cellules vides ou « - », date de résultats sans année
  CCCC : AMEX — place HORS des places autorisées, capitaux propres NÉGATIFS (Epic 14 S1)
  DDDD : place absente de la table de correspondance, colonnes de contexte vides

Le jeton et le lien d'export utilisés ici sont FACTICES, distincts de toute valeur
d'exploitation (même règle que les constantes de conftest.py).

Lancer : DATA_DIR=/tmp/screener_test PYTHONPATH=backend pytest backend/tests/test_finviz.py -v
"""
import inspect
import os
import re
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

from datetime import datetime, timezone
from pathlib import Path

import pytest

import finviz
import screener_backend as sb
from screener_backend import FILTERS, _days_to_earnings, _is_binary_event_sector

FIXTURE = Path(__file__).parent / "fixtures" / "finviz" / "export.csv"

TEST_URL = "https://exemple.invalid/export.ashx?v=152"
TEST_TOKEN = "jeton-de-test-sans-valeur"


@pytest.fixture(autouse=True)
def reseau_interdit(monkeypatch):
    """Journal des appels réseau RÉELS — doit rester vide dans toute la suite."""
    journal = []

    class _Bloque:
        @staticmethod
        def get(url, **kwargs):
            journal.append(url)
            raise AssertionError("appel réseau réel dans un test offline")

    monkeypatch.setattr(finviz, "requests", _Bloque)
    return journal


@pytest.fixture(autouse=True)
def config_neutre(monkeypatch):
    """
    Défauts NEUTRES avant chaque test : la config locale de la machine (ou du conteneur)
    ne doit jamais décider du résultat d'un test.
    """
    monkeypatch.setitem(finviz.CFG, "export_url", "")
    monkeypatch.setitem(finviz.CFG, "token", "")
    monkeypatch.setattr(finviz, "_BACKOFF_S", 0.0)     # retries sans attente en test


@pytest.fixture
def actif(monkeypatch):
    monkeypatch.setitem(finviz.CFG, "export_url", TEST_URL)
    monkeypatch.setitem(finviz.CFG, "token", TEST_TOKEN)


@pytest.fixture
def export_log(monkeypatch):
    """Doublure de la sortie réseau : journalise l'URL demandée, sert la fixture."""
    journal = []

    def faux_get(url):
        journal.append(url)
        return FIXTURE.read_text()

    monkeypatch.setattr(finviz, "_get", faux_get)
    return journal


# Contrat d'enrichissement, ÉNONCÉ ICI et pas dérivé de finviz.FIELD_MAP : un verrou
# qui se recopie sur le module qu'il surveille ne verrouille rien. Ce sont les champs
# que `enrich_ticker` lit dans le `.info` (les deux dates de résultats passent par
# `_days_to_earnings`, secteur et industrie aussi par `_is_binary_event_sector`).
CONTRAT = {
    "shortName", "longName", "sector", "industry", "exchange", "marketCap",
    "floatShares", "shortPercentOfFloat", "heldPercentInsiders", "revenueGrowth",
    "earningsTimestampStart", "earningsTimestamp", "firstTradeDateEpochUtc",
    "totalCash", "totalDebt",
    # Bloc de contexte (Epic 14 S1) : seule clé de l'instantané qui ne soit pas un champ
    # `.info` — l'enrichissement la lit comme les autres, donc le garde-fou de dérive la
    # veut ici. Son CONTENU est verrouillé à part (CONTEXTE ci-dessous).
    "context_flags",
}

# Clés du bloc de contexte, ÉNONCÉES ICI et pas dérivées de `finviz.CONTEXT_KEYS`, même
# raison que ci-dessus : un verrou recopié sur le module qu'il surveille ne verrouille rien.
CONTEXTE = {
    "insider_transactions", "institutional_ownership", "institutional_transactions",
    "short_float", "short_ratio", "eps_surprise", "revenue_surprise",
    "optionable", "shortable",
}


# --- Parsing : N lignes → N dictionnaires portant tout le contrat ------------

def test_le_contrat_couvre_les_champs_lus_par_l_enrichissement():
    """Garde-fou de dérive : un champ `.info` ajouté à l'enrichissement doit être ici."""
    src = inspect.getsource(sb)
    lus = set(re.findall(r'\binfo\.get\(\s*"(\w+)"', src))

    # Angle mort comblé (dette Epic 13) : les accès par VARIABLE — `info.get(v)` nourri
    # par une boucle `for v in ("a", "b")` — échappaient au motif littéral ci-dessus.
    variables = set(re.findall(r'\binfo\.get\(\s*([a-z_]\w*)\s*[,)]', src))
    assert variables, "aucun accès par variable trouvé — la branche serait morte"
    for var in variables:
        for tup in re.findall(rf'\bfor\s+{var}\s+in\s+\(([^)]*)\)', src):
            lus |= set(re.findall(r'"(\w+)"', tup))

    assert lus, "aucun champ lu trouvé — le garde-fou serait vide, donc mort"
    assert lus <= CONTRAT, f"champs lus par l'enrichissement et hors du contrat : {lus - CONTRAT}"


def test_la_fixture_rend_un_dict_par_ticker_avec_tout_le_contrat(reseau_interdit):
    instantane = finviz._parse(FIXTURE.read_text())

    assert set(instantane) == {"AAAA", "BBBB", "CCCC", "DDDD"}
    for ticker, champs in instantane.items():
        assert set(champs) == CONTRAT, f"{ticker} : contrat incomplet"
    assert reseau_interdit == []


def test_les_champs_sans_equivalent_sont_neutres(reseau_interdit):
    champs = finviz._parse(FIXTURE.read_text())["AAAA"]

    assert all(champs[cle] is None for cle in finviz.UNMAPPED)
    assert reseau_interdit == []


# --- Normalisation : mêmes unités et types que le contrat actuel -------------

def test_pourcentages_capitalisations_et_dates_en_unites_du_contrat(reseau_interdit):
    champs = finviz._parse(FIXTURE.read_text())["AAAA"]

    # Capitalisation à suffixe → dollars absolus, comme `marketCap` du contrat
    assert champs["marketCap"] == pytest.approx(412.50e6)
    assert champs["floatShares"] == pytest.approx(12.40e6)
    # Pourcentages texte → FRACTIONS, comme `shortPercentOfFloat` / `heldPercentInsiders`
    assert champs["shortPercentOfFloat"] == pytest.approx(0.0345)
    assert champs["heldPercentInsiders"] == pytest.approx(0.0720)
    assert champs["revenueGrowth"] == pytest.approx(0.2350)

    # Dates → epoch UTC : les CONSOMMATEURS du contrat les relisent sans rien savoir
    # de Finviz — c'est la preuve d'unité la plus forte disponible.
    jours, date_iso = _days_to_earnings(champs, now=datetime(2026, 2, 15, tzinfo=timezone.utc))
    assert (jours, date_iso) == (10, "2026-02-25")
    assert datetime.fromtimestamp(champs["firstTradeDateEpochUtc"], tz=timezone.utc).year == 2021

    # Secteur / industrie : lus tels quels par le détecteur de secteur à évènements binaires
    assert _is_binary_event_sector(finviz._parse(FIXTURE.read_text())["BBBB"]) is True
    assert reseau_interdit == []


def test_une_croissance_negative_garde_son_signe(reseau_interdit):
    assert finviz._parse(FIXTURE.read_text())["CCCC"]["revenueGrowth"] == pytest.approx(-0.0420)
    assert reseau_interdit == []


def test_cellule_vide_ou_tiret_rend_none_sans_exception(reseau_interdit):
    instantane = finviz._parse(FIXTURE.read_text())

    tiret = instantane["BBBB"]        # cellules « - »
    assert tiret["shortName"] == "Beta Biopharma Corp"
    assert all(tiret[cle] is None for cle in
               ("marketCap", "floatShares", "shortPercentOfFloat",
                "heldPercentInsiders", "revenueGrowth", "firstTradeDateEpochUtc"))

    vide = instantane["DDDD"]         # cellules vides en fin de ligne
    assert vide["marketCap"] == pytest.approx(1.05e9)
    assert vide["shortPercentOfFloat"] is None
    assert vide["earningsTimestampStart"] is None
    assert reseau_interdit == []


def test_une_date_de_resultats_sans_annee_reste_lisible(reseau_interdit):
    epoch = finviz._parse(FIXTURE.read_text())["BBBB"]["earningsTimestampStart"]

    quand = datetime.fromtimestamp(epoch, tz=timezone.utc)
    assert (quand.month, quand.day) == (2, 25)
    assert reseau_interdit == []


# --- Bloc de contexte (Epic 14 S1) -------------------------------------------

def test_chaque_ticker_porte_tout_le_bloc_de_contexte(reseau_interdit):
    for ticker, champs in finviz._parse(FIXTURE.read_text()).items():
        assert set(champs["context_flags"]) == CONTEXTE, f"{ticker} : bloc incomplet"
    assert reseau_interdit == []


def test_les_familles_de_format_du_contexte_arrivent_aux_bonnes_unites(reseau_interdit):
    instantane = finviz._parse(FIXTURE.read_text())
    plein = instantane["AAAA"]["context_flags"]
    autre = instantane["CCCC"]["context_flags"]

    # Pourcentage SIGNÉ → fraction, signe compris
    assert plein["insider_transactions"] == pytest.approx(0.1250)
    assert plein["institutional_transactions"] == pytest.approx(-0.0310)
    assert autre["insider_transactions"] == pytest.approx(-0.0680)
    # Un zéro n'est pas une absence : il traverse comme un nombre.
    assert autre["institutional_transactions"] == 0.0

    # Yes/No → BOOLÉEN, pas la chaîne — « No » est vrai tant qu'il reste du texte.
    assert plein["optionable"] is True
    assert autre["optionable"] is False

    # Ratio décimal → nombre tel quel : ni division par cent, ni suffixe de magnitude.
    assert plein["short_ratio"] == pytest.approx(2.60)

    # Le short flottant du bloc est le MÊME que celui du contrat : le bloc se lit seul,
    # sans que l'UI ait à croiser deux endroits pour décrire une mécanique de squeeze.
    assert plein["short_float"] == instantane["AAAA"]["shortPercentOfFloat"]
    assert reseau_interdit == []


def test_un_contexte_vide_ou_tiret_rend_none_sans_exception(reseau_interdit):
    instantane = finviz._parse(FIXTURE.read_text())

    assert all(v is None for v in instantane["BBBB"]["context_flags"].values())   # « - »

    vide = instantane["DDDD"]["context_flags"]                                    # cellules vides
    assert all(vide[cle] is None for cle in
               ("insider_transactions", "institutional_ownership",
                "institutional_transactions", "short_float", "short_ratio",
                "eps_surprise", "revenue_surprise"))
    # Une cellule RENSEIGNÉE de la même ligne garde sa valeur : l'absence n'est pas contagieuse.
    assert vide["optionable"] is False and vide["shortable"] is True
    assert reseau_interdit == []


# --- Reconstruction du bilan et parité du verdict cash (Epic 14 S1) ----------

@pytest.fixture
def depots_muets(monkeypatch):
    """
    Dépôts officiels muets, jitter nul : `enrich_ticker` interroge EDGAR (insiders, survie)
    et attend avant un appel `.info`. Ni l'un ni l'autre n'est le sujet ici, et la suite
    est HORS LIGNE.
    """
    import edgar
    monkeypatch.setattr(edgar, "net_insider_buying", lambda *a, **k: None)
    monkeypatch.setattr(edgar, "survival_signals", lambda *a, **k: None)
    monkeypatch.setitem(sb.FILTERS, "enrich_jitter_s", 0)


def test_la_tresorerie_et_la_dette_se_reconstruisent_par_action(reseau_interdit):
    champs = finviz._parse(FIXTURE.read_text())["AAAA"]

    # Attendus recalculés depuis les CELLULES de la fixture — jamais depuis le module.
    actions = 20.00 * 1e6
    assert champs["totalCash"] == pytest.approx(2.50 * actions)
    assert champs["totalDebt"] == pytest.approx(0.50 * (4.00 * actions))
    assert reseau_interdit == []


def test_un_facteur_de_reconstruction_manquant_rend_none(reseau_interdit):
    instantane = finviz._parse(FIXTURE.read_text())

    # BBBB : toutes les colonnes par action valent « - ».
    assert instantane["BBBB"]["totalCash"] is None
    assert instantane["BBBB"]["totalDebt"] is None

    # CCCC : capitaux propres NÉGATIFS. Multipliés, ils rendraient une dette négative,
    # donc un bilan faussement sain — le cas le plus dangereux du lot. La trésorerie,
    # elle, reste lisible : l'absence est ciblée, pas globale.
    assert instantane["CCCC"]["totalCash"] == pytest.approx(0.30 * 30.00 * 1e6)
    assert instantane["CCCC"]["totalDebt"] is None
    assert reseau_interdit == []


def test_le_verdict_cash_est_le_meme_par_les_deux_sources(monkeypatch, depots_muets,
                                                          reseau_interdit):
    """
    Parité inter-sources : à valeurs sous-jacentes ÉGALES, le critère cash rend le même
    verdict que les fondamentaux viennent de Yahoo ou de l'instantané d'export. C'était
    faux avant ce sprint — l'export ne servant pas les valeurs absolues du bilan, la même
    entreprise valait None par un chemin et True par l'autre.
    """
    actions = 20.00 * 1e6      # colonnes par action de la ligne AAAA de la fixture
    yahoo = {"exchange": "NMS", "marketCap": 412.50e6, "shortName": "Alpha Alloys Inc",
             "totalCash": 2.50 * actions, "totalDebt": 0.50 * (4.00 * actions)}
    monkeypatch.setattr(sb, "_fetch_info", lambda tk: yahoo)

    par_yahoo, motif_y = sb.enrich_ticker("AAAA", {})                     # chemin `.info`
    par_finviz, motif_f = sb.enrich_ticker("AAAA", {},
                                           finviz._parse(FIXTURE.read_text())["AAAA"])

    assert (motif_y, motif_f) == ("ok", "ok")
    assert par_yahoo["cash_positive"] is True      # sans quoi la parité serait vide de sens
    assert par_finviz["cash_positive"] == par_yahoo["cash_positive"]
    assert par_finviz["cash_bin"] == par_yahoo["cash_bin"]
    assert reseau_interdit == []


def test_un_bilan_illisible_rend_un_verdict_neutre_sans_exception(depots_muets,
                                                                  reseau_interdit):
    """Facteur manquant → None neutre jusque dans le candidat servi, jamais une exception."""
    sans_bilan = dict(finviz._parse(FIXTURE.read_text())["AAAA"],
                      totalCash=None, totalDebt=None)

    stock, motif = sb.enrich_ticker("AAAA", {}, sans_bilan)

    assert motif == "ok"
    assert stock["cash_positive"] is None and stock["cash_bin"] is None
    assert reseau_interdit == []


def test_le_bloc_de_contexte_existe_aussi_sur_le_chemin_yahoo(monkeypatch, depots_muets,
                                                              reseau_interdit):
    """Forme stable des deux côtés : sur le chemin `.info`, le bloc est là, tout à None."""
    monkeypatch.setattr(sb, "_fetch_info",
                        lambda tk: {"exchange": "NMS", "marketCap": 300e6, "shortName": tk})

    stock, motif = sb.enrich_ticker("ZZZZ", {})

    assert motif == "ok"
    assert set(stock["context_flags"]) == CONTEXTE
    assert all(v is None for v in stock["context_flags"].values())
    assert reseau_interdit == []


# --- Traduction des places de cotation ---------------------------------------

def test_les_places_passent_par_la_table_pas_par_la_chaine_brute(reseau_interdit):
    instantane = finviz._parse(FIXTURE.read_text())

    # Les noms Finviz ne sont JAMAIS des codes de place autorisés : sans traduction,
    # tout l'univers serait rejeté.
    assert not {"NASDAQ", "NYSE", "AMEX"} & set(FILTERS["allowed_exchanges"])

    assert instantane["AAAA"]["exchange"] == finviz.EXCHANGES["NASDAQ"]
    assert instantane["AAAA"]["exchange"] in FILTERS["allowed_exchanges"]        # acceptable

    assert instantane["CCCC"]["exchange"] == finviz.EXCHANGES["AMEX"]
    assert instantane["CCCC"]["exchange"] not in FILTERS["allowed_exchanges"]    # rejetable

    assert instantane["DDDD"]["exchange"] is None                                # rejetable
    assert reseau_interdit == []


# --- Module inactif, erreurs réseau -----------------------------------------

def test_sans_section_finviz_le_module_est_inactif(tmp_path, export_log, reseau_interdit):
    config = tmp_path / "local.yml"
    config.write_text("filters:\n  enrich_max: 3\n")
    finviz.load_config(config)

    assert finviz.CFG == {"export_url": "", "token": ""}
    assert finviz.snapshot() is None
    assert export_log == []
    assert reseau_interdit == []


def test_une_config_absente_laisse_les_defauts_neutres(tmp_path, export_log):
    finviz.load_config(tmp_path / "jamais-ecrit.yml")

    assert finviz.snapshot() is None
    assert export_log == []


def test_la_section_locale_active_le_module(tmp_path, export_log, reseau_interdit):
    config = tmp_path / "local.yml"
    config.write_text(f'finviz:\n  export_url: "{TEST_URL}"\n  token: "{TEST_TOKEN}"\n')
    finviz.load_config(config)

    instantane = finviz.snapshot()

    assert set(instantane) == {"AAAA", "BBBB", "CCCC", "DDDD"}
    assert len(export_log) == 1
    assert export_log[0].startswith(TEST_URL)
    assert f"auth={TEST_TOKEN}" in export_log[0]
    assert reseau_interdit == []


def test_une_erreur_reseau_rend_none_apres_retries(monkeypatch, actif, reseau_interdit):
    journal = []

    def get_qui_leve(url):
        journal.append(url)
        raise ConnectionError(f"connexion refusée pour {url}")

    monkeypatch.setattr(finviz, "_get", get_qui_leve)

    assert finviz.snapshot() is None                 # aucune exception ne remonte
    assert len(journal) == finviz._RETRIES + 1
    assert reseau_interdit == []


def test_un_export_vide_rend_none_apres_retries(monkeypatch, actif):
    journal = []
    monkeypatch.setattr(finviz, "_get", lambda url: journal.append(url))

    assert finviz.snapshot() is None
    assert len(journal) == finviz._RETRIES + 1


def test_un_csv_illisible_rend_none_sans_exception(monkeypatch, actif):
    monkeypatch.setattr(finviz, "_get", lambda url: "\x00 pas un csv \x00")

    assert finviz.snapshot() in (None, {})


def test_le_jeton_ne_fuit_ni_dans_le_journal_ni_dans_les_erreurs(monkeypatch, actif, capsys):
    def get_qui_leve(url):
        raise ConnectionError(f"HTTPSConnectionPool: échec sur {url}")   # comme `requests`

    monkeypatch.setattr(finviz, "_get", get_qui_leve)

    assert finviz.snapshot() is None
    sortie = capsys.readouterr()
    assert TEST_TOKEN not in sortie.out + sortie.err
    assert "ConnectionError" in sortie.out
