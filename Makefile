# Entrypoint unique des vérifications de l'epic 6 — chaque sprint ajoute ses cibles.

TEST_ENV = DATA_DIR=/tmp/screener_test PYTHONPATH=backend

.PHONY: test test-config

test:
	$(TEST_ENV) pytest backend/tests/

test-config:
	$(TEST_ENV) pytest backend/tests/test_config.py -v
