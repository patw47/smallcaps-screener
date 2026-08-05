# Index de couverture — critères et seuils

Cet index est **public et versionné** : il liste uniquement les **noms de clés** des règles
(Purge de marché, Purge silencieuse, Fusée, Phénix) et des poids de scoring, jamais leurs
valeurs. Les valeurs réelles, leur justification mesurée et leur statut de validation vivent
dans la page de référence, hors dépôt :

**Page de référence** : <https://app.notion.com/p/3b2681d3ae9481ba8890c7ac95ad994e> (Notion privé, accès sur invitation)

Vérifié par `make check-criteria-coverage` (`scripts/check_criteria_coverage.py`) : chaque clé
listée ici doit exister dans les defaults neutres du code (`v4.CFG`, `v5.CFG`,
`FILTERS["profiles"]`, `FILTERS["score_weights"]`, `FILTERS`) — les noms de clés sont publics par
construction (seules leurs valeurs sont secrètes, cf. `v4.py`/`v5.py`), donc rien ci-dessous
n'est une fuite.

## Purge de marché (v4)
- price_max
- chg1m_max
- mkt_window
- beta_window
- beta_min_obs
- checkpoint_day
- checkpoint_thr
- horizon
- prelist_max

## Purge silencieuse (v5)
- price_max
- chg_max
- windows
- cmf_min
- volcalm_max
- volcalm_base
- flash_window
- flash_thr
- checkpoint_day
- checkpoint_thr
- horizon
- prelist_max

## Fusée
- rs63_pctile_min
- perf_1m_pctile_min

## Phénix
- pct_52w_pctile_max
- atr_ratio_pctile_max
- phenix_sma_window

## Poids de scoring
- accumulation
- compression
- near_pivot
- low_ext
- rs_turning
- above_ma
- insider
- cash
- revenue
- low_float
- short

## Sections transverses
- ecarte
- croisement

## Marqueurs de détresse

Mesure DESCRIPTIVE (Epic 9 S2) : ces clés ne sélectionnent, ne classent et ne notent rien.
Elles vivent dans `FILTERS`, pas dans une section de règles — leurs valeurs sont publiques
(la règle de cotation qu'elles reproduisent l'est aussi) et lisibles dans `docs/backend.md`.

- sub_dollar_price
- sub_dollar_min_days
- sub_dollar_window
