#!/usr/bin/env bash
# Gate anti-fuite de l'edge (Epic 6 S2, réduite par l'Epic 15 S2) — sort 0 si propre.
#
# Passe 0 (toujours) : les defaults du backend sont NEUTRES (aucun jeton ni lien
#   d'export dans le code) — on importe les modules sans config et on vérifie.
# Passe 1 (toujours) : aucune référence aux documents d'edge sortis du repo
#   (protocoles privés, exploration) — toutes cibles, backend compris.
# Passe 2 (si config/local.yml présent) : aucune VALEUR privée en clair dans la
#   prose publique (frontend, docs, README…). Patterns DÉRIVÉS de la config
#   locale (scripts/edge_patterns.py) — jamais écrits ici, ce script étant
#   versionné. En CI (sans config), les passes 0 et 1 tournent seules.
#
# site/ (rendu MkDocs, Epic 6 S4) inclus s'il existe — absent = silencieusement
# sauté par grep (2>/dev/null), aucune condition nécessaire ici.
set -u
cd "$(dirname "$0")/.."

ALL_TARGETS=(backend frontend docs README.md Makefile docker-compose.yml site)
PROSE_TARGETS=(frontend docs README.md Makefile docker-compose.yml site scripts deploy)
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
  # Patterns d'abord, dans une variable : lus par une substitution de processus, un
  # plantage de edge_patterns.py passait pour « aucun pattern » et la gate sortait 0.
  if ! pats=$(python3 scripts/edge_patterns.py config/local.yml); then
    echo "INTERDIT — edge_patterns.py a échoué : passe valeurs non jouée"
    fail=1
  fi
  n=0
  while IFS= read -r pat; do
    [ -z "$pat" ] && continue
    n=$((n + 1))
    hits=$(grep -rnE "$pat" "${PROSE_TARGETS[@]}" --exclude-dir=node_modules --exclude-dir=assets --exclude-dir=search 2>/dev/null || true)
    if [ -n "$hits" ]; then
      printf 'INTERDIT — valeur privée en clair (pattern %s) :\n%s\n' "$pat" "$hits"
      fail=1
    fi
  done <<< "${pats:-}"
  echo "passe valeurs : $n pattern(s) dérivé(s) de config/local.yml"
else
  echo "config/local.yml absent — passe valeurs sautée (passes 0 et 1 seules)"
fi

if [ "$fail" -eq 0 ]; then
  echo "check-edge OK"
fi
exit "$fail"
