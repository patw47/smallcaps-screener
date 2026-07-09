# Protocole pré-enregistré v5 — « washout multi-fenêtres » (SIGNÉ)

**Signé par le propriétaire le 2026-07-09.** Les §8 (règles d'entrée) et §9 (schéma de
jugement) sont désormais CONTRAIGNANTS — toute modification = révision v5.1 + remise à
zéro du chrono forward. Le chrono de la Validation D court à partir de la première
cohorte instrumentée.

Rédigé le 2026-07-09, à partir de la session d'exploration du même jour (l'intégralité des
tableaux et de la logique de calcul est reproduite ci-dessous). Le protocole v4
(`backtest_protocol_v4.md`, signé le 2026-07-06) **continue de tourner inchangé** : v5 est
une instrumentation additionnelle, pas un remplacement.

Scripts d'exploration : [`docs/exploration_v5/`](exploration_v5/). Données brutes :
`data/sim_grid_windows.json`, `data/sim_autopsy_windows.json` (volume Docker).

---

## 0. Ce que ce document est — et ce qu'il n'est pas

Comme le v4, ce protocole est **de la recherche statistique, pas une promesse de gain**.
Toutes les règles ci-dessous ont été trouvées par **exploration a posteriori sur des données
déjà vues** : nous avons regardé les réponses avant de choisir les seuils. Conséquence
mathématique inévitable : les données historiques ne peuvent plus ni confirmer ni réfuter
ces règles — chaque « fenêtre de test » a été dépensée pendant la découverte. Le **seul juge
recevable est le futur** (validation forward, §9).

De plus, cette session d'exploration est la **quatrième** du projet (après v1, v2, v3, v4).
À chaque session, des dizaines de cellules statistiques ont été scannées. Plus on scanne,
plus la « meilleure cellule » a de chances d'être un artefact du hasard. Ce risque, appelé
*data-mining* ou *multiple comparisons* (comparaisons multiples), est documenté à chaque
étape ci-dessous, et c'est pourquoi aucun chiffre de ce document ne doit être lu comme une
espérance de gain réelle : ce sont des **plafonds d'espoir** mesurés sur des données
survivantes, avec des seuils choisis après coup.

---

## 1. Pourquoi le marché baissier — la logique « washout »

### L'hypothèse en une phrase

Quand **tout le marché** des small caps purge, des titres corrects se font brader **sans
raison qui leur soit propre** (vendeurs forcés, retraits de fonds, panique indiscriminée) ;
ces titres-là, une fois la purge passée, reviennent vers leur prix — c'est la **réversion
post-survente** (*oversold overshoot* : l'excès de vente au-delà du justifiable).

À l'inverse, un titre qui s'effondre **seul, pendant que le marché monte**, a presque
toujours une vraie raison de s'effondrer (dilution imminente, procès, cash épuisé, échec
clinique) — et il continue de tomber.

### La preuve par le miroir

Le test le plus convaincant de cette logique est de prendre **exactement les mêmes règles
titre** et de les appliquer dans les deux contextes de marché. C'est ce que nous avons fait
(session 2026-07-09). Profil complet (§6) appliqué des deux côtés :

| Contexte | Médiane fwd63 | P(perdre −50 %) | Nature de la distribution |
|---|---|---|---|
| Marché **en baisse** sur la fenêtre | **+10 % à +23 %** | 0 à 2 % | le titre typique gagne |
| Marché **en hausse** sur la fenêtre | **−1 % à −9 %** | 5 à 7 % | le titre typique perd ; la moyenne ne survit que grâce à de rares billets de loterie (ex. un titre à +132 % qui porte à lui seul la moyenne de sa période) |

Le détail complet du test miroir est au §6.3. La condition « marché en baisse » n'est donc
pas une superstition prudentielle : c'est **le composant qui sélectionne le mécanisme** —
survente collective réversible plutôt que naufrage individuel mérité. Elle transforme la
même liste de titres d'une loterie à médiane négative en panier à médiane positive.

### Vocabulaire pour néophytes

- **IWM** : un ETF (fonds coté) qui réplique l'indice Russell 2000, c'est-à-dire les
  ~2 000 petites capitalisations américaines. C'est notre thermomètre du « marché ».
- **fwd63** : le rendement du titre **63 séances de bourse** (~3 mois calendaires) après
  la date d'observation. C'est notre horizon de jugement, hérité des protocoles v2-v4.
- **Purge / washout** : une phase où l'indice baisse et entraîne presque tout avec lui.
- **Médiane vs moyenne** : la médiane est le résultat du titre « du milieu » (50 % font
  mieux, 50 % font moins bien). Une moyenne positive avec une médiane négative signifie
  que la plupart des titres perdent et que quelques gagnants extrêmes tirent la moyenne —
  une loterie, pas une méthode.

---

## 2. Données et logique de calcul

### 2.1 Le jeu de données

