# Glossaire — tous les termes de la page et de l'alerte

Référence unique des termes affichés par la page des alertes et par le message Telegram.
Règle : le libellé reste technique, l'infobulle explique, ce fichier recense tout. Aucune valeur
mesurée ici : elles sont servies à la page depuis la configuration privée (`config/local.yml`).

## Le signal

| Terme | Définition | Source |
|---|---|---|
| **Surprise de résultats (SUE)** | Écart entre le bénéfice par action du trimestre et celui du même trimestre un an plus tôt, divisé par l'écart-type des 8 écarts saisonniers précédents (4 au minimum). Elle mesure « combien ce résultat s'écarte de l'habitude de la société », sans prévision d'analyste. | Bernard & Thomas 1990, *Journal of Accounting and Economics* 13(4) |
| **Quintile (Q5)** | Rang de la surprise parmi toutes les publications du trimestre civil précédent, en 5 groupes égaux. Q5 = le cinquième supérieur ; seul Q5 déclenche une alerte. | — |
| **Dérive après publication (PEAD)** | Le marché réagit trop peu à une surprise de résultats : le cours continue de bouger dans le sens de la surprise pendant des semaines. | Ball & Brown 1968, *JAR* 6(2) ; Bernard & Thomas 1989, *JAR* 27 |
| **8-K, item 2.02** | Dépôt SEC du communiqué de résultats. | SEC |
| **10-Q / 10-K** | Rapport trimestriel / annuel déposé à la SEC ; il porte le bénéfice par action en données XBRL. L'alerte part après ce dépôt. | SEC |
| **Variante B** | Achat après le dépôt du 10-Q / 10-K qui porte le bénéfice par action. Seule variante tradable en temps réel avec des données XBRL. | [backtest_protocol_v6.md](backtest_protocol_v6.md) |
| **Univers (tier)** | Tranche de capitalisation boursière. L'alerte ne couvre que les tiers retenus par l'étude (micro caps) ; les nano caps sont toujours exclues (spread trop large). | — |

## La page

| Terme | Définition |
|---|---|
| **Séance de publication** | Dernière séance close dont les publications sont listées dans « Publications du jour ». |
| **Entrée (ouverture)** | Jour d'achat : ouverture de la séance qui suit le premier cours de clôture public après le dépôt du rapport (règle de 16 h, heure de New York). |
| **Horizon (5 / 21 / 63 séances)** | Nombre de séances de bourse entre l'entrée et la sortie à laquelle on mesure le rendement. |
| **Rendement réalisé** | Rendement simple, brut, de l'ouverture du jour d'entrée à la clôture de la séance d'horizon, cours ajustés des divisions et dividendes. |
| **IWM** | Fonds indiciel des petites capitalisations américaines (Russell 2000), mesuré sur les mêmes dates : le point de comparaison du rendement réalisé. |
| **Écart avec IWM** | Rendement moyen des alertes échues moins rendement moyen d'IWM sur les mêmes dates. |
| **Alertes échues** | Nombre d'alertes dont la séance d'horizon est passée et dont le rendement est écrit : c'est le n de la moyenne. |
| **En attente** | La séance d'horizon n'est pas encore close (ou close ce jour, le job du soir n'a pas tourné). |
| **Sans cours** | La séance d'horizon est passée et aucun cours n'existe (retrait de la cote, cotation suspendue). Compté à part, hors moyenne, car ces cas perdent souvent. |
| **Gain mesuré sur l'historique** | Écart logarithmique avec les titres de même taille et de même volatilité le même jour, net du spread, mesuré sur l'historique du lac de données. Ne se compare pas directement au rendement réalisé. Servi par l'API depuis la configuration privée. |
| **Spread** | Écart entre prix d'achat et prix de vente, coût de l'aller-retour. Estimé par Corwin & Schultz 2012, *Journal of Finance* 67(2). |
| **t ≥ 3** | Seuil de preuve de la règle de décision : un rendement net n'est « prouvé » que si son écart à zéro vaut au moins 3 fois son erreur-type (Harvey, Liu & Zhu 2016, *Review of Financial Studies* 29(1)). |

## Drapeaux de risque (information, aucun filtre)

| Drapeau | Sens | Source |
|---|---|---|
| **Doute sur la continuité** | Le rapport officiel contient le langage « doute important » sur la capacité à poursuivre l'activité. | EDGAR, ASC 205-40 |
| **Émission d'actions en préparation** | Un document préparant l'émission de nouvelles actions a été déposé (dilution du capital). | EDGAR (S-1, S-3, F-1, F-3, 424B) |
| **Rapport en retard** | Le rapport périodique n'a pas été déposé dans les délais et la société l'a déclaré. | EDGAR (NT 10-K, NT 10-Q) |
| **Regroupement d'actions / cours sous le plancher** | Marqueurs issus des cours ; l'alerte n'en porte pas de série de cours, ils n'apparaissent donc pas aujourd'hui. | Cours |

Chaque drapeau a un niveau (élevé, intermédiaire, faible) servi comme donnée ; la page le
traduit. Un drapeau n'écarte jamais une alerte : filtrer sur des traits de risque n'est pas prouvé.
