"""
Gate de non-régression des instantanés (Epic 9 S2) — sort 0 si propre.

L'artefact est le DERNIER instantané écrit dans l'historique vivant ; l'invariant est le
jeu de clés des objets de sélection : toutes les clés antérieures au sprint, plus
exactement les six nouvelles. Tolérance zéro sur la disparition ou le renommage d'une
clé antérieure — l'historique est la matière première du jugement forward, il se relit
sur des années et personne ne réécrit un instantané a posteriori.

Pourquoi le JEU DE CLÉS et non un différentiel de fichiers : `data/` est exclu du
versionnement et régénéré à chaque scan. Une vérification par différentiel de dépôt
serait vraie par vacuité — verte quoi qu'il arrive, donc incapable de rougir.

Tourne dans le conteneur (`make check-snapshot-keys`) : c'est lui qui porte l'historique
vivant, la copie de l'hôte est figée.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DATA_DIR", "/app/data")

import screener_backend as sb  # noqa: E402

# Clés des objets de sélection AVANT l'Epic 9 S2 (relevées sur `main`, commit 5cdb3c1).
BEFORE: frozenset[str] = frozenset({
    "ticker", "score", "price", "setup_score", "triggered", "days_since_trigger",
    "sector", "accumulation", "compressed", "near_pivot", "rs_strength", "profile",
    "is_fusee", "is_phenix", "fusee_event", "fusee_strength", "phenix_strength",
    "profile_strength",
})

# Les six ajoutées par le sprint : les cinq marqueurs de détresse + le volume en dollars.
ADDED: frozenset[str] = frozenset({
    "sub_dollar_flag", "reverse_split_flag", "dilution_flag", "late_filing_flag",
    "going_concern_flag", "dollar_volume",
})


def _latest_with_picks(history_dir: Path) -> tuple[Path, list[dict]] | None:
    """Instantané le plus récent portant au moins une sélection (un jour à liste vide
    est légitime et ne prouve rien sur le jeu de clés)."""
    for f in sorted(history_dir.glob("*.json"), reverse=True):
        try:
            picks = json.loads(f.read_text()).get("picks") or []
        except Exception:
            continue
        if picks:
            return f, picks
    return None


def main() -> int:
    found = _latest_with_picks(sb.HISTORY_DIR)
    if found is None:
        print(f"check-snapshot-keys ÉCHEC — aucun instantané avec sélection dans {sb.HISTORY_DIR}")
        return 1
    path, picks = found

    expected = BEFORE | ADDED
    missing = sorted(k for p in picks for k in BEFORE - set(p))
    extra = sorted({k for p in picks for k in set(p) - expected})
    absent_new = sorted(k for p in picks for k in ADDED - set(p))

    print(f"[check-snapshot-keys] {path.name} · {len(picks)} sélections · "
          f"{len(BEFORE)} clés antérieures + {len(ADDED)} nouvelles attendues")

    errors = []
    if missing:
        errors.append(f"clé(s) antérieure(s) disparue(s) ou renommée(s) : {', '.join(sorted(set(missing)))}")
    if absent_new:
        errors.append(f"nouvelle(s) clé(s) absente(s) : {', '.join(sorted(set(absent_new)))}")
    if extra:
        errors.append(f"clé(s) inattendue(s) : {', '.join(extra)}")
    if errors:
        print("check-snapshot-keys ÉCHEC :")
        print("\n".join(f"  - {e}" for e in errors))
        return 1
    print("check-snapshot-keys OK (toutes les clés antérieures, plus exactement les six nouvelles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
