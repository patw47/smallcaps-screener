# Entrypoint unique des vérifications de l'epic 6 — chaque sprint ajoute ses cibles.

TEST_ENV = DATA_DIR=/tmp/screener_test PYTHONPATH=backend

.PHONY: test test-config check-edge test-invariance i18n-parity check-i18n docs-build docs-check

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