- **19 666 observations** : 1 870 tickers small/micro caps US observés à **18 dates
  trimestrielles** indépendantes, du 2021-09-29 au 2026-01-06 (fichier
  `data/sim_filter.json`, constitué lors de l'exploration du 2026-07-06 — Epic 4).
- Chaque observation contient : prix, chute 1 mois, CMF, drapeau dilution EDGAR
  point-in-time, et les rendements forward à 7 horizons (l'horizon de jugement fwd63 est
  l'élément d'indice 5, vérifié en reproduisant les chiffres du protocole v4 à 1
  observation près : n=1 192 vs 1 193, E +5,9 %).
- Les chutes sur 3/7/14/21 séances et les volumes ont été recalculés depuis les clôtures
  ajustées Yahoo Finance (caches `closes_1870.pkl`, `volumes_1870.pkl`).
- **Biais du survivant** : les tickers radiés de la cote (délistés) avant la constitution
  du jeu de données en sont absents. Or les délistés sont surreprésentés parmi les crashs.
  Toutes les probabilités de perte ci-dessous sont donc des **planchers**, et toutes les
  espérances des **plafonds**. (Décision propriétaire : pas de données payantes — ce biais
  est irréductible et documenté partout.)

### 2.2 Les formules

Toutes les grandeurs sont calculées ainsi (P(t) = clôture ajustée du jour t) :

**Rendement sur une fenêtre de w séances** (le « rétroviseur ») :

    r_w(t) = P(t) / P(t − w) − 1

Exemple : IWM 21 j = +4,4 % signifie que la clôture d'IWM aujourd'hui vaut 1,044 fois sa
clôture d'il y a 21 séances de bourse. Aucune moyenne mobile, aucune pente : un simple
rapport entre deux points.

**Rendement forward net** (ce qu'on juge) :

    fwd63_net(t) = P(t + 63) / P(t) − 1 − 0,01

Le terme −0,01 est la **décote de friction** (haircut) de 1 % aller-retour héritée du
protocole v4 : écart achat/vente + glissement d'exécution, volontairement forfaitaire.

**Espérance nette** : moyenne arithmétique des fwd63_net d'une cellule.
**Médiane** : valeur centrale des fwd63_net triés.
**P(doubler)** = fraction des observations avec fwd63 ≥ +100 %.
**P(−50 %)** = fraction des observations avec fwd63 ≤ −50 %.

**Statistique t par dates** — la mesure d'incertitude. Les observations d'une même date ne
sont pas indépendantes (si le marché rebondit, tous les titres de la cohorte rebondissent
ensemble). Traiter 1 193 observations comme 1 193 tirages indépendants surestimerait
énormément la certitude. On agrège donc **par date** :

    m_d  = moyenne des fwd63_net des titres qualifiés à la date d
    t    = moyenne(m_d) / ( écart-type(m_d) / √k )        avec k = nombre de dates actives

Règle de lecture : t ≥ 2 ≈ « significatif » (moins de ~5 % de chances que ce soit du
hasard) ; t < 1 = indistinguable du bruit. **Tous les t de ce document sont < 1,4** — c'est
LA raison pour laquelle seul le forward peut juger.

**CMF (Chaikin Money Flow)** — mesure les flux d'argent entrants/sortants sur 20 séances :

    MFM(t) = ((C−L) − (H−C)) / (H−L)        position de la clôture dans le range du jour
    CMF    = Σ (MFM × Volume) / Σ Volume     sur 20 séances

CMF proche de +1 : les clôtures se font près des plus-hauts du jour sur du volume
(acheteurs dominants). Proche de −1 : près des plus-bas (vendeurs dominants).

**Volume calme** — la chute s'est-elle faite SUR ou SANS volume :

    vol_calm_w(t) = moyenne(Volume, w dernières séances) / moyenne(Volume, 60 séances précédentes)

vol_calm ≤ 1,25 signifie : pendant la chute, le volume n'a pas dépassé de plus de 25 % son
niveau habituel — personne ne se précipite pour vendre, le titre baisse « dans
l'indifférence ». L'autopsie (§5) montre que c'est un marqueur des futurs rebonds.

### 2.3 Pourquoi juger par dates et pas par titres

Illustration mesurée : la cohorte du 2 janvier 2025 (marché en début de glissade) a perdu
en moyenne −29 à −34 % ; celle du 4 avril 2025 (marché au fond de la purge) a gagné +37 à
+49 %. **Le sort d'une cohorte se joue en bloc.** Chaque date est donc UN tirage, pas cent.
Avec 5 à 9 dates actives par fenêtre, l'échantillon effectif est minuscule — d'où des t
faibles quoi qu'il arrive, et l'humilité obligatoire de ce document.

---

## 3. Le choix des fenêtres : 7, 14 et 21 séances

### 3.1 Sensibilité de la condition marché (règles titre du v4 : chute ≤ −3 %)

Première question posée : la fenêtre de 21 séances du v4 est-elle « magique » ? Réponse —
non, l'effet survit aux fenêtres voisines (le signe est robuste), mais aucune n'est
statistiquement solide :

| Fenêtre IWM | Dates actives /18 | n | E nette | Médiane | P(doubler) | P(−50 %) | t |
|---|---|---|---|---|---|---|---|
| 7 séances | 5 | 746 | +8,5 % | +6,2 % | 2,1 % | 2,9 % | 0,68 |
| 14 séances | 9 | 1 126 | +5,1 % | +1,5 % | 1,8 % | 2,1 % | 0,33 |
| 21 séances (v4) | 9 | 1 193 | +5,9 % | +1,6 % | 2,0 % | 1,9 % | 0,56 |
| *Titre au hasard (référence)* | 18 | 19 666 | **−3,9 %** | — | 0,8 % | 3,8 % | — |

Lecture : les trois fenêtres battent largement le hasard (−3,9 %), mais le critère
« doubler au moins aussi probable que crasher » ne tenait qu'à 21 j avec le seuil de chute
−3 % — il redevient favorable aux trois fenêtres avec le seuil −15 % retenu au §4.

### 3.2 Anatomie des purges (pourquoi une seule fenêtre ne suffit pas)

**Les grosses purges vues de haut** (chute ≥ 10 % depuis le plus-haut absolu, 6 ans d'IWM) :

| Purge (pic) | Creux | Profondeur | Pic→creux | Récupération |
|---|---|---|---|---|
| nov. 2021 | juin 2022* | −31,9 % | 152 séances (~7 mois) | 601 séances (~2,4 ans) |
| nov. 2024 | avr. 2025 | −27,5 % | 90 séances (~4 mois) | 107 séances (~5 mois) |
| janv. 2026 | mars 2026 | −11,0 % | 46 séances (~2 mois) | 11 séances |

*\*le bear 2021-2024 contenait plusieurs jambes internes.*

**Le retard structurel du signal 21 j** — distance entre le premier jour où IWM 21 j passe
négatif et le creux de la purge :

| Purge | Signal allumé | Creux atteint | Chute restante après le signal |
|---|---|---|---|
| 2021-2022 | 26 nov. 2021 | 139 séances plus tard | **−25,9 %** |
| 2024-2025 | 10 déc. 2024 | 80 séances plus tard | **−25,8 %** |
| 2026 | 5 févr. 2026 | 36 séances plus tard | −6,2 % |

Dans les deux grosses purges, le signal s'allume ~3 semaines après le pic puis le marché
tombe **encore 4 à 6,5 mois et −26 %**. C'est le mécanisme du « cimetière janvier 2025 »
(§5) : entrer au 25ᵉ jour d'une purge qui en dure 90.

**Le découpage fin en jambes** (méthode zigzag : toute baisse ≥ 5 % depuis un pic *local*,
close par un rebond de 5 % — table complète en Annexe A.3) : **32 jambes de baisse en 6
ans**, soit ~5-6 par an :

| Catégorie | Nombre | Durée médiane | Étendue |
|---|---|---|---|
| Petites (−5 à −10 %) | 19 | 10 séances (~2 sem.) | 4-28 séances |
| Moyennes (−10 à −15 %) | 9 | 16 séances (~3 sem.) | 7-46 séances |
| Grosses (> −15 %) | 4 | 30 séances (~6 sem.) | 11-63 séances |

**Découverte clé** : la jambe de juillet-août 2024 (−10,1 % en 16 séances) n'a **jamais**
allumé le signal 21 j — le rebond est arrivé avant que la moyenne du mois passe au rouge.
Une fenêtre de 7 séances l'aurait vue en quelques jours. Inversement, les longues
glissades (63 séances en 2023) sont le territoire naturel du 21 j.

**C'est la justification du multi-fenêtres** : 7 j capture les purges éclair, 21 j les
longues glissades, 14 j l'entre-deux. Aucune fenêtre unique ne couvre les deux régimes.

### 3.3 Le clignotement (pourquoi les fenêtres courtes ont un coût)

Durée des périodes où le signal reste allumé **d'affilée** (IWM_w < 0 en séances
consécutives, 6 ans) :

| Fenêtre | Périodes actives | Moyenne | Médiane | P75 | Max | % du temps actif |
|---|---|---|---|---|---|---|
| 7 j | 134 | 5,0 séances | **3** | 7 | 24 | 44 % |
| 14 j | 90 | 6,8 séances | **3** | 10 | 35 | 41 % |
| 21 j | 75 | 8,1 séances | **2** | 10 | 60 | 41 % |

Le signal est allumé ~42 % du temps quelle que soit la fenêtre, mais il **clignote** : la
période active typique dure 2-3 séances (à 21 j, 29 périodes sur 75 durent exactement UNE
séance). Deux régimes coexistent : une majorité de clignotements de 1-4 jours (oscillation
autour de zéro, sans purge réelle) et une minorité de vraies glissades de 10-60 jours qui
concentrent presque tout le temps actif. Le protocole n'impose **pas** de règle de
persistance (ex. « ≥ 3 séances consécutives ») : elle a été envisagée puis écartée pour ne
pas ajouter un 5ᵉ paramètre ajusté a posteriori — le clignotement est assumé comme limite
connue (§10).

### 3.4 Pourquoi PAS de fenêtre 3 jours

La fenêtre 3 séances produit les plus beaux chiffres de toute l'exploration — et les plus
creux. Profil complet (§6) à 3 j : n=22, E +41,2 %, médiane +27,5 %, P(doubler) 18,2 %.
Mais : **18 des 22 observations viennent de la seule date du 4 avril 2025** (+49 % de
moyenne) ; les 4 autres dates ont 1 titre chacune (−40 %, +80 %, +8 %, −29 %). Sur la
grille de profondeur, le t par dates est même **négatif** (−1,33) : par épisodes, ça perd
plus souvent que ça gagne. Par ailleurs le signal 3 j s'allume sur du bruit (−0,5 %,
−0,6 % aux dates d'échantillon) — les clignotements du §3.3 à l'état pur. Une chute titre
de −15 % en 3 séances hors purge violente est un événement d'entreprise (résultats,
offering, échec clinique), précisément la population « vraies casseroles ». La fenêtre
3 j n'est donc **pas** une variante : elle ne sert que sous forme de drapeau d'intensité
marché (§7).

---

## 4. Le choix de la profondeur de chute : −15 %

Question posée : « de combien doivent baisser les actions pour qu'elles rebondissent ? »
Réponse mesurée : **il n'y a pas de seuil magique — c'est un gradient monotone.** Plus la
chute (sur la même fenêtre que le marché) est profonde, plus le rebond moyen est fort,
dans les trois fenêtres. Cellules : prix ≤ 8 $, sans dilution, IWM_w < 0, fwd63 net :

**Fenêtre 7 séances** (5/18 dates actives)

| Chute ≤ | n | E nette | Médiane | P(x2) | P(−50 %) | t |
|---|---|---|---|---|---|---|
| 0 % | 751 | +11,5 % | +7,1 % | 2,9 % | 2,1 % | 0,69 |
| −3 % | 608 | +14,7 % | +10,8 % | 3,3 % | 1,8 % | 0,75 |
| −5 % | 522 | +16,5 % | +12,6 % | 3,3 % | 1,3 % | 0,70 |
| −10 % | 339 | +20,4 % | +16,4 % | 4,1 % | 1,5 % | 0,66 |
| **−15 %** | **191** | **+24,9 %** | **+19,4 %** | **5,2 %** | **2,1 %** | 0,66 |
| −20 % | 91 | +35,8 % | +26,9 % | 8,8 % | 2,2 % | 1,19 |
| −30 % | 10 | (n trop faible) | | | | |

**Fenêtre 14 séances** (9/18 dates actives)

| Chute ≤ | n | E nette | Médiane | P(x2) | P(−50 %) | t |
|---|---|---|---|---|---|---|
| 0 % | 1 267 | +4,5 % | +0,6 % | 1,7 % | 2,1 % | 0,38 |
| −3 % | 1 126 | +4,6 % | +0,8 % | 1,8 % | 2,2 % | 0,23 |
| −5 % | 1 017 | +5,1 % | +1,4 % | 2,0 % | 2,0 % | 0,11 |
| −10 % | 728 | +7,2 % | +2,5 % | 2,3 % | 1,9 % | 0,03 |
| **−15 %** | **503** | **+9,9 %** | **+5,4 %** | **2,6 %** | **1,8 %** | −0,01 |
| −20 % | 303 | +12,8 % | +9,6 % | 4,3 % | 1,7 % | 0,25 |
| −30 % | 79 | +18,7 % | +12,5 % | 8,9 % | **3,8 %** | 0,60 |

**Fenêtre 21 séances** (9/18 dates actives — la ligne −3 % est la règle v4)

| Chute ≤ | n | E nette | Médiane | P(x2) | P(−50 %) | t |
|---|---|---|---|---|---|---|
| 0 % | 1 310 | +5,2 % | +1,6 % | 1,8 % | 2,0 % | 0,61 |
| −3 % (v4) | 1 192 | +5,9 % | +1,6 % | 2,0 % | 1,9 % | 0,56 |
| −5 % | 1 096 | +6,7 % | +2,0 % | 2,1 % | 1,9 % | 0,54 |
| −10 % | 867 | +7,6 % | +2,2 % | 2,5 % | 2,0 % | 0,45 |
| **−15 %** | **595** | **+9,6 %** | **+4,9 %** | **2,9 %** | **1,8 %** | 0,58 |
| −20 % | 377 | +12,6 % | +7,3 % | 4,0 % | 2,4 % | 0,91 |
| −30 % | 140 | +19,5 % | +12,5 % | 6,4 % | **3,6 %** | 1,18 |

**Pourquoi −15 % et pas −20 % ou −30 %** : au-delà de −20 %, deux dégradations. (a) Le
« barbell » se casse : à −30 %, P(−50 %) double (3,6-3,8 % contre ~1,8 % à −15 %) — à ces
profondeurs on ramasse aussi les vrais mourants. (b) L'effectif fond (79-140 obs, cohortes
forward rarissimes → jugement interminable). −15 % est le coude : espérance environ
doublée par rapport à la règle v4, P(−50 %) intacte, effectif suffisant. Ce choix reste un
compromis choisi après coup — le forward le jugera.

