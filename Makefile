# Entrypoint unique des vérifications de l'epic 6 — chaque sprint ajoute ses cibles.

TEST_ENV = DATA_DIR=/tmp/screener_test PYTHONPATH=backend

.PHONY: test test-config check-edge test-invariance i18n-parity check-i18n check-jargon check-criteria-coverage check-thresholds build-frontend docs-build docs-check check-runtime check-cohort flag-prevalence check-snapshot-keys

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

# Mode présentation (Epic 8 S6) : la réponse servie en présentation ne porte aucune clé
# de seuil, à aucune profondeur, et aucun texte n'y cite une valeur de règle chargée.
# Seul gate qui lit config/local.yml pour juger ce qui SORT (check-edge, lui, juge le
# dépôt) — sans config privée il tourne sur les defaults neutres et le dit.
check-thresholds:
	python3 scripts/check_thresholds.py

# Compilation réelle du frontend, en conteneur (aucun Node ni node_modules requis sur
# l'hôte) : les gates JS ne parsent que du texte, seul vite dit si le JSX compile.
# Syntaxe valide sur le Python de PRODUCTION (3.11), pas seulement sur celui de la
# machine de dev. Une f-string contenant un backslash compile en 3.12 et casse en 3.11 :
# la suite de tests locale passait pendant que le conteneur refusait de démarrer.
check-runtime:
	docker run --rm -v "$(CURDIR)":/src -w /src python:3.11-slim \
		python -m compileall -q backend/ scripts/

# Étanchéité de la cohorte de suivi (Epic 9 S1) : sur les données de suivi COURANTES,
# tout titre en « données absentes » est confirmé sans cotation par un appel isolé.
# Tourne dans le conteneur — c'est lui qui porte l'historique vivant, l'hôte n'en a
# qu'une copie figée ; le script arrive par l'entrée standard (image sans scripts/).
check-cohort:
	docker compose exec -T backend python - < scripts/check_cohort.py

# Prévalence des marqueurs de détresse (Epic 9 S2) : rapport DESCRIPTIF, deux dénominateurs
# distincts (univers pour la couche prix, sélections pour la couche des dépôts) + ventilation
# par secteur, biotechnologie isolée. Réseau et données réelles — donc dans le conteneur,
# script sur l'entrée standard (l'image ne porte pas scripts/).
flag-prevalence:
	docker compose exec -T backend python - < scripts/flag_prevalence.py

# Non-régression des instantanés (Epic 9 S2) : le dernier instantané écrit porte toutes les
# clés de sélection antérieures, plus exactement les six nouvelles. Dans le conteneur : c'est
# lui qui porte l'historique vivant.
check-snapshot-keys:
	docker compose exec -T backend python - < scripts/check_snapshot_keys.py

build-frontend:
	docker run --rm -v "$(CURDIR)/frontend":/app -w /app node:20-alpine \
		sh -c "npm install --silent --no-audit --no-fund >/dev/null 2>&1 && npx vite build"
	docker run --rm -v "$(CURDIR)/frontend":/app -w /app node:20-alpine \
		sh -c "rm -rf node_modules dist package-lock.json"

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
