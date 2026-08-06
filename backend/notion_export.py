"""
Export des lignes de suivi ÉCHUES vers la table de résultats (Epic 11 S2).

Les résultats ne sont aujourd'hui écrits nulle part : ils sont RECALCULÉS à chaque
affichage à partir de prix que le fournisseur réécrit rétroactivement lors des
opérations sur titres — précisément celles que subissent les sociétés en détresse.
Une ligne écrite ici ne bouge plus jamais : c'est un enregistrement, pas un calcul.

Trois propriétés portent tout le sprint :

  - **Seules les fenêtres échues** (`phase == "closed"`) sont écrites. Une ligne en
    cours ne l'est jamais, même si son résultat provisoire est spectaculaire.
  - **La déduplication interroge la table**, jamais un état local : un fichier de clés
    déjà exportées vivrait dans le volume dont on se méfie précisément, et sa perte
    provoquerait un ré-export intégral en doublons. La table est la source de vérité
    de ce qui a déjà été écrit.
  - **Les marqueurs écrits sont ceux de l'instantané d'ENTRÉE**, jamais ceux du scan
    courant. Les rafraîchir reviendrait à relire le passé en connaissant la fin, ce
    qui invaliderait toute comparaison ultérieure entre titres marqués et non marqués.

Rien n'est jamais mis à jour : une ligne présente est sautée, pas réécrite. Les colonnes
d'étiquetage manuel (verdict, note) appartiennent à l'owner et restent vides.

Non bloquant de bout en bout : secret absent, service indisponible, quota atteint ou
expiration ne lèvent jamais vers l'appelant — même contrat que `edgar.py` sans
`EDGAR_USER_AGENT`. Les lignes non exportées le seront au passage suivant, la
déduplication garantissant qu'aucune ne sera doublée.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from screener_backend import HISTORY_DIR

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"
_TIMEOUT = 20

# Les deux blocs de suivi, nommés comme dans l'interface (la table est lue par l'owner).
_MARKET = "Purge de marche"
_QUIET = "Purge silencieuse"

# Marqueurs de détresse archivés dans les instantanés depuis l'Epic 9 S2 → options de la
# colonne multi-choix de la table.
_FLAG_LABELS = {
    "dilution_flag": "Dilution a venir",
    "going_concern_flag": "Doute sur la continuite",
    "reverse_split_flag": "Regroupement d actions",
    "late_filing_flag": "Rapport en retard",
    "sub_dollar_flag": "Cours sous le plancher",
}
_STATUS_LABELS = {"explosion": "Explosion", "crash": "Crash", "closed": "Cloture"}
_PROFILE_LABELS = {"fusee": "Fusee", "phenix": "Phenix", "both": "Fusee et Phenix"}


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Notion-Version": _VERSION,
            "Content-Type": "application/json"}


def _closed_rows(result: dict) -> list[tuple[str, dict]]:
    """(famille, ligne de suivi) pour les seules fenêtres échues des deux blocs."""
    rows = [(_MARKET, r) for r in (result.get("v4_tracking") or [])]
    rows += [(_QUIET, r) for r in ((result.get("v5") or {}).get("tracking") or [])]
    return [(fam, r) for fam, r in rows
            if r.get("phase") == "closed" and r.get("ticker") and r.get("entry_date")]


def _key(family: str, row: dict) -> str:
    """Clé de déduplication : symbole + date d'entrée + fenêtre.

    La famille y entre aussi — le bloc de marché n'a pas de fenêtre d'entrée, et sans
    elle deux lignes du même titre entré le même jour dans les deux blocs porteraient
    la même clé : la seconde serait silencieusement perdue.
    """
    w = row.get("window")
    return f"{row['ticker']}|{row['entry_date']}|{family}|{w if w else '-'}"


def _entry_picks(history_dir: Path, entry_date: str) -> dict[str, dict]:
    """Sélections de l'instantané d'ENTRÉE, par symbole — jamais le scan courant.

    Plusieurs instantanés peuvent porter la même journée (redémarrage du conteneur) :
    le premier gagne, comme partout ailleurs dans le suivi.
    """
    picks: dict[str, dict] = {}
    try:
        files = sorted(Path(history_dir).glob(f"{entry_date.replace('-', '')}_*.json"))
    except Exception:
        return picks
    for f in files:
        try:
            snap = json.loads(f.read_text())
        except Exception:
            continue
        for p in snap.get("picks") or []:
            tk = p.get("ticker")
            if tk:
                picks.setdefault(tk, p)
    return picks


def _properties(family: str, row: dict, pick: dict) -> dict:
    """Composition d'une ligne. `pick` = l'entrée de l'instantané d'entrée, {} si le titre
    n'y figurait pas (les cohortes sont bâties sur le pool tradable complet, bien plus
    large que les sélections consignées) — les colonnes d'entrée restent alors vides."""
    entry_price, ret = row.get("entry_price"), row.get("ret_63")
    props: dict = {
        "Ticker": {"title": [{"text": {"content": row["ticker"]}}]},
        "Cle": {"rich_text": [{"text": {"content": _key(family, row)}}]},
        "Famille": {"select": {"name": family}},
        "Date entree": {"date": {"start": row["entry_date"]}},
        "Prix entree": {"number": entry_price},
        "Rendement": {"number": ret},
        "Marqueurs a l entree": {"multi_select": [
            {"name": label} for flag, label in _FLAG_LABELS.items() if pick.get(flag)]},
    }
    status = _STATUS_LABELS.get(((row.get("status") or {}).get("code")))
    if status:
        props["Statut mesure"] = {"select": {"name": status}}
    if row.get("window"):
        props["Fenetre"] = {"number": row["window"]}
    if entry_price and ret is not None:
        props["Prix sortie"] = {"number": round(entry_price * (1 + ret), 4)}
    if pick:
        props["Profil a l entree"] = {
            "select": {"name": _PROFILE_LABELS.get(pick.get("profile"), "Aucun")}}
        if pick.get("sector"):
            props["Secteur"] = {"rich_text": [{"text": {"content": pick["sector"]}}]}
    return props