Le gradient lui-même corrobore le mécanisme du v4 (§1 du protocole v4) : les chutes **en
excès du bêta** rebondissaient le plus (+11,2 % pour résidu < −10 %). Ici on le retrouve
sans modèle : plus l'écrasement est violent, plus le retour moyen est fort — tant que le
marché purge en même temps.

---

## 5. L'autopsie : mortes vs explosées

Question posée : dans les cases washout, **qui** meurt et **qui** explose, et qu'est-ce qui
les distinguait AU MOMENT de l'entrée ? Cellules larges (prix ≤ 8 $, chute_w ≤ −3 %,
IWM_w < 0, dilution incluse pour la mesurer). **Mortes** = fwd63 ≤ −50 % ; **explosées** =
fwd63 ≥ +100 %. Dossiers SEC issus de l'exploration Epic 4 (couverture 60/61 et 87/88).

| Caractéristique (à l'entrée) | MORTES (7 j / 14 j) | EXPLOSÉES (7 j / 14 j) | Pouvoir séparateur |
|---|---|---|---|
| Checkpoint J+5 > +3 % *(post-entrée)* | 36 % / 43 % | **76 % / 78 %** | le plus net — mais connu après l'achat |
| Cash runway (trimestres) | 9,7 / 14 | **30 / 24** | fort — les mortes brûlaient leur cash |
| Dilution en attente | **63 % / 56 %** | 39 % / 38 % | fort — confirme la règle v4 |
| Profondeur de chute (méd.) | −8,4 % / −14,3 % | **−16,6 % / −22,3 %** | contre-intuitif : les explosées avaient chuté PLUS |
| Ratio volume | **1,57 / 1,39** | 1,14 / 1,12 | les mortes chutaient SUR volume (vraie distribution) |
| CMF | **−0,15 / −0,14** | −0,07 / −0,07 | sortie d'argent 2× plus forte chez les mortes |
| Going-concern | 22 % / 18 % | 15 % / 19 % | **aucun** (volatilité sans direction — conforme v4 A.2) |
| Retard de dépôt | 4 % / 4 % | 15 % / 12 % | aucun (voire inversé) |
| Prix / plus-haut 52 sem. | 0,41 / 0,37 | 0,38 / 0,38 | aucun |

**Portrait de la morte type** : chute modérée mais sur volume élevé et flux sortants
(CMF ≈ −0,15), dilution déposée à la SEC, 2-3 trimestres de cash — elle ne se fait pas
brader, elle se fait *vendre pour de bonnes raisons*.

**Portrait de l'explosée type** : écrasée plus fort mais **sans volume** (pas de vendeur
convaincu), flux quasi neutres, 6+ trimestres de cash — c'est la survente mécanique.

