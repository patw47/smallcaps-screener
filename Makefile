# Entrypoint unique des vérifications de l'epic 6 — chaque sprint ajoute ses cibles.

TEST_ENV = DATA_DIR=/tmp/screener_test PYTHONPATH=backend

.PHONY: test test-config check-edge test-invariance i18n-parity check-i18n check-jargon check-criteria-coverage docs-build docs-check

test:
	$(TEST_ENV) pytest backend/tests/

test-config:
	$(TEST_ENV) pytest backend/tests/test_config.py -v

# Gate anti-fuite : aucune valeur gelée v4/v5 ni référence aux protocoles privés
# dans les cibles publiques. Réutilisée en CI au Sprint 4.
check-edge:
	bash scripts/check_edge.sh

# i18n (S3) : parité stricte des clés fr/en + zéro chaîne UI en dur dans le JSX.
i18n-parity:
	node frontend/i18n/check-parity.mjs

check-i18n:
	node scripts/check_i18n.mjs

# Jargon (Epic 8 S1, liste complétée au S3) : ni numéro de version de famille, ni
# « cohorte », « protocole », référence de section, numéro de validation, « repo »,
# « in-sample », « résidu » ou acronyme de flux d'argent — dans les dictionnaires
# i18n comme dans les chaînes littérales du JSX.
check-jargon:
	node scripts/check_jargon.mjs

# Couverture de l'index des critères (Epic 8 S2) : chaque clé des defaults
# neutres v4/v5/profils/poids figure dans docs/criteria-index.md.
check-criteria-coverage:
	python3 scripts/check_criteria_coverage.py

# Invariance de l'extraction (S2) : nécessite la vraie config config/local.yml
# et l'historique data/history/ — skip propre sans eux (donc skippé en CI).
test-invariance:
	$(TEST_ENV) CONFIG_FILE=$(CURDIR)/config/local.yml HISTORY_DIR=$(CURDIR)/data/history \
		pytest backend/tests/test_invariance_v5.py -v

# Docs publiques (S4) : build strict MkDocs Material.
docs-build:
	mkdocs build --strict

# Gate anti-fuite rejouée sur le rendu site/ (nécessite docs-build avant).
docs-check: check-edge
