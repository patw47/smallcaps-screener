"""
Gate de couverture de l'index des critères (Epic 8 S2) — sort 0 si propre.

Vérifie que docs/criteria-index.md (public, noms de clés seulement) couvre toutes
les clés des sections de règles (v4, v5, Fusée, Phénix) et des poids de scoring,
lues depuis les DEFAULTS NEUTRES du code (jamais config/local.yml — ce script ne
doit rien savoir des valeurs réelles). Vérifie aussi la présence des deux entrées
transverses (« ecarte », « croisement ») exigées par le sprint.

Sort 1 en listant les clés manquantes sinon. Appelé par `make check-criteria-coverage`.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ["CONFIG_FILE"] = "/nonexistent/never-loaded.yml"  # defaults neutres, jamais l'overlay
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")
os.environ.pop("REQUIRE_LOCAL_CONFIG", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import v4  # noqa: E402
import v5  # noqa: E402
import screener_backend as sb  # noqa: E402

INDEX_PATH = Path(__file__).resolve().parents[1] / "docs" / "criteria-index.md"

SECTIONS: dict[str, set[str]] = {
    "Purge de marché (v4)": set(v4.CFG) - {"display"},
    "Purge silencieuse (v5)": set(v5.CFG) - {"display"},
    "Fusée": set(sb.FILTERS["profiles"]["fusee"]),
    "Phénix": set(sb.FILTERS["profiles"]["phenix"]) | {"phenix_sma_window"},
    "Poids de scoring": set(sb.FILTERS["score_weights"]),
    "Sections transverses": {"ecarte", "croisement"},
}


def _parse_index(text: str) -> dict[str, set[str]]:
    """{titre de section: clés listées} — sections = titres `## `, clés = puces `- key`."""
    found: dict[str, set[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        header = re.match(r"^##\s+(.+?)\s*$", line)
        if header:
            current = header.group(1)
            found.setdefault(current, set())
            continue
        bullet = re.match(r"^-\s+`?([A-Za-z0-9_]+)`?", line)
        if bullet and current is not None:
            found[current].add(bullet.group(1))
    return found


def main() -> int:
    if not INDEX_PATH.exists():
        print(f"{INDEX_PATH} absent")
        return 1
    found = _parse_index(INDEX_PATH.read_text())
    missing = [f"{section}: {key}"
               for section, expected in SECTIONS.items()
               for key in sorted(expected - found.get(section, set()))]
    if missing:
        print("check-criteria-coverage ÉCHEC — clés manquantes de docs/criteria-index.md :")
        print("\n".join(f"  - {m}" for m in missing))
        return 1
    print("check-criteria-coverage OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
