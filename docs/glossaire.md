# Glossaire — tous les termes affichés par le screener

Référence unique des labels techniques de l'interface. Règle d'or (S3) : **le label reste
technique, l'infobulle explique, ce fichier recense tout**.

Depuis l'Epic 6 S2, les **valeurs gelées des protocoles v4/v5** (seuils des règles,
chiffres des bandeaux, fenêtres de checkpoint) ne sont plus versionnées : elles sont
servies à l'interface par l'API depuis la config privée (`config/local.yml`), et les
protocoles signés sont archivés hors repo. Ce glossaire décrit les **concepts** ; les
chiffres v2/v3 cités restent publics (post-mortems versionnés dans `docs/`).

## Marché & cadre

| Terme | Définition | Source |
|---|---|---|
| **IWM** | ETF qui suit le Russell 2000, l'indice des petites capitalisations US. Notre thermomètre « marché ». | — |
| **IWM n j** | Variation d'IWM sur les n dernières séances (fenêtre fixée par le protocole). Négatif = marché baissier → la méthode s'applique ; positif = elle se met en pause. | protocole v4 (privé) |
| **Univers tradable** | Les ~2 500 small/micro caps US (NASDAQ, NYSE, AMEX) qui passent les filtres durs de liquidité/prix — ce qu'on peut réellement acheter sans être coincé. | — |
| **fwd63** | Rendement du titre 63 jours de bourse (~3 mois calendaires) après la date d'observation. L'horizon de jugement de tous les protocoles. | — |
| **Espérance nette** | Gain/perte MOYEN par titre à l'horizon fwd63, coût d'aller-retour déduit. Moyenne tirée par les rares gros gagnants : toujours comparer à la médiane. Valeur affichée servie par l'API. | protocole v4 (privé) |
| **Taux de base** | La fréquence « au hasard » (doubler, perdre la moitié) dans l'univers tradable, qui sert de référence aux fréquences des filtres. | protocoles (privés) |
| **t-stat / « non significatif »** | Test statistique : le résultat est-il distinguable de la chance ? Unité indépendante = le trimestre (les titres d'un même jour vivent le même marché). Il faut t ≥ 2 ; aucune cohorte n'y est — d'où la validation forward. | protocoles (privés) |
| **Validation forward (« Validation C »)** | Le seul juge encore recevable : les cohortes enregistrées chaque jour à partir du 6 juillet 2026, jugées sur leurs résultats réels (critères pré-écrits, première lecture ≥ 12 mois). Sans biais de survie : les faillites seront vues en direct. | protocole v4 (privé) |
| **Biais de survie / plafond optimiste** | Nos données historiques ne contiennent que les entreprises encore cotées : les faillites ont disparu des calculs. Tout chiffre historique est donc une borne haute. | protocoles §2 (v3/v4) |

## Cohorte v4 (les 4 règles gelées + champs)

| Terme | Définition | Source |
|---|---|---|
| **Cohorte v4** | Les titres du jour qui passent les 4 règles gelées du protocole signé. Seul groupe mesuré à espérance historique positive. Enregistrée chaque jour pour le jugement forward. | protocole v4 (privé) |
| **Règles gelées** | Les 4 conditions (plafond de prix · zéro dilution en attente · chute minimale sur ~1 mois · marché lui-même en baisse). Seuils servis par l'API. « Gelées » = aucun réglage sans révision v4.1, qui remettrait le chrono forward à zéro. | protocole v4 §2 (privé) |
| **Marge (au seuil)** | Distance entre la valeur du titre et le seuil de la règle. Affichage seulement — ne re-classe pas. | protocole v4 §3 (privé) |
| **Bêta** | Sensibilité du titre au marché, mesurée sur la fenêtre du protocole (~6 mois) : bêta 1,6 = quand IWM fait −1 %, le titre fait −1,6 % en moyenne. | protocole v4 §4 (observationnel) |
| **Corrélation** | À quel point le titre suit le marché (0 = indépendant, 1 = copie conforme). Même fenêtre que le bêta. | protocole v4 §4 |
| **Résidu (bêta)** | La part de la chute 1 mois qui appartient au titre lui-même, une fois retirée la part expliquée par le marché : `résidu = chute 1 mois − bêta × IWM n j`. Ex. : marché −5,1 % × bêta 1,6 ≈ −8,2 % « normaux » ; le titre a fait −18,3 % → résidu −10,1 %. | protocole v4 A.5 (privé) |
| **Profondeur de survente** | Lecture du résidu : plus il est négatif, plus le titre a chuté au-delà de ce que le marché justifie. Historiquement le meilleur gradient interne — c'est l'ordre d'affichage de la cohorte, indicatif et non validé. Jamais une règle d'entrée. | protocole v4 A.5 (privé) |

## Drapeaux EDGAR (documents officiels SEC)

| Terme | Définition | Source |
|---|---|---|
| **EDGAR** | La base publique de la SEC (régulateur boursier US) où chaque société cotée dépose ses documents officiels, datés. Notre source fondamentale, gratuite et point-in-time. | — |
| **Dilution / dilution en attente** | L'entreprise a déposé le document qui prépare une émission de NOUVELLES actions (formulaires S-1/S-3/F-1/F-3/424B, fenêtre 180 j). Double effet : ta part de l'entreprise fond, et l'arrivée des titres écrase le cours. Seul drapeau directionnel mesuré : **2,1× plus fréquent avant un crash** (contre 1,6× avant une explosion). Les cohortes v4/v5 exigent ZÉRO dépôt de ce type. | exploration Epic 3/4 |
| **Going-concern** | Dans le dernier rapport officiel (10-K/10-Q), les auditeurs écrivent douter que l'entreprise survive 12 mois (« substantial doubt », langage comptable ASC 205-40). Contre-intuitif mais mesuré : multiplie les DEUX queues (explosion ×4,4, crash ×5,2) — signal de « gros mouvement imminent », sans direction. | exploration Epic 3/4 |
| **Late filing (retard de dépôt, NT)** | L'entreprise n'a pas rendu son rapport trimestriel/annuel à temps (formulaires NT 10-Q/NT 10-K). Détresse administrative — même profil barbell que le going-concern (×3,6 explosions, ×3,9 crashs). | exploration Epic 3/4 |
| **Cash runway** | Mois de trésorerie restants au rythme de dépense actuel, calculés depuis les comptes officiels (XBRL). Explosées comme crashées avaient ~20 mois ; 120 = plafond « très confortable ». | exploration Epic 3/4 |
| **Insiders / Form 4** | Achats/ventes d'actions par les dirigeants, déclarés sous 2 jours (formulaire 4). Sur 161 explosions historiques : ZÉRO achat net avant — normal, un dirigeant qui connaît une news à venir a interdiction légale de trader (blackout). Leur silence ne dit rien ; leurs achats restent la moins mauvaise info isolée mesurée. | exploration Epic 3/4 |
| **8-K** | Dépôt « événement matériel » (contrat, financement, résultat d'essai…). 84 % des explosées en ont un dans la fenêtre… mais 83 % des témoins aussi : le catalyseur est dans le CONTENU, pas dans le comptage — d'où « lire les 8-K récents » avant tout achat. | exploration Epic 3/4 |
| **Barbell / les deux queues** | Distribution en haltère : beaucoup de très gros gains ET de très grosses pertes en même temps. Les drapeaux de détresse marquent cette zone sans en choisir le côté — c'est pourquoi ils ne sont ni « à fuir » ni « à acheter ». | exploration Epic 3/4 |

## Profils v2 (zones extrêmes)

| Terme | Définition | Source |
|---|---|---|
| **🔥 Phénix** | Action massacrée (loin de son plus-haut 52 semaines), volatilité comprimée, premiers signes de stabilisation. Concentre les explosions (4,6× en 2021-23 ; ~1,7× sur 5 ans — dépend du régime) mais AUSSI les crashs (2,3×) : espérance −11 %. Recherche humaine uniquement. | v2 §9 (public) |
| **🚀 Fusée** | Momentum extrême + explosion de volume. Verdict : aucun avantage (1,03× — comme le hasard), espérance −9,6 %. | v2 §9 (public) |
| **Force de profil** | Intensité d'appartenance au profil (0-1), percentiles cross-sectionnels du protocole v2. Ordre d'affichage de la section. | v2 §3 (public) |
| **« Non validé »** | Marqueur permanent : sur données gratuites, un backtest peut réfuter, jamais confirmer. Seul le suivi réel peut faire tomber ce marqueur. | protocoles §2 |

## Suivi de trajectoire

| Terme | Définition | Source |
|---|---|---|
| **Checkpoint** | Point de contrôle après l'entrée (jours fixés par le protocole, servis par l'API) où l'on compare le titre au seuil qui séparait le mieux, historiquement, les futures explosions des futurs crashs. | protocole v4 A.6 (privé) |
| **Probabilités conditionnelles** | Comment les fréquences historiques évoluent SACHANT la position au checkpoint. Fréquences passées, pas des prédictions — textes servis par l'API. | protocole v4 A.6 (privé) |
| **Cônes / trajectoires** | Les chemins médians mesurés des futures explosions et des futurs crashs après l'entrée. « Entre les cônes » = ni l'un ni l'autre. | protocole v4 A.6 (privé) |
| **Whipsaw** | Le coût caché des ventes automatiques précoces : une part substantielle des futures explosions était encore NÉGATIVE aux premiers checkpoints. C'est pourquoi les checkpoints informent et ne vendent jamais : le stop serré détruit le rendement mesuré du panier. | protocole v4 A.6 (privé) |

## Cohorte v5 — multi-fenêtres (protocole v5, signé 2026-07-09)

| Terme | Définition | Source |
|---|---|---|
| **Sélecteur multi-fenêtres** | Le même thermomètre marché (IWM) mesuré sur trois rétroviseurs (fenêtres pré-déclarées, servies par l'API). Les fenêtres courtes voient les purges éclair, les longues voient les glissades de plusieurs mois. Le choix pilote la liste v5 ; la v4 reste jugée sur sa propre fenêtre (protocole distinct). | protocole v5 (privé) |
| **Chute fenêtre** | Le titre doit avoir perdu au moins le seuil du protocole sur la fenêtre choisie (seuil servi par l'API). Gradient mesuré : plus la chute est profonde, plus le rebond moyen historique est fort — jusqu'à un coude au-delà duquel les crashs doublent. | protocole v5 (privé) |
| **Volume calme** | Volume moyen pendant la chute / volume habituel (base fixée par le protocole). Bas = le titre baisse « dans l'indifférence » — signature des futurs doubleurs ; les futurs morts chutaient SUR volume. | protocole v5 (privé) |
| **CMF (règle v5)** | Flux d'argent Chaikin sur 20 séances : où se font les clôtures dans le range du jour, pondéré par le volume. Proche de −1 = l'argent fuit. La règle exige un CMF au-dessus du seuil du protocole (servi par l'API). | protocole v5 (privé) |
| **⚡ Krach éclair** | Chute d'IWM en quelques séances au-delà du percentile extrême de l'historique long (seuil servi par l'API). Information de contexte, jamais une règle d'entrée ; payoff mesuré sur UN épisode seulement. | protocole v5 (privé) |
| **Variante primaire** | Trois fenêtres = trois chances de faux positif. Le jugement forward ne validera la méthode que si la variante désignée d'avance passe ses critères ; les deux autres sont secondaires. | protocole v5 (privé) |
| **P(−50 %) « 0 %* »** | Le zéro crash mesuré sur les fenêtres courtes est un artefact d'échantillon (vrai taux ~2 %) — dimensionner comme si c'était ~2 %. | protocole v5 (privé) |
| **Validation D** | Le jugement forward des cohortes v5 : ≥ 4 cohortes non chevauchantes pour une première lecture, ≥ 8 (~24 mois) pour le jugement final. | protocole v5 (privé) |

*Ajouté en S3 (Epic 4), complété Epic 5, sanitisé Epic 6 S2 (valeurs gelées → config privée).
Toute nouvelle métrique affichée doit entrer ici ET avoir son infobulle — c'est une règle de revue.*
