"""
Vérifie que les defaults du code versionné sont NEUTRES : aucun jeton ni lien d'export
Finviz. Plus fort qu'un grep — on importe les modules sans config
locale et on vérifie les valeurs effectives.

Sort 0 si propre. Appelé par scripts/check_edge.sh.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["CONFIG_FILE"] = "/nonexistent/never-loaded.yml"  # defaults purs, jamais l'overlay
os.environ.setdefault("DATA_DIR", "/tmp/screener_test")
os.environ.pop("REQUIRE_LOCAL_CONFIG", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import finviz  # noqa: E402
import screener_backend  # noqa: E402,F401  (la config du code s'importe sans overlay)

errors = [f"finviz.CFG['{k}'] non vide — default non neutre"
          for k in ("export_url", "token") if finviz.CFG[k]]

if errors:
    print("check-neutral-defaults ÉCHEC :")
    print("\n".join(f"  - {e}" for e in errors))
    sys.exit(1)
print("defaults neutres OK")
