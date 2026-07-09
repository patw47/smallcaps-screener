# Guide de lecture de l'interface

Ce document explique **ce qu'on voit exactement à l'écran**, étage par étage, en langage
simple. Les définitions détaillées de chaque terme sont dans [glossaire.md](glossaire.md) ;
les chiffres cités viennent tous des tables gelées de
[backtest_protocol_v4.md](backtest_protocol_v4.md) (Annexe A) et de
[backtest_protocol_v2.md](backtest_protocol_v2.md) (§9).

**Le principe général** : le screener ne dit jamais « achète ». Il dit où regarder en
premier, et pourquoi. Un seul groupe affiché a une espérance historique positive (la
cohorte v4) ; tout le reste est de la matière à recherche.

---

## L'en-tête

- **Pastille « Marché : IWM 21 j »** : la variation de l'indice small caps (IWM) sur les
  21 dernières séances, soit environ un mois de bourse. **Rouge (négatif) = marché
  baissier → la méthode v4 est active. Vert (positif) = la méthode est en pause** — c'est
  la règle 4 du protocole, pas un choix d'humeur.
- **« ▶ Scanner le marché »** : relance un scan complet de l'univers (~2 500 small/micro
  caps US).

Juste en dessous, le bandeau **« En un coup d'œil »** résume la journée en une phrase :
soit « N titres qualifiés v4, commencer par X », soit « pas de cohorte aujourd'hui,
la méthode est en pause ».

---

## Étage 1 — Cohorte v4 du jour

### Ce que c'est

Les titres qui passent, **le jour même**, les 4 règles gelées du protocole signé
(`backtest_protocol_v4.md` §2). Un titre qualifie si **toutes** sont vraies :

1. **Prix ≤ 8 $** — les explosions historiques cotaient 6,50 $ en médiane, contre
   13 $ pour les autres titres.
2. **Aucune dilution en attente** — aucun dépôt à la SEC préparant une émission de
   nouvelles actions (formulaires S-1/S-3/F-1/F-3/424B) dans les 180 derniers jours.
   Si la donnée SEC est indisponible, le titre est disqualifié (prudence par défaut).
3. **Chute d'au moins 3 % sur 1 mois** — on achète des soldes, pas des sommets.
4. **Marché lui-même en baisse** (IWM 21 j < 0) — un marché en purge brade des titres
   sans raison propre ; un titre qui s'effondre seul dans un marché haussier a de
   vraies casseroles.

**Ces 4 règles sont les seuls critères d'entrée.** Elles sont « gelées » : aucun réglage
possible sans nouvelle version du protocole, ce qui remettrait le compteur de validation
à zéro.

### D'où viennent les règles (et pourquoi pas d'autres)

L'Annexe A du protocole est la preuve mesurée, pas un critère de sélection :

- **A.1 (portrait-robot)** décrit à quoi ressemblaient les 161 explosions historiques.
  C'est une photo du passé — aucun titre n'est « testé contre A.1 ».
- **A.2 (explosions vs crashs)** explique pourquoi la règle dilution existe (le drapeau
  est 2,1× plus fréquent avant un crash) et pourquoi les drapeaux de détresse
  (going-concern, retard de dépôt) ne sont **pas** des règles : ils annoncent un gros
  mouvement **sans en choisir le sens** — ils ne peuvent ni sélectionner ni exclure.
