"""
Preuve en conteneur de l'export des résultats terminés (Epic 11 S2) — hors gate.

L'hôte n'a ni fastapi ni accès aux secrets : deux tests de la suite y sont skippés, et
le chemin réseau réel n'y est jamais exercé. Ce script rejoue les deux, puis écrit une
ligne PIRE que réelle dans la vraie table (symbole factice) pour prouver l'aller-retour
complet — écriture, déduplication par interrogation, puis archivage de la ligne posée.

Lancer : docker compose exec -T backend python - < scripts/proof_export.py
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

import requests

import api
import notion_export as nx

FAKE_TICKER = "ZZPREUVE"
ok = True


def check(label, condition):
    global ok
    ok = ok and bool(condition)
    print(f"  [{'OK ' if condition else 'ÉCHEC'}] {label}")


# --- A. Non-régression du contrat servi ------------------------------------
payload = {"scanned_at": "2026-01-05T12:00:00+00:00", "universe_size": 10, "candidates": 1,
           "stocks": [], "rejection_stats": {}, "v4_cohort": [], "v4_note": {},
           "v4_mkt21": None, "v4_prelist": [], "v4_tracking": [], "v5": {"tracking": []},
           "enriched": 1, "display": {}}
api._load_json_cache = lambda: payload
served = asyncio.run(api.get_scan())
print("A. contrat servi")
check(f"jeu de clés identique ({len(served)} clés)", set(served) == set(payload))

# --- B. Non bloquant dans la vraie boucle de scan ---------------------------
print("B. boucle de scan avec un service injoignable")
row = {"ticker": FAKE_TICKER, "window": 7, "entry_date": "2026-01-05", "entry_price": 2.0,
       "phase": "closed", "ret_63": 0.25, "status": {"code": "closed"}}
api.run_scan = lambda wl: {"v4_tracking": [], "v5": {"tracking": [row]}}
api.backup_snapshots = lambda: 0
_post = requests.post
requests.post = lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout("simulé"))
api._run_scan_sync()
requests.post = _post
check("scan abouti malgré l'export en échec", api._cached_data["v5"]["tracking"][0]["ticker"] == FAKE_TICKER)

# --- C. Aller-retour réel contre la table -----------------------------------
print("C. écriture réelle, déduplication réelle, archivage")
tmp = Path(tempfile.mkdtemp())
(tmp / "20260105_120000.json").write_text(json.dumps(
    {"scanned_at": "2026-01-05T12:00:00+00:00",
     "picks": [{"ticker": FAKE_TICKER, "profile": "phenix", "sector": "Biotechnology",
                "dilution_flag": True, "going_concern_flag": False}]}))
result = {"v4_tracking": [], "v5": {"tracking": [row, dict(row, ticker="ZZOUVERTE", phase="open")]}}

check("1re passe : exactement 1 écriture", nx.export_closed_rows(result, tmp) == 1)
check("2e passe : 0 écriture (dédup par interrogation)", nx.export_closed_rows(result, tmp) == 0)

key = os.environ["NOTION_API_KEY"]
db = os.environ["NOTION_RESULTS_DB_ID"]
headers = {"Authorization": f"Bearer {key}", "Notion-Version": "2022-06-28",
           "Content-Type": "application/json"}
pages = requests.post(f"https://api.notion.com/v1/databases/{db}/query",
                      headers=headers, json={"page_size": 100}, timeout=20).json()["results"]
mine = [p for p in pages
        if (p["properties"]["Ticker"]["title"] or [{}])[0].get("plain_text") == FAKE_TICKER]
check(f"1 seule ligne dans la table ({len(mine)} trouvée(s))", len(mine) == 1)

if mine:
    props = mine[0]["properties"]
    def sel(name):
        return (props[name]["select"] or {}).get("name")
    print("   ligne écrite :",
          json.dumps({"Cle": props["Cle"]["rich_text"][0]["plain_text"],
                      "Famille": sel("Famille"),
                      "Profil a l entree": sel("Profil a l entree"),
                      "Statut mesure": sel("Statut mesure"),
                      "Fenetre": props["Fenetre"]["number"],
                      "Prix entree": props["Prix entree"]["number"],
                      "Prix sortie": props["Prix sortie"]["number"],
                      "Rendement": props["Rendement"]["number"],
                      "Secteur": (props["Secteur"]["rich_text"] or [{}])[0].get("plain_text"),
                      "Marqueurs a l entree": [m["name"] for m in props["Marqueurs a l entree"]["multi_select"]],
                      "Verdict": sel("Verdict"),
                      "Note": [t["plain_text"] for t in props["Note"]["rich_text"]]},
                     ensure_ascii=False))
    check("colonnes d'étiquetage manuel vides", sel("Verdict") is None and not props["Note"]["rich_text"])
    check("marqueur d'entrée porté", [m["name"] for m in props["Marqueurs a l entree"]["multi_select"]] == ["Dilution a venir"])
    r = requests.patch(f"https://api.notion.com/v1/pages/{mine[0]['id']}",
                       headers=headers, json={"archived": True}, timeout=20)
    check(f"ligne de preuve archivée ({r.status_code})", r.json().get("archived") is True)

print("\nproof-export", "OK" if ok else "ÉCHEC")
raise SystemExit(0 if ok else 1)
