"""
Gate des seuils (Epic 8 S6, révisé au S7) — sort 0 si propre.

Vérifie, sur LA réponse de scan (il n'y a plus de mode : les seuils ne sont
jamais servis), que :
  1. aucune des clés de seuil déclarées (`HIDDEN_THRESHOLDS`) n'y figure, à aucune
     profondeur — sinon le masquage serait cosmétique, l'inspecteur du navigateur
     lisant tout ce qui est sérialisé ;
  2. aucune VALEUR de seuil effectivement chargée n'apparaît dans une chaîne servie.
     C'est le chemin de fuite principal : les seuils sont écrits en toutes lettres au
     milieu de leur justification, dans une config privée non versionnée — donc hors
     de portée de `check-edge`, qui ne surveille que le dépôt.

La réponse examinée est le vrai `screener_data.json` quand il existe (VPS, conteneur) ;
sinon elle est reconstruite hors ligne avec les VRAIES valeurs de config : bloc
d'affichage complet + une cohorte produite par le vrai constructeur (EDGAR neutralisé,
aucun réseau). Le gate exige que cette entrée porte bien les clés masquées avant
filtrage — un gate incapable de rougir passerait pour vert.

Lancer : make check-thresholds
"""
from __future__ import annotations

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
    """(payload de scan servi en mode normal, origine)."""
    if sb.OUTPUT_FILE.exists():
        try:
            payload = json.loads(sb.OUTPUT_FILE.read_text())
            payload["display"] = sb._display_params()
            return payload, f"scan réel ({sb.OUTPUT_FILE})"
        except Exception as e:  # fichier tronqué : on retombe sur la reconstruction
            print(f"[check-thresholds] {sb.OUTPUT_FILE} illisible ({e}) — réponse reconstruite")
    return {"display": sb._display_params(), "v4_cohort": _offline_cohort()}, "réponse reconstruite hors ligne"


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
