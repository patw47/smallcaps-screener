"""
Gate des seuils (Epic 8 S6, révisé au S7) — sort 0 si propre.

Vérifie, sur LA réponse de scan (il n'y a plus de mode : les seuils ne sont
jamais servis), que :
  1. aucune des clés de seuil déclarées n'y figure, à aucune profondeur — sinon le
     masquage serait cosmétique, l'inspecteur du navigateur lisant tout ce qui est
     sérialisé ;
  2. aucune VALEUR de seuil effectivement chargée n'apparaît dans une chaîne servie.
     C'est le chemin de fuite principal : les seuils sont écrits en toutes lettres au
     milieu de leur justification, dans une config privée non versionnée — donc hors
     de portée de `check-edge`, qui ne surveille que le dépôt ;
  3. `get_scan` recalcule le bloc d'affichage sur chaque chemin qui sert des données.
     Le bloc est écrit dans le cache au moment du scan : sans recalcul, un cache
     antérieur au retrait des seuils continue de les servir pendant des heures, et un
     gate qui n'examine qu'une réponse reconstruite reste vert sur un payload que
     personne ne reçoit. C'est exactement ce trou qui a été trouvé en interrogeant
     l'API réelle après le déploiement.

La réponse examinée est le vrai `screener_data.json` quand il existe (VPS, conteneur),
avec son bloc d'affichage recalculé comme le fait l'API ; sinon elle est reconstruite
hors ligne avec les VRAIES valeurs de config : bloc d'affichage complet + une cohorte
produite par le vrai constructeur (EDGAR neutralisé, aucun réseau).

Lancer : make check-thresholds
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CONFIG_FILE", str(ROOT / "config" / "local.yml"))
os.environ.setdefault("DATA_DIR", str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402

import screener_backend as sb  # noqa: E402
import v4  # noqa: E402


def _offline_cohort() -> list[dict]:
    """Cohorte du jour produite par le vrai constructeur : marché baissier, EDGAR muté
    en « aucune dilution », titres calibrés juste sous les seuils chargés."""
    import edgar
    edgar.survival_signals = lambda ticker, now=None, window_days=None: {"dilution_flag": False}
    idx = pd.bdate_range("2025-01-01", periods=200)
    bench = pd.Series([100 * (0.998 ** i) for i in range(200)], index=idx)
    tradables = [("PROBE", {"price": max(v4.CFG["price_max"] - 1.0, 0.5),
                            "change_1m": v4.CFG["chg1m_max"] - 0.05})]
    cohort, _, _, _ = v4.build_cohort(tradables, {}, bench)
    return cohort


def build_response() -> tuple[dict, str]:
    """
    (payload de scan tel que l'API le sert, origine).

    Le cache disque porte un bloc `display` figé au moment du scan : le servir tel quel
    resservirait les seuils d'avant un changement de configuration pendant des heures.
    L'API le recalcule à chaque réponse (`api._fresh_display`) — ce gate reproduit
    exactement ce chemin, cache compris, plutôt que de reconstruire une réponse idéale
    que personne ne reçoit. C'est un vrai cache servi qui a révélé le trou.
    """
    if sb.OUTPUT_FILE.exists():
        try:
            payload = json.loads(sb.OUTPUT_FILE.read_text())
            stale = payload.get("display")
            payload["display"] = sb._display_params()  # comme l'API
            origine = f"scan réel ({sb.OUTPUT_FILE})"
            if stale is not None:
                origine += " · bloc d'affichage du cache écarté et recalculé"
            return payload, origine
        except Exception as e:  # fichier tronqué : on retombe sur la reconstruction
            print(f"[check-thresholds] {sb.OUTPUT_FILE} illisible ({e}) — réponse reconstruite")
    return {"display": sb._display_params(), "v4_cohort": _offline_cohort()}, "réponse reconstruite hors ligne"


def check_api_recomputes_display() -> list[str]:
    """
    Dans `get_scan`, tout `return` qui sert des données doit passer par le recalcul du
    bloc d'affichage. Sans ça, un cache écrit avant un changement de seuils continue de
    les servir pendant des heures — et un gate qui n'examine qu'une réponse reconstruite
    reste vert sur un payload que personne ne reçoit. C'est ce trou-là qui a été trouvé
    en interrogeant l'API réelle, pas en relisant le code.

    Lecture par AST plutôt que par motif de ligne : `_last_result()` contient un
    `return _cached_data` légitime, qui n'est pas un chemin de réponse.
    """
    src = (ROOT / "backend" / "api.py").read_text(encoding="utf-8")
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "get_scan"), None)
    if fn is None:
        return ["backend/api.py : endpoint get_scan introuvable"]

    errs = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        # Un dict entièrement littéral ne sert aucune donnée de scan (réponse « scan en
        # cours », stocks vide) : rien à recalculer. Dès qu'il déballe une variable
        # (`{**data, …}`, clé None en AST), il sert un payload et doit passer par le
        # recalcul — c'est le chemin stale-while-revalidate.
        if isinstance(node.value, ast.Dict) and all(k is not None for k in node.value.keys):
            continue
        rendu = ast.unparse(node.value)
        if "_fresh_display" not in rendu:
            errs.append(f"chemin de réponse de get_scan sans recalcul du bloc "
                        f"d'affichage : return {rendu[:70]}")
    return errs


def walk(node, path="$"):
    """(chemin, clé, valeur) pour chaque entrée de dict, à toute profondeur."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")