- **A.3 (l'entonnoir)** fournit les chiffres du bandeau (voir ci-dessous).
- **A.4 (carré marché × titre)** justifie la règle 4 : « titre en baisse dans un marché
  en baisse » est la seule case à espérance positive.

### Le bandeau de chiffres

| Chiffre affiché | Ce qu'il veut dire |
|---|---|
| **Espérance hist. 3 mois : +5,9 %** | Gain moyen par titre à 3 mois, coûts déduits, mesuré sur 2021-2026 (médiane : +1,6 %). |
| **P(doubler en 3 mois) : 2,0 %** | Un titre au hasard : 0,8 %. Le filtre multiplie par ~2,5. |
| **P(perdre −50 %) : 1,9 %** | Un titre au hasard : 3,8 %. Le filtre divise par 2. Rare cas où doubler devient aussi probable que crasher. |
| **t = 0,47 — non significatif** | Le test statistique ne peut pas exclure que le +5,9 % soit de la chance (il faudrait t ≥ 2). **C'est LA raison d'être de la validation forward** : seules les données réelles à venir trancheront (été 2027). |
| **4/4 règles gelées actives** | Aucune règle n'a été modifiée depuis la signature. |

L'encadré jaune le rappelle : chiffres historiques, survivants seuls, seuils choisis
a posteriori — **un plafond d'espoir, pas une promesse**.

### Les cartes de titres

Chaque titre qualifié a une carte :

- **L'ordre d'affichage** suit la **profondeur de survente** (le « résidu bêta ») : de
  combien le titre a chuté EN PLUS de ce que la baisse du marché explique.
  Historiquement, plus cette part propre est profonde, meilleur a été le rebond
  (+11,2 % contre +2,9 %). C'est un ordre de lecture, **jamais une règle d'entrée**
  (Annexe A.5, observationnel).
- Le premier titre porte « **à étudier en premier** » et une phrase « Pourquoi lui ».
- Les **4 pastilles** en bas de carte montrent chaque règle et la marge au seuil
  (ex. « prix 4,20 $ / seuil 8 $ »). Les marges sont affichées pour information,
  jamais utilisées pour reclasser.
- Le bloc « **Avant tout achat** » : lire les 8-K récents (le catalyseur est dans les
  news, pas dans nos chiffres), vérifier l'écart achat/vente, dimensionner pour
  survivre à −50 %.

### Quand la cohorte est vide

« Pas de cohorte aujourd'hui » n'est **pas une panne** : la méthode n'achète que pendant
les soldes générales (marché baissier). En attendant, la **pré-liste** montre les titres
qui passent les règles-titre (prix, chute) et n'attendent que la condition marché — la
dilution n'y est pas encore vérifiée (elle le sera le jour où ils qualifient).

---

## Étage 2 — Suivi des cohortes passées

Le journal de toutes les cohortes enregistrées depuis le 6 juillet 2026, ligne par ligne :

- **Entré le / prix d'entrée / aujourd'hui** : la performance réelle depuis la
  qualification (J+n).
- **Checkpoint** : point de contrôle mesuré une semaine (5 séances) après l'entrée.
  Au-dessus de +3 %, les titres ont historiquement 4× plus doublé et 2× moins crashé ;
  en dessous, l'inverse — mais 31 % des explosions étaient encore négatives à ce stade.
- **Position** : où en est le titre (au-dessus / sous le seuil / explosion / crash /
  fenêtre 63 j close).
- **Probabilités conditionnelles** : la traduction chiffrée de la position.

**Information, jamais un ordre de vente** : vendre automatiquement sous le seuil détruit
le rendement mesuré du panier (+1,4 % → −0,4 %), parce que les stops coupent la réversion.

Cet étage est le cœur de la **validation forward (« Validation C »)** : c'est lui qui
jugera la méthode à l'été 2027, selon des critères écrits à l'avance dans le protocole.

---

## Étage 3 — Zones extrêmes (🔥 Phénix · 🚀 Fusée)

### Ce que c'est

Les titres qui correspondent aux deux profils de l'ancienne hypothèse v2 :

- **🚀 Fusée** : momentum extrême + explosion de volume — l'action déjà brûlante.
- **🔥 Phénix** : action massacrée (loin de son plus-haut annuel), volatilité comprimée,
  premiers signes de stabilisation.

### Pourquoi « non validé » sur chaque badge

Les deux profils ont été testés une fois pour toutes (« Validation A » du protocole v2,
jugée le 5 juillet 2026) et ont **échoué** :

- **Fusée** : double aussi souvent qu'un titre au hasard (1,03×) — aucun avantage.
  Espérance : −9,6 %.
- **Phénix** : les explosions y sont bien 4,6× plus fréquentes… mais les chutes de
  moitié 2,3× aussi, et l'espérance nette est de **−11 %**.

C'est pourquoi cet étage s'appelle « à étudier, pas à acheter » : ces zones concentrent
les explosions ET les crashs. C'est la liste des dossiers où une recherche humaine
(news, refinancement, essais cliniques) peut faire la différence que nos chiffres ne
font pas.

### Le dossier de risque

Sur chaque carte : les drapeaux factuels tirés des dépôts SEC — **détresse EDGAR**
(going-concern, retard de dépôt : volatilité extrême, sans direction), **dilution en
attente** (seul drapeau clairement défavorable) — et le bouton **« Analyser avec
Claude »** qui lit le dossier et résume.

---

## Ce que l'écran ne dit jamais

- « Achète » ou « vends » — aucune ligne de l'interface n'est un conseil
  d'investissement.
- Une promesse de rendement : tout chiffre historique est un plafond d'espoir
  (données survivantes, seuils choisis après coup), et le t = 0,47 rappelle que même
  le +5,9 % peut être du bruit. Le juge de paix est le forward, été 2027.
