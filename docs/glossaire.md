# Glossaire — tous les termes affichés par le screener

Référence unique des labels techniques de l'interface. Règle d'or (S3) : **le label reste
technique, l'infobulle explique, ce fichier recense tout** — même contenu que les infobulles,
avec les chiffres sources. Chaque chiffre cité provient d'une table gelée :
`docs/backtest_protocol_v4.md` Annexe A (v4) ou `docs/backtest_protocol_v2.md` §9 (profils).

## Marché & cadre

| Terme | Définition | Chiffre source |
|---|---|---|
| **IWM** | ETF qui suit le Russell 2000, l'indice des petites capitalisations US. Notre thermomètre « marché ». | — |
| **IWM 21 j** | Variation d'IWM sur les 21 dernières séances (~1 mois de bourse). Négatif = marché baissier → la méthode v4 s'applique ; positif = elle se met en pause. | Règle §2.4 ; combo +5,9 % en marché baissier vs +0,4 % en haussier (A.3) |
| **Univers tradable** | Les ~2 500 small/micro caps US (NASDAQ, NYSE, AMEX) qui passent les filtres durs de liquidité/prix — ce qu'on peut réellement acheter sans être coincé. | — |
| **fwd63** | Rendement du titre 63 jours de bourse (~3 mois calendaires) après la date d'observation. L'horizon de jugement de tous les protocoles. | — |
| **Espérance nette** | Gain/perte MOYEN par titre à l'horizon fwd63, coût d'aller-retour de 1 % déduit. Moyenne tirée par les rares gros gagnants : toujours comparer à la médiane. | Cohorte v4 : +5,9 % (méd. +1,6 %) — A.3 |
| **Taux de base** | La fréquence « au hasard » qui sert de référence : P(+100 %) = 0,82 %, P(≤−50 %) = 3,77 % dans l'univers tradable. | A.3 |
| **t-stat / « non significatif »** | Test statistique : le résultat est-il distinguable de la chance ? Unité indépendante = le trimestre (les titres d'un même jour vivent le même marché). Il faut t ≥ 2 ; la cohorte v4 est à **t = 0,47** → le +5,9 % peut être du bruit. D'où la validation forward. | A.3 |
| **Validation forward (« Validation C »)** | Le seul juge encore recevable : les cohortes enregistrées chaque jour à partir du 6 juillet 2026, jugées sur leurs résultats réels (critères pré-écrits, première lecture ≥ 12 mois). Sans biais de survie : les faillites seront vues en direct. | Protocole v4 §4 |
| **Biais de survie / plafond optimiste** | Nos données historiques ne contiennent que les entreprises encore cotées : les faillites ont disparu des calculs. Tout chiffre historique est donc une borne haute. | Protocole §2 (v3/v4) |

## Cohorte v4 (les 4 règles gelées + champs)

| Terme | Définition | Chiffre source |
|---|---|---|
| **Cohorte v4** | Les titres du jour qui passent les 4 règles gelées du protocole signé. Seul groupe mesuré à espérance historique positive. Enregistrée chaque jour pour le jugement forward. | A.3 |
| **Règles gelées** | prix ≤ 8 $ · dilution : aucune · chute 1 mois ≤ −3 % · IWM 21 j < 0. « Gelées » = aucun réglage sans révision v4.1, qui remettrait le chrono forward à zéro. | Protocole v4 §2 |
| **Marge (au seuil)** | Distance entre la valeur du titre et le seuil de la règle (ex. prix 2,14 $ → marge 5,86 $ sous le seuil 8 $). Affichage seulement — ne re-classe pas. | §3 |
| **Bêta** | Sensibilité du titre au marché, mesurée sur ses 126 dernières séances : bêta 1,6 = quand IWM fait −1 %, le titre fait −1,6 % en moyenne. | §4 (observationnel) |
| **Corrélation** | À quel point le titre suit le marché (0 = indépendant, 1 = copie conforme). Fenêtre 126 séances. | §4 |
| **Résidu (bêta)** | La part de la chute 1 mois qui appartient au titre lui-même, une fois retirée la part expliquée par le marché : `résidu = chute 1 mois − bêta × IWM 21 j`. Ex. : marché −5,1 % × bêta 1,6 ≈ −8 % « normaux » ; le titre a fait −18,3 % → résidu −12,4 %. | A.5 |
| **Profondeur de survente** | Lecture du résidu : plus il est négatif, plus le titre a chuté au-delà de ce que le marché justifie. Historiquement le meilleur gradient interne (+11,2 % pour résidu < −10 % vs +2,9 % pour résidu > −3 %) — c'est l'ordre d'affichage de la cohorte, indicatif et non validé. Jamais une règle d'entrée. | A.5 |

## Drapeaux EDGAR (documents officiels SEC)

| Terme | Définition | Chiffre source |
|---|---|---|
| **EDGAR** | La base publique de la SEC (régulateur boursier US) où chaque société cotée dépose ses documents officiels, datés. Notre source fondamentale, gratuite et point-in-time. | — |
| **Dilution / dilution en attente** | L'entreprise a déposé le document qui prépare une émission de NOUVELLES actions (formulaires S-1/S-3/F-1/F-3/424B, fenêtre 180 j). Double effet : ta part de l'entreprise fond, et l'arrivée des titres écrase le cours. Seul drapeau directionnel mesuré : **2,1× plus fréquent avant un crash** (contre 1,6× avant une explosion). Règle 2 : la cohorte v4 exige ZÉRO dépôt de ce type. | A.1/A.2 |
| **Going-concern** | Dans le dernier rapport officiel (10-K/10-Q), les auditeurs écrivent douter que l'entreprise survive 12 mois (« substantial doubt », langage comptable ASC 205-40). Contre-intuitif mais mesuré : multiplie les DEUX queues (explosion ×4,4, crash ×5,2) — signal de « gros mouvement imminent », sans direction. | A.1/A.2 |
| **Late filing (retard de dépôt, NT)** | L'entreprise n'a pas rendu son rapport trimestriel/annuel à temps (formulaires NT 10-Q/NT 10-K). Détresse administrative — même profil barbell que le going-concern (×3,6 explosions, ×3,9 crashs). | A.1/A.2 |
| **Cash runway** | Mois de trésorerie restants au rythme de dépense actuel, calculés depuis les comptes officiels (XBRL). Explosées comme crashées avaient ~20 mois ; 120 = plafond « très confortable ». | A.1/A.2 |
| **Insiders / Form 4** | Achats/ventes d'actions par les dirigeants, déclarés sous 2 jours (formulaire 4). Sur 161 explosions historiques : ZÉRO achat net avant — normal, un dirigeant qui connaît une news à venir a interdiction légale de trader (blackout). Leur silence ne dit rien ; leurs achats restent la moins mauvaise info isolée mesurée. | A.1 |
| **8-K** | Dépôt « événement matériel » (contrat, financement, résultat d'essai…). 84 % des explosées en ont un dans la fenêtre… mais 83 % des témoins aussi : le catalyseur est dans le CONTENU, pas dans le comptage — d'où « lire les 8-K récents » avant tout achat. | A.1 |
| **Barbell / les deux queues** | Distribution en haltère : beaucoup de très gros gains ET de très grosses pertes en même temps. Les drapeaux de détresse marquent cette zone sans en choisir le côté — c'est pourquoi ils ne sont ni « à fuir » ni « à acheter ». | A.2 |

## Profils v2 (zones extrêmes)

| Terme | Définition | Chiffre source |
|---|---|---|
| **🔥 Phénix** | Action massacrée (loin de son plus-haut 52 semaines), volatilité comprimée, premiers signes de stabilisation. Concentre les explosions (4,6× en 2021-23 ; ~1,7× sur 5 ans — dépend du régime) mais AUSSI les crashs (2,3×) : espérance −11 %. Recherche humaine uniquement. | v2 §9 |
| **🚀 Fusée** | Momentum extrême + explosion de volume. Verdict : aucun avantage (1,03× — comme le hasard), espérance −9,6 %. | v2 §9 |
| **Force de profil** | Intensité d'appartenance au profil (0-1), percentiles cross-sectionnels du protocole v2. Ordre d'affichage de la section. | v2 §3 |
| **« Non validé »** | Marqueur permanent : sur données gratuites, un backtest peut réfuter, jamais confirmer. Seul le suivi réel peut faire tomber ce marqueur. | Protocoles §2 |

## Suivi de trajectoire

| Terme | Définition | Chiffre source |
|---|---|---|
| **Checkpoint** | Point de contrôle après l'entrée (3 j, 1 sem, 2 sem, 1 mois) où l'on compare le titre au seuil qui séparait le mieux, historiquement, les futures explosions des futurs crashs. | A.6 |
| **Probabilités conditionnelles** | Comment les fréquences historiques évoluent SACHANT la position au checkpoint. Ex. : ≥ +3 % à 1 semaine → P(doubler) ×4, P(−50 %) ÷2. Fréquences passées, pas des prédictions. | A.6 |
| **Cônes / trajectoires** | Les chemins médians mesurés : explosions +5,6 % dès 3 j → +127 % à 3 mois (et tiennent à 6 mois) ; crashs −1,2 % → −59 % (et continuent). « Entre les cônes » = ni l'un ni l'autre. | A.6 |
| **Whipsaw** | Le coût caché des ventes automatiques précoces : 32 % des futures explosions étaient encore NÉGATIVES à 3 jours (30 % à 2 semaines). C'est pourquoi les checkpoints informent et ne vendent jamais : le stop serré fait passer le panier v4 de +1,4 % à −0,4 %. | A.6 |

## Cohorte v5 — multi-fenêtres (protocole v5, signé 2026-07-09)

| Terme | Définition | Chiffre source |
|---|---|---|
| **Sélecteur 7 j / 14 j / 21 j** | Le même thermomètre marché (IWM) mesuré sur trois rétroviseurs. Les fenêtres courtes voient les purges éclair (juillet 2024 : −10 % en 16 séances, jamais vue par le 21 j), les longues voient les glissades de plusieurs mois. Le choix pilote la liste v5 ; la v4 reste jugée sur 21 j. | v5 §3.2-§3.3 |
| **Chute fenêtre (règle −15 %)** | Le titre doit avoir perdu ≥ 15 % sur la fenêtre choisie. Gradient mesuré : plus la chute est profonde, plus le rebond moyen est fort — jusqu'à −20 % ; au-delà, les crashs doublent. | v5 §4 |
| **Volume calme (≤ 1,25×)** | Volume moyen pendant la chute / volume habituel (60 séances précédentes). Bas = le titre baisse « dans l'indifférence » — signature des futurs doubleurs (1,1×) ; les futurs morts chutaient SUR volume (1,4-1,6×). | v5 §5 |
| **CMF > −0,10 (règle v5)** | Flux d'argent Chaikin sur 20 séances : les futurs morts avaient un CMF deux fois plus négatif (−0,15) que les futurs doubleurs (−0,07). | v5 §5 |
| **⚡ Krach éclair** | IWM ≤ −8 % en 3 séances — le pire demi-percentile de 26 ans (~1×/2 ans : COVID, 2022, yen-carry 2024, tarifs 2025). Information de contexte, jamais une règle d'entrée ; payoff mesuré sur UN épisode seulement. | v5 §7 |
| **Variante primaire (14 j)** | Trois fenêtres = trois chances de faux positif. Le jugement forward ne validera la méthode que si la 14 j (désignée d'avance) passe ses critères ; 7 j et 21 j sont secondaires. | v5 §9 |
| **P(−50 %) « 0 %* »** | Le zéro crash mesuré à 7/14 j est un artefact d'échantillon (70-151 cas, vrai taux ~2 %) — dimensionner comme si c'était ~2 %. | v5 §6.2 |
| **Validation D** | Le jugement forward des cohortes v5 : ≥ 4 cohortes non chevauchantes pour une première lecture, ≥ 8 (~24 mois) pour le jugement final. | v5 §9 |

*Ajouté en S3 (Epic 4), complété Epic 5. Toute nouvelle métrique affichée doit entrer ici ET
avoir son infobulle — c'est une règle de revue.*
