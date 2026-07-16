#!/usr/bin/env bash
# Purge de l'historique git des documents d'edge v4/v5 (Epic 6 S2).
#
# ⚠️ À EXÉCUTER PAR L'OWNER UNIQUEMENT, APRÈS le merge de la PR S2 :
#   ① vérifier que les trois documents existent dans le vault Obsidian
#      (Memory/smallcaps-screener/) — c'est la seule copie qui restera ;
#   ② lancer ce script sur un clone FRAIS de main ;
#   ③ force-pusher le résultat (action volontairement laissée à la main de
#      l'owner — jamais faite par un agent) ;
#   ④ vérifier : git log --oneline --all -- docs/backtest_protocol_v4.md → vide.
#
# Résiduel accepté (décision d'epic) : les commits purgés restent accessibles
# par SHA via les refs de PR GitHub — le scrub total passe par un ticket
# support GitHub, optionnel, hors scope.
#
# Prérequis : pip install git-filter-repo
set -euo pipefail

if ! command -v git-filter-repo >/dev/null 2>&1 && ! git filter-repo --version >/dev/null 2>&1; then
  echo "git-filter-repo introuvable — pip install git-filter-repo" >&2
  exit 1
fi

echo "Purge des chemins d'edge de TOUT l'historique (destructif, SHAs réécrits)…"
git filter-repo \
  --invert-paths \
  --path docs/backtest_protocol_v4.md \
  --path docs/backtest_protocol_v5.md \
  --path docs/exploration_v5 \
  --force

cat <<'EOF'

Purge locale terminée. Étapes restantes (manuelles, owner) :
  git remote add origin <url-du-repo>   # filter-repo retire le remote par sécurité
  git push --force origin main
Puis vérifier :
  git log --oneline --all -- docs/backtest_protocol_v4.md   # → aucune ligne
  git log --oneline --all -- docs/backtest_protocol_v5.md   # → aucune ligne
  git log --oneline --all -- docs/exploration_v5            # → aucune ligne
Chaque contributeur re-clone ensuite (les anciens clones réintroduiraient l'historique).
EOF
