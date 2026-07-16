#!/usr/bin/env bash
# Gate anti-fuite de l'edge v4/v5 (Epic 6 S2) — sort 0 si propre.
#
# Passe 0 (toujours) : les defaults du backend sont NEUTRES — on parse v4.CFG /
#   v5.CFG / score_weights sans config et on vérifie les valeurs effectives
#   (plus fort qu'un grep : couvre backend/ sans faux positifs).
# Passe 1 (toujours) : aucune référence aux documents d'edge sortis du repo
#   (protocoles v4/v5, exploration v5) — toutes cibles, backend compris.
# Passe 2 (si config/local.yml présent) : aucune VALEUR gelée en clair dans la
#   prose publique (frontend, docs, README…). Patterns DÉRIVÉS de la config
#   locale (scripts/edge_patterns.py) — jamais écrits ici, ce script étant
#   versionné. En CI (sans config), les passes 0 et 1 tournent seules.
#
# Limite connue : les poids entiers de score_weights sont trop génériques pour
# un grep — leur protection est la passe 0 (defaults uniformes).
#
# site/ (rendu MkDocs, Epic 6 S4) inclus s'il existe — absent = silencieusement
# sauté par grep (2>/dev/null), aucune condition nécessaire ici.
set -u
cd "$(dirname "$0")/.."

ALL_TARGETS=(backend frontend docs README.md Makefile docker-compose.yml site)
PROSE_TARGETS=(frontend docs README.md Makefile docker-compose.yml site)
fail=0

python3 scripts/check_neutral_defaults.py || fail=1

for name in backtest_protocol_v4 backtest_protocol_v5 exploration_v5; do
  hits=$(grep -rn "$name" "${ALL_TARGETS[@]}" --exclude-dir=node_modules --exclude-dir=assets --exclude-dir=search 2>/dev/null || true)
  if [ -n "$hits" ]; then
    printf 'INTERDIT — référence à un document privé (%s) :\n%s\n' "$name" "$hits"
    fail=1
  fi
done

if [ -f config/local.yml ]; then
  while IFS= read -r pat; do
    [ -z "$pat" ] && continue
    hits=$(grep -rnE "$pat" "${PROSE_TARGETS[@]}" --exclude-dir=node_modules --exclude-dir=assets --exclude-dir=search 2>/dev/null || true)
    if [ -n "$hits" ]; then
      printf 'INTERDIT — valeur gelée en clair (pattern %s) :\n%s\n' "$pat" "$hits"
      fail=1
    fi
  done < <(python3 scripts/edge_patterns.py config/local.yml)
else
  echo "config/local.yml absent — passe valeurs sautée (passes 0 et 1 seules)"
fi

if [ "$fail" -eq 0 ]; then
  echo "check-edge OK"
fi
exit "$fail"
