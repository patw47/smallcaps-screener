"""
Dérive les patterns grep (ERE) des valeurs gelées v4/v5 depuis la config locale.

Utilisé par scripts/check_edge.sh sur les cibles PROSE (frontend, docs, README) :
les valeurs ne sont JAMAIS écrites en dur dans un fichier versionné — elles sont
lues de config/local.yml au moment du check. Formes émises, par valeur :
  - virgule française :        « 0,15 » / « −0,15 »
  - pourcentage comparé :      « ≥ 15 % », « −15 % »
  - multiplicateur :           « 1,25× »
  - monétaire comparé (int) :  « ≤ 8 $ »
Les décimales à point nues (0.15…) ne sont pas émises : trop génériques (faux
positifs massifs) — le backend est couvert par check_neutral_defaults.py.
Les clés structurelles (fenêtres, horizons…) sont ignorées.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

os.environ.setdefault("CONFIG_FILE", "/nonexistent/never-loaded.yml")  # jamais d'overlay ici
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from screener_backend import value_patterns  # noqa: E402  (source unique des formes)

SKIP_KEYS = {
    "windows", "mkt_window", "beta_window", "beta_min_obs", "volcalm_base",
    "flash_window", "checkpoint_day", "horizon", "prelist_max",
    "primary_window", "display", "n",
}
GENERIC = {0.0, 1.0, -1.0}


def _walk(node: object):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SKIP_KEYS:
                continue
            yield from _walk(value)
    elif isinstance(node, float) and node not in GENERIC:
        yield node


def patterns(config_path: Path) -> list[str]:
    raw = yaml.safe_load(config_path.read_text()) or {}
    pats: set[str] = set()
    for section in ("v4", "v5"):
        for value in _walk(raw.get(section) or {}):
            pats |= value_patterns(value)
    return sorted(pats)


if __name__ == "__main__":
    for p in patterns(Path(sys.argv[1])):
        print(p)
