# Entrypoint unique des vérifications de l'epic 6 — chaque sprint ajoute ses cibles.

TEST_ENV = DATA_DIR=/tmp/screener_test PYTHONPATH=backend

.PHONY: test test-config check-edge test-invariance

test:
	$(TEST_ENV) pytest backend/tests/

test-config:
	$(TEST_ENV) pytest backend/tests/test_config.py -v

# Gate anti-fuite : aucune valeur gelée v4/v5 ni référence aux protocoles privés
# dans les cibles publiques. Réutilisée en CI au Sprint 4.
check-edge:
	bash scripts/check_edge.sh

# Invariance de l'extraction (S2) : nécessite la vraie config config/local.yml
# et l'historique data/history/ — skip propre sans eux (donc skippé en CI).
test-invariance:
	$(TEST_ENV) CONFIG_FILE=$(CURDIR)/config/local.yml HISTORY_DIR=$(CURDIR)/data/history \
		pytest backend/tests/test_invariance_v5.py -v