def _existing_keys(api_key: str, db_id: str) -> set[str] | None:
    """Clés déjà présentes dans la table, ou None si elle n'a pas pu être lue entièrement.

    None n'est PAS un ensemble vide : sans la source de vérité de la déduplication,
    écrire produirait des doublons impossibles à retirer automatiquement (rien n'est
    jamais mis à jour). L'appelant s'abstient alors et retentera au scan suivant.
    """
    keys: set[str] = set()
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(f"{_API}/databases/{db_id}/query",
                             headers=_headers(api_key), json=body, timeout=_TIMEOUT)
        if resp.status_code != 200:
            print(f"[export] lecture de la table refusée (ignorée) : {resp.status_code}")
            return None
        data = resp.json()
        for page in data.get("results") or []:
            rich = ((page.get("properties") or {}).get("Cle") or {}).get("rich_text") or []
            if rich:
                keys.add(rich[0].get("plain_text") or "")
        if not data.get("has_more"):
            return keys
        cursor = data.get("next_cursor")


def export_closed_rows(result: dict, history_dir: Path = HISTORY_DIR) -> int:
    """Freeze every tracking row whose observation window has elapsed; return how many were written.

    Reads the destination table to know what is already there, so losing the local volume
    can never cause a duplicate re-export. Never raises: a scan must complete even when
    the table cannot be reached, and no secret at all means silently disabled.
    """
    api_key = os.environ.get("NOTION_API_KEY", "").strip()
    db_id = os.environ.get("NOTION_RESULTS_DB_ID", "").strip()
    if not api_key or not db_id:
        return 0                       # secret absent → export désactivé silencieusement

    written = 0
    try:
        rows = _closed_rows(result)
        if not rows:
            return 0                   # aucune fenêtre échue : pas un appel réseau pour rien
        known = _existing_keys(api_key, db_id)
        if known is None:
            return 0
        picks_by_date: dict[str, dict[str, dict]] = {}
        for family, row in rows:
            key = _key(family, row)
            if key in known:
                continue
            date = row["entry_date"]
            if date not in picks_by_date:
                picks_by_date[date] = _entry_picks(history_dir, date)
            pick = picks_by_date[date].get(row["ticker"]) or {}
            resp = requests.post(
                f"{_API}/pages", headers=_headers(api_key), timeout=_TIMEOUT,
                json={"parent": {"database_id": db_id},
                      "properties": _properties(family, row, pick)})
            if resp.status_code >= 300:
                print(f"[export] écriture refusée (ignorée) : {resp.status_code} · {key}")
                continue
            known.add(key)
            written += 1
        if written:
            print(f"[export] {written} ligne(s) figée(s) dans la table de résultats")
    except Exception as e:
        print(f"[export] export impossible (ignoré) : {e}")
    return written
