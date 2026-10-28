# Entrypoint unique des vérifications de l'epic 6 — chaque sprint ajoute ses cibles.

TEST_ENV = DATA_DIR=/tmp/screener_test PYTHONPATH=backend

.PHONY: test test-config check-edge i18n-parity check-i18n check-jargon build-frontend docs-build docs-check check-runtime check-secrets test-frontend study-earnings study-earnings-verdict

test:
	$(TEST_ENV) pytest backend/tests/

test-config:
	$(TEST_ENV) pytest backend/tests/test_config.py -v

# Gate anti-fuite : defaults neutres, aucune référence aux protocoles privés, aucune
# valeur privée de config/local.yml dans les cibles publiques.
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

# Syntaxe valide sur le Python de PRODUCTION (3.11), pas seulement sur celui de la
# machine de dev. Une f-string contenant un backslash compile en 3.12 et casse en 3.11 :
# la suite de tests locale passait pendant que le conteneur refusait de démarrer.
check-runtime:
	docker run --rm -v "$(CURDIR)":/src -w /src python:3.11-slim \
		python -m compileall -q backend/ scripts/

# Étanchéité des secrets (Epic 11 S2) : aucune valeur de secret dans les fichiers
# versionnés (valeurs du .env local + motifs de jetons connus), et .env.example porte
# les NOMS des variables Telegram sans leurs valeurs. Tourne sur l'hôte : c'est le
# DÉPÔT qui est jugé, pas l'exécution.
check-secrets:
	python3 scripts/check_secrets.py

# Compilation réelle du frontend, en conteneur : les gates JS ne parsent que du texte,
# seul vite dit si le JSX compile.
# Le nettoyage final efface frontend/node_modules sur l'hôte, donc le point de montage
# du volume anonyme du service frontend : après cette cible, `docker compose up -d
# --force-recreate frontend` pour le remonter (sinon le prochain départ n'a plus de deps).
build-frontend:
	docker run --rm -v "$(CURDIR)/frontend":/app -w /app node:20-alpine \
		sh -c "npm install --silent --no-audit --no-fund >/dev/null 2>&1 && npx vite build"
	docker run --rm -v "$(CURDIR)/frontend":/app -w /app node:20-alpine \
		sh -c "rm -rf node_modules dist package-lock.json"

# Logique JS sans DOM : `node --test`, aucune dépendance à installer — contrairement à
# build-frontend, qui a besoin de Vite. Couvre la logique, pas le rendu de l'écran.
test-frontend:
	node --test frontend/i18n/fmt.test.js

# Docs publiques (S4) : build strict MkDocs Material.
docs-build:
	mkdocs build --strict

# Gate anti-fuite rejouée sur le rendu site/ (nécessite docs-build avant).
docs-check: check-edge

# Étude SUE Q5 réalisable (Epic 15 S1) sur le lac ta-patterns, en LECTURE SEULE : chemin
# dans config/local.yml (study.ta_patterns_dir), sorties dans data/study/ (gitignoré).
# PY = interpréteur du venv Windows de ta-patterns (variable PY de son Makefile) : le lac
# n'est lisible que par lui (pyarrow, norgatedata). -B : aucun __pycache__ écrit dans le lac.
# STEP=cases|net|measure|placebo|verdict pour une étape seule (défaut : toutes, ~14 min).
PY ?= /mnt/c/Users/ACER/ta-venv/Scripts/python.exe
study-earnings:
	cd backend && $(PY) -B -u -m study.earnings --config ../config/local.yml --step $(or $(STEP),all)

# Verdict seul, depuis les sorties de study-earnings (aucune mesure relancée).
study-earnings-verdict:
	cd backend && $(PY) -B -u -m study.earnings --config ../config/local.yml --step verdict
