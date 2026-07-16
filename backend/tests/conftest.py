"""
Fixtures de config de TEST (Epic 6 S2) — les constantes v4/v5 et les poids de
scoring n'ont plus de valeurs réelles dans le code (defaults neutres, vraies
valeurs dans config/local.yml gitignoré). Les tests tournent avec les valeurs
ci-dessous, volontairement DIFFÉRENTES des valeurs gelées des protocoles : le
repo public ne doit pas les révéler, et `make check-edge` échouerait sinon.

Appliquées une fois à l'import (comme la config au démarrage en production) ;
les assertions dérivent leurs attendus de v4.CFG / v5.CFG, jamais de littéraux.
"""
import os

os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import screener_backend as sb  # noqa: E402
import v4  # noqa: E402
import v5  # noqa: E402

TEST_V4 = {
    "price_max": 7.0,
    "chg1m_max": -0.05,
    "checkpoint_thr": 0.04,
}
TEST_V5 = {
    "price_max": 7.0,
    "chg_max": -0.12,
    "cmf_min": -0.09,
    "volcalm_max": 1.3,
    "flash_thr": -0.07,
    "checkpoint_thr": 0.04,
}
TEST_WEIGHTS = {"accumulation": 3, "insider": 2}  # non uniformes, ≠ valeurs réelles

v4.CFG.update(TEST_V4)
v5.CFG.update(TEST_V5)
sb.FILTERS["score_weights"].update(TEST_WEIGHTS)
