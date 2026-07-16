"""
Vérifie que les defaults du code versionné sont NEUTRES (Epic 6 S2) : aucune
valeur gelée v4/v5 ni poids réel dans backend/. Plus fort qu'un grep — on parse
les modules eux-mêmes, sans config locale, et on vérifie les valeurs effectives.

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

import v4  # noqa: E402
import v5  # noqa: E402
import screener_backend as sb  # noqa: E402

NEUTRAL = {0.0, 1.0, -1.0}
errors: list[str] = []

for name, cfg, keys in (
    ("v4", v4.CFG, ("price_max", "chg1m_max", "checkpoint_thr")),
    ("v5", v5.CFG, ("price_max", "chg_max", "cmf_min", "volcalm_max", "flash_thr",
                    "checkpoint_thr")),
):
    for key in keys:
        if cfg[key] not in NEUTRAL:
            errors.append(f"{name}.CFG['{key}'] = {cfg[key]} — default non neutre")
    for stat_block in [cfg["display"]["stats"]] if name == "v4" else cfg["display"]["stats"].values():
        for k, val in stat_block.items():
            if val not in ("", 0):
                errors.append(f"{name}.display.stats.{k} = {val!r} — default non neutre")
    for k, val in cfg["display"]["gloss"].items():
        if val != "":
            errors.append(f"{name}.display.gloss.{k} non vide — default non neutre")

if len(set(sb.FILTERS["score_weights"].values())) != 1:
    errors.append(f"score_weights non uniformes dans le code : {sb.FILTERS['score_weights']}")

if errors:
    print("check-neutral-defaults ÉCHEC :")
    print("\n".join(f"  - {e}" for e in errors))
    sys.exit(1)
print("defaults neutres OK")