**Deux réserves majeures.** (a) Aucun drapeau n'exclut proprement : GRRR a fait **+558 %
avec une dilution en attente** ; TSSI **+329 % avec les trois drapeaux** (dilution +
going-concern + late filing) ; 38 % des explosées portaient une dilution. Les drapeaux
déplacent des probabilités, ils ne trient pas les individus. (b) **La date d'entrée écrase
le stock-picking** : la cohorte 2025-01-02 est un cimetière (~30 mortes), la cohorte
2025-04-04 une pouponnière (~20 explosées) — voir §2.3 et §10. Listes nominatives
complètes en Annexe A.1/A.2.

Note : le **cash runway** (le plus gros écart mesuré) n'est PAS une règle d'entrée v5 — sa
couverture point-in-time dans nos données n'était que de 27 % (échantillon des queues,
biaisé). Il est enregistré comme piste pour une éventuelle v5.1, à condition de câbler le
calcul EDGAR complet (`edgar.survival_signals`, aujourd'hui stub neutre).

---

## 6. Le profil « explosée type » transformé en règles

### 6.1 Les règles candidates (fixées avant le calcul)

Traduction du portrait §5 en filtres **disponibles au moment de l'entrée** :
CMF > −0,10 (flux pas trop vendeurs) et vol_calm_w ≤ 1,25 (chute sans volume), ajoutés à
la cellule de base (prix ≤ 8 $, sans dilution, chute_w ≤ −15 %, IWM_w < 0). Les seuils ont
été fixés avant de lancer le calcul (moyennes des deux portraits), pas optimisés — mais
ils restent choisis dans la même session : data-mining au second degré, assumé.

### 6.2 Résultats en marché baissier (fwd63 net)

| Fenêtre 7 j (5 dates actives) | n | E nette | Médiane | P(x2) | P(−50 %) | t | k |
|---|---|---|---|---|---|---|---|
| base (chute ≤ −15 %, sans dil.) | 191 | +24,9 % | +19,4 % | 5,2 % | 2,1 % | 0,66 | 5 |
| + CMF > −0,10 | 92 | +31,2 % | +21,9 % | 8,7 % | 0,0 % | 0,39 | 4 |
| + volume calme (≤ 1,25×) | 122 | +26,7 % | +19,2 % | 6,6 % | 2,5 % | 0,18 | 5 |
| **profil complet** | **70** | **+32,3 %** | **+23,1 %** | **8,6 %** | 0,0 % | 0,34 | 4 |

Par date (profil complet 7 j) : 2022-09-29 n=14 +2 % · 2024-10-02 n=1 +4 % ·
2025-01-02 n=2 **−29 %** · 2025-04-04 n=53 **+43 %**.

| Fenêtre 14 j (9 dates actives) | n | E nette | Médiane | P(x2) | P(−50 %) | t | k |
|---|---|---|---|---|---|---|---|
| base | 503 | +9,9 % | +5,4 % | 2,6 % | 1,8 % | −0,01 | 9 |
| + CMF > −0,10 | 222 | +13,3 % | +9,4 % | 4,1 % | 1,4 % | 0,18 | 9 |
| + volume calme | 322 | +13,3 % | +8,9 % | 3,4 % | 0,9 % | 0,14 | 9 |
| **profil complet** | **151** | **+16,5 %** | **+10,9 %** | **5,3 %** | 0,0 % | 0,42 | 9 |

Par date (14 j) : 21-09-29 n=2 −34 % · 21-12-29 n=12 −12 % · 22-06-30 n=11 −2 % ·
22-09-29 n=45 +7 % · 22-12-29 n=7 +29 % · 23-10-02 n=2 +34 % · 24-07-03 n=4 +1 % ·
2025-01-02 n=8 **−29 %** · 2025-04-04 n=60 **+40 %**.

| Fenêtre 21 j (9 dates actives) | n | E nette | Médiane | P(x2) | P(−50 %) | t | k |
|---|---|---|---|---|---|---|---|
| base | 596 | +9,6 % | +5,1 % | 2,9 % | 1,8 % | 0,58 | 9 |
| + CMF > −0,10 | 218 | +12,5 % | +8,5 % | 4,1 % | 1,8 % | 0,38 | 9 |
| + volume calme | 407 | +8,9 % | +4,5 % | 2,5 % | 1,5 % | 0,41 | 9 |
| **profil complet** | **150** | **+13,3 %** | **+10,5 %** | **4,0 %** | 1,3 % | 0,02 | 9 |

Par date (21 j) : 21-09-29 n=2 −13 % · 22-06-30 n=14 −9 % · 22-09-29 n=42 +8 % ·
22-12-29 n=7 +13 % · 23-03-31 n=6 −4 % · 23-10-02 n=5 −5 % · 24-07-03 n=9 +8 % ·
2025-01-02 n=10 **−34 %** · 2025-04-04 n=55 **+37 %**.

**Trois avertissements.** (a) P(−50 %) = 0,0 % est un artefact d'échantillon : sur 70-151
observations avec un vrai taux ~2 %, observer zéro crash est du bruit. (b) La
concentration par date est brutale : avril 2025 domine partout ; janvier 2025 perd ~30 %
partout — le profil **ne protège pas du timing d'entrée dans la purge**. (c) Les t se sont
*effondrés* par rapport à la base (0,34 / 0,42 / 0,02) : chaque filtre réduit le nombre de
dates effectives — statistiquement, le profil est MOINS soutenu que la règle simple, pas
plus. Il est retenu pour son mécanisme cohérent avec l'autopsie, pas pour ses t.

### 6.3 Le miroir haussier (test de la règle 4)

Même profil, condition inversée (IWM_w ≥ 0) :

| Fenêtre | Cellule | n | E nette | Médiane | P(x2) | P(−50 %) | t |
|---|---|---|---|---|---|---|---|
| 7 j | base | 76 | +7,3 % | **−2,6 %** | 5,3 % | **5,3 %** | 0,69 |
| 7 j | profil complet | 15 | +6,3 % | **−1,4 %** | 6,7 % | **6,7 %** | 0,44 |
| 14 j | base | 135 | +4,9 % | **−8,6 %** | 6,7 % | **5,9 %** | 0,73 |
| 14 j | profil complet | 14 | (n trop faible) | | | | |
| 21 j | base | 180 | +3,7 % | **−4,2 %** | 5,0 % | **6,7 %** | 0,44 |
| 21 j | profil complet | 18 | +0,5 % | **−6,1 %** | 5,6 % | 0,0 % | 0,25 |

Toutes les médianes négatives, crashs ×3. La moyenne parfois positive tient à des billets
de loterie isolés (juillet 2024 : n=1, +132 %). Voir §1 — c'est la preuve par le miroir.

---

## 7. Le drapeau d'intensité ⚡ « krach éclair »

### 7.1 Pourquoi

Le §3.2 a montré que les purges éclair (juillet-août 2024 : −10,1 % en 16 séances)
échappent au signal 21 j, et le §3.4 que la fenêtre 3 j est inutilisable comme variante
(un seul épisode mesuré). Le compromis : un **drapeau d'affichage** qui signale « épisode
de type avril 2025 en cours », sans créer de 4ᵉ cohorte à juger.

### 7.2 Calibration du seuil (26 ans d'IWM, 6 563 observations)

Percentiles du rendement 3 séances : p10 = −2,8 % · p5 = −3,8 % · p2 = −5,5 % ·
p1 = −6,7 % · **p0,5 = −8,0 %** · p0,1 = −13,6 %.

Épisodes distincts par seuil (déclenchements à < 10 séances d'écart = même épisode) :

| Seuil 3 j | Épisodes en 26 ans | Fréquence | Contenu |
|---|---|---|---|
| −4 % | 98 | 3,8/an | volatilité ordinaire — bruit |
| −5 % | 62 | 2,4/an | encore fréquent |
| −6 % | 32 | 1,2/an | + SVB mars 2023, jambes sept. 2022 |
| **−8 %** | **14** | **0,5/an** | vagues COVID 2020, pires jambes 2022, yen-carry août 2024, tarifs avril 2025 |
| −10 % | 6 | 0,23/an | 2008 (×2), 2011, mars/juin 2020, avril 2025 |
| −12 % | 4 | 0,15/an | générationnel seulement |

### 7.3 Règle retenue

    ⚡ krach éclair  ⇔  r_3(IWM) ≤ −8 %

−8 % est le percentile 0,5 arrondi : ~1 déclenchement tous les 2 ans, uniquement sur de
vrais événements de stress, y compris celui que le 21 j a raté (5 août 2024). −10 % serait
trop rare pour être jugé de notre vivant statistique ; −6 % trop bavard pour un badge
« sérieux ». **Honnêteté obligatoire** : le seuil est bien calibré en *fréquence* (26 ans),
mais son *payoff* n'est mesuré que sur UN épisode dans nos données (avril 2025). Le
drapeau est purement informatif — il ne modifie ni les cohortes ni leur jugement.

---

## 8. Règles d'entrée v5 (à geler à la signature)

Un titre **qualifie pour la variante w** (w ∈ {7, 14, 21} séances) à la date t si TOUTES :

1. `prix ≤ 8 USD` (héritée v4 — les explosions historiques cotaient 6,50 $ en médiane) ;
2. `dilution_flag == False` — EDGAR point-in-time : aucun dépôt S-1/S-3/F-1/F-3/424B dans
   les 180 jours ; EDGAR muet (None) ⇒ non qualifié (héritée v4) ;
3. `r_w(titre) ≤ −15 %` — chute sur la fenêtre (§4) ;
4. `r_w(IWM) < 0` — marché en baisse sur la MÊME fenêtre (§1, §6.3) ;
5. `CMF_20 > −0,10` — flux pas franchement vendeurs (§5, §6) ;
6. `vol_calm_w ≤ 1,25` — chute sans volume, base 60 séances (§5, §6).

Affichage : les trois variantes sont calculées à chaque scan et présentées via un
**sélecteur 7 j / 14 j / 21 j** dans l'interface ; le drapeau ⚡ (§7) s'affiche en tête
quand `r_3(IWM) ≤ −8 %`. Aucune variante n'est « la bonne » a priori : ce sont trois
paris pré-déclarés sur le même mécanisme à trois échelles de temps.

Champs observationnels (jamais des règles) : bêta/résidu (hérités v4), checkpoint J+5 à
+3 % (héritée v4 A.6 — information de suivi, jamais un ordre de vente : les stops
détruisent le rendement mesuré du panier).

## 9. Schéma de jugement (forward — Validation D)

- Horizon : fwd63 net (décote 1 %), cohortes **non chevauchantes** uniquement (une cohorte
  jugée tous les 63 jours de bourse au plus, par variante).
- **Multiplicité déclarée** : trois variantes = trois chances de faux positif. La variante
  **primaire est 14 j** (meilleur compromis assise/signal mesuré : 9 dates, n=151,
  médiane +10,9 %) ; 7 j et 21 j sont **secondaires**. La méthode ne sera déclarée
  « soutenue » que si la variante primaire passe ses critères ; une secondaire qui passe
  seule = anecdote documentée, pas une validation.
- Critères de succès par variante (identiques v4 §4) : (a) espérance nette ≥ 0 ET
  (b) P(fwd63 ≥ +100 %) ≥ P(fwd63 ≤ −50 %), sur ≥ 4 fenêtres non chevauchantes pour une
  première lecture (≥ 12 mois), ≥ 8 pour le jugement final (~24 mois).
- Critères d'échec (kill) : espérance nette < 0 sur ≥ 8 fenêtres non chevauchantes, ou
  t < 1 au jugement final.
- Interdits absolus : re-régler un seuil après avoir vu un résultat forward (= v5.1 +
  chrono remis à zéro) ; re-lancer l'étude historique « pour vérifier » ; promouvoir une
  variante secondaire en primaire après coup.

## 10. Limites connues (à relire avant toute décision)

1. **Le timing intra-purge n'est pas résolu.** Le signal s'allume tôt dans les grandes
   purges (§3.2 : −26 % de chute restante) ; le profil ne protège pas du scénario janvier
   2025. Piste non retenue (post-hoc) : étalement des entrées, condition de profondeur du
   marché lui-même.
2. **Le clignotement** (§3.3) : ~40 % des périodes actives durent 1-2 séances et
   produiront des cohortes « de bruit ». Assumé, non filtré.
3. **Biais du survivant** (§2.1) : toutes les probabilités de crash sont des planchers.
4. **Data-mining cumulatif** : 4ᵉ session d'exploration du projet, dizaines de cellules
   scannées, seuils choisis après lecture des réponses. Les chiffres de ce document ne
   sont PAS des espérances — ce sont les raisons pour lesquelles on regarde. Le forward
   juge.
5. **Concentration par épisodes** : l'essentiel du signal mesuré vient de 2-3 purges
   (sept.-oct. 2022, avril 2025). k effectif ≈ une poignée d'épisodes, pas 150 titres.

---

## Annexe A — tables nominatives et découpage complet

### A.1 Mortes (fwd63 ≤ −50 %) — cellule 14 j, flags D=dilution G=going-concern L=late-filing

2025-01-02 NUAI 4,89 $ −6 % → −85 % [D] · 2023-10-02 ACRS 6,49 $ −15 % → −84 % [G] ·
2025-01-02 LPRO 5,71 $ −7 % → −82 % · 2025-01-02 ANVS 5,11 $ −14 % → −74 % [DG] ·
2025-04-04 IBIO 3,23 $ −34 % → −74 % [DG] · 2022-12-29 ESPR 5,86 $ −5 % → −73 % ·
2021-09-29 HEPS 6,46 $ −12 % → −70 % [D] · 2025-01-02 CGC 2,88 $ −12 % → −68 % [DG] ·
2025-01-02 MGNX 3,30 $ −3 % → −68 % · 2022-06-30 SLQT 2,48 $ −14 % → −68 % [GL] ·
2024-07-03 ALXO 5,60 $ −34 % → −67 % · 2024-07-03 STTK 3,70 $ −44 % → −66 % [D] ·
2025-01-02 CAN 2,22 $ −17 % → −66 % [D] · 2022-06-30 TUYA 2,41 $ −14 % → −65 % [D] ·
2025-01-02 LXEO 6,67 $ −13 % → −65 % [D] · 2025-01-02 MRVI 5,49 $ −5 % → −65 % ·
2025-01-02 CCCC 3,66 $ −22 % → −64 % [D] · 2021-12-29 AKBA 2,29 $ −15 % → −64 % ·
2025-01-02 AIRS 5,42 $ −12 % → −63 % · 2022-09-29 HIVE 3,89 $ −24 % → −63 % [D] ·
2025-01-02 INDI 4,21 $ −7 % → −62 % · 2025-01-02 GERN 3,60 $ −10 % → −62 % ·
2025-01-02 IOVA 7,79 $ −9 % → −61 % · 2025-01-02 ZNTL 3,00 $ −14 % → −61 % [G] ·
2023-10-02 PROK 4,30 $ −44 % → −60 % [D] · 2025-04-04 LUNG 6,76 $ −13 % → −60 % ·
2023-10-02 BW 3,60 $ −25 % → −59 % · 2021-12-29 CRDF 5,93 $ −3 % → −58 % [D] ·
2025-01-02 CDXS 5,00 $ −14 % → −57 % · 2025-01-02 PRQR 2,74 $ −19 % → −57 % [D] ·
2025-04-04 HAIN 3,76 $ −6 % → −57 % · 2022-09-29 WBX 7,67 $ −12 % → −57 % [D] ·
2025-01-02 ZURA 2,35 $ −6 % → −56 % [D] · 2021-09-29 PBYI 7,03 $ −4 % → −56 % [D] ·
2022-09-29 SLDP 5,29 $ −20 % → −56 % [D] · 2025-04-04 OMER 7,06 $ −17 % → −56 % [G] ·
2025-01-02 SPCE 6,06 $ −7 % → −55 % [D] · 2025-01-02 HIVE 3,09 $ −22 % → −55 % [D] ·
2022-06-30 SLAI 6,20 $ −70 % → −54 % [D] · 2025-01-02 JMIA 3,90 $ −18 % → −54 % [D] ·
2022-09-29 AREC 2,66 $ −20 % → −54 % [D] · 2025-01-02 SGMT 4,49 $ −5 % → −54 % [D] ·
2025-01-02 PRME 2,99 $ −5 % → −53 % [D] · 2025-01-02 FLNA 2,75 $ −4 % → −53 % ·
2023-10-02 EOSE 2,22 $ −16 % → −53 % [DG] · 2025-01-02 FDMT 5,83 $ −16 % → −52 % ·
2025-01-02 QTTB 3,45 $ −42 % → −52 % [DG] · 2022-09-29 HLLY 4,27 $ −29 % → −52 % [D] ·
2025-01-02 CABA 2,33 $ −24 % → −52 % · 2025-01-02 AMPY 6,10 $ −4 % → −52 % ·
2022-06-30 PACK 7,00 $ −32 % → −51 % · 2025-01-02 LRMR 4,01 $ −38 % → −51 % [G] ·
2021-12-29 HYPR 7,01 $ −30 % → −51 % [DL] · 2022-09-29 IVVD 3,03 $ −34 % → −51 % [D] ·
2021-12-29 KLTR 3,71 $ −15 % → −50 % [D] · 2025-01-02 XRX 7,67 $ −4 % → −50 %

### A.2 Explosées (fwd63 ≥ +100 %) — cellule 14 j

2025-04-04 SGMT 2,08 $ −45 % → **+340 %** · 2025-04-04 TSSI 6,24 $ −33 % → **+329 %** [DGL] ·
2024-07-03 CAPR 4,83 $ −5 % → +242 % [DG] · 2025-04-04 BKSY 6,81 $ −27 % → +231 % ·
2023-10-02 EYPT 7,80 $ −31 % → +189 % · 2025-04-04 BBAI 2,85 $ −18 % → +166 % [DL] ·
2022-12-29 RRGB 5,60 $ −23 % → +156 % · 2025-04-04 PCT 5,99 $ −20 % → +143 % [DGL] ·
2025-04-04 APPS 2,35 $ −39 % → +140 % · 2024-07-03 BMEA 4,35 $ −6 % → +133 % [G] ·
2025-04-04 LFMD 5,16 $ −10 % → +132 % · 2023-10-02 MGNX 4,48 $ −9 % → +127 % ·
2025-04-04 DOMO 6,64 $ −22 % → +125 % · 2025-04-04 PRCH 5,64 $ −10 % → +121 % [G] ·
2025-04-04 PSNL 3,11 $ −18 % → +121 % [D] · 2025-04-04 FTK 6,60 $ −35 % → +120 % ·
2022-06-30 TH 5,71 $ −15 % → +118 % · 2025-04-04 EYPT 4,61 $ −30 % → +116 % [D] ·
2024-07-03 RIGL 7,73 $ −23 % → +115 % · 2025-04-04 ORIC 4,88 $ −38 % → +114 % ·
2025-04-04 ENVX 6,31 $ −23 % → +113 % [D] · 2025-04-04 RAIL 4,64 $ −29 % → +112 % [D] ·
2025-04-04 ALTG 4,08 $ −22 % → +111 % · 2025-04-04 BBBY 3,94 $ −30 % → +109 % ·
2022-09-29 EVER 6,83 $ −22 % → +108 % · 2025-04-04 EVLV 2,85 $ −10 % → +107 % [L] ·
2025-04-04 SEPN 5,48 $ −14 % → +107 % [D] · 2025-04-04 IE 4,74 $ −25 % → +106 % [DG] ·
2022-09-29 EH 4,13 $ −34 % → +104 % · 2025-04-04 AMLX 3,43 $ −9 % → +103 % [D] ·
2024-07-03 CRMD 4,13 $ −17 % → +100 % [D] · 2024-07-03 BVS 5,89 $ −13 % → +100 %

(NB : la cellule 7 j — 28 mortes / 33 explosées — recoupe largement la 14 j ; GRRR
2024-10-02, +558 % avec dilution en attente, n'apparaît que dans la cellule 7 j.)

### A.3 Les 32 jambes de baisse IWM (zigzag 5 %, 2020-2026)

| Pic | Creux | Prof. | Durée | 21j<0 (jours) |
|---|---|---|---|---|
| 2020-09-02 | 2020-09-23 | −8,7 % | 14 | 14 |
| 2020-10-12 | 2020-10-30 | −6,5 % | 14 | 0 |
| 2021-02-09 | 2021-03-04 | −6,7 % | 16 | 1 |
| 2021-03-15 | 2021-03-24 | −9,5 % | 7 | 2 |
| 2021-04-28 | 2021-05-12 | −7,4 % | 10 | 5 |
| 2021-06-08 | 2021-07-19 | −8,9 % | 28 | 10 |
| 2021-08-11 | 2021-08-19 | −5,3 % | 6 | 2 |
| 2021-09-02 | 2021-09-20 | −5,2 % | 11 | 3 |
| 2021-11-08 | 2021-12-01 | −12,1 % | 16 | 4 |
| 2021-12-08 | 2021-12-20 | −5,7 % | 8 | 9 |
| 2022-01-03 | 2022-01-27 | −15,0 % | 17 | 16 |
| 2022-02-09 | 2022-02-23 | −6,6 % | 9 | 10 |
| 2022-03-02 | 2022-03-14 | −5,6 % | 8 | 7 |
| 2022-03-29 | 2022-05-11 | −19,4 % | 30 | 21 |
| 2022-06-07 | 2022-06-16 | −13,9 % | 7 | 4 |
| 2022-08-15 | 2022-09-06 | −11,3 % | 15 | 6 |
| 2022-09-12 | 2022-09-26 | −13,0 % | 10 | 11 |
| 2022-10-04 | 2022-10-14 | −5,2 % | 8 | 9 |
| 2022-12-02 | 2022-12-28 | −8,9 % | 17 | 12 |
| 2023-02-02 | 2023-03-23 | −13,8 % | 34 | 18 |
| 2023-07-31 | 2023-10-27 | −18,0 % | 63 | 56 |
| 2023-12-27 | 2024-01-17 | −7,5 % | 13 | 2 |
| 2024-03-28 | 2024-04-18 | −8,3 % | 14 | 10 |
| 2024-07-16 | 2024-08-07 | −10,1 % | 16 | **0** |
| 2024-08-26 | 2024-09-06 | −5,7 % | 8 | 4 |
| 2024-11-11 | 2024-11-15 | −5,5 % | 4 | 0 |
| 2024-11-25 | 2025-01-10 | −10,3 % | 30 | 19 |
| 2025-01-21 | 2025-03-13 | −13,8 % | 36 | 17 |
| 2025-03-24 | 2025-04-08 | −16,3 % | 11 | 12 |
| 2025-07-23 | 2025-08-01 | −5,2 % | 7 | 1 |
| 2025-10-15 | 2025-11-20 | −8,5 % | 26 | 14 |
| 2026-01-22 | 2026-03-30 | −11,0 % | 46 | 29 |

### A.4 Fenêtre 3 séances — les chiffres écartés (§3.4)

Grille de profondeur (IWM 3 j < 0, 9/18 dates, sans dilution) : −3 % : n=781, E +10,2 %,
t 0,50 · −10 % : n=246, E +20,0 %, t 0,53 · −15 % : n=84, E +23,2 %, **t −1,33** ·
−20 % : n=37, E +19,4 %, t −0,65. Profil complet : n=22, E +41,2 %, médiane +27,5 %,
P(x2) 18,2 % — dont 18 obs sur 22 issues du seul 2025-04-04.

---

*Signé par le propriétaire (patw47) le 2026-07-09 — §8-§9 contraignants, chrono forward lancé.*