# Noms de clés qui portent une valeur de seuil et ne doivent jamais être servis.
# `thr` = seuil du point de contrôle (son `day` et son `horizon` restent : calendrier).
# `primary_window` = fenêtre de référence. `margins` = distance au seuil, qui ajoutée à
# la valeur du titre le redonne exactement.
FORBIDDEN_KEYS = set(sb.HIDDEN_THRESHOLDS) | {"thr", "primary_window", "margins"}


def main() -> int:
    served, origin = build_response()

    values = sb.hidden_values()
    pats = sorted({p for v, unit in values for p in sb.value_patterns(v, loose=True, unit=unit)})
    compiled = [re.compile(p) for p in pats]

    print(f"[check-thresholds] source : {origin} · {len(values)} seuil(s) chargé(s) · "
          f"{len(pats)} forme(s) d'écriture cherchée(s)")

    errors: list[str] = []
    # Un gate qui ne cherche rien passerait pour vert : sans valeur chargée (defaults
    # neutres), la passe « valeurs dans les textes » ne prouve rien — on le dit.
    if not pats:
        print("[check-thresholds] AUCUNE valeur chargée (defaults neutres) — "
              "la passe « valeurs dans les textes » ne prouve rien ici")

    for path, key, _ in walk(served):
        if key in FORBIDDEN_KEYS:
            errors.append(f"clé de seuil servie : {path}")

    errors.extend(check_api_recomputes_display())

    # Périmètre : les textes de RÈGLE (glossaire). Les chiffres de résultat (espérance,
    # probabilités, test de robustesse) et les valeurs des titres qualifiés restent
    # servis par décision d'epic — les contrôler reviendrait à masquer ce qu'on montre.
    for fam in ("v4", "v5"):
        for key, text in (((served.get("display") or {}).get(fam) or {}).get("gloss") or {}).items():
            if isinstance(text, str) and any(p.search(text) for p in compiled):
                errors.append(f"valeur de seuil citée dans un texte servi : display.{fam}.gloss.{key}")

    # Explications perdues : textes vidés par le filet de `_redact()` faute d'avoir été
    # réécrits sans leur chiffre. Signalé, jamais fatal — un blanc vaut mieux qu'une fuite.
    for fam in ("v4", "v5"):
        shown = ((served.get("display") or {}).get(fam) or {}).get("gloss") or {}
        vides = sorted(k for k, v in shown.items() if v == "")
        if vides:
            print(f"[check-thresholds] textes {fam} vides (à réécrire sans chiffre) : "
                  f"{', '.join(vides)}")

    if errors:
        print("check-thresholds ÉCHEC :")
        print("\n".join(f"  - {e}" for e in errors))
        return 1
    print(f"check-thresholds OK ({len(pats)} formes cherchées, aucune servie)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
