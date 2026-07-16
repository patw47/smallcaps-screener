# Guide de lecture de l'interface

Ce document explique **ce qu'on voit exactement à l'écran**, étage par étage, en langage
simple. Les définitions détaillées de chaque terme sont dans [glossaire.md](glossaire.md).

Depuis l'Epic 6 S2, **tous les chiffres gelés des protocoles v4/v5** (seuils des règles,
bandeaux de statistiques, textes d'infobulles associés) sont servis à l'interface par
l'API depuis la config privée — ils n'apparaissent ni dans ce document ni dans le code
public. Les chiffres v2 cités plus bas restent publics (post-mortem versionné,
[backtest_protocol_v2.md](backtest_protocol_v2.md) §9).

**Le principe général** : le screener ne dit jamais « achète ». Il dit où regarder en
premier, et pourquoi. Un seul groupe affiché a une espérance historique positive (la
cohorte v4) ; tout le reste est de la matière à recherche.

---

## L'en-tête

- **Pastille « Marché : IWM »** avec son **sélecteur de fenêtre** : la variation de
  l'indice small caps (IWM) sur la fenêtre choisie (trois fenêtres pré-déclarées par le
  protocole v5 ; la v4 garde sa propre fenêtre). **Rouge (négatif) = marché baissier →
  la méthode s'applique. Vert (positif) = elle est en pause** — c'est une règle du
  protocole, pas un choix d'humeur. Un badge **⚡ krach éclair** peut s'y ajouter les
  jours de purge violente (information de contexte, jamais une règle d'entrée).
- **« ▶ Scanner le marché »** : relance un scan complet de l'univers (~2 500 small/micro
  caps US).

Juste en dessous, le bandeau **« En un coup d'œil »** résume la journée en une phrase :
soit « N titres qualifiés v4, commencer par X », soit « pas de cohorte aujourd'hui,
la méthode est en pause ».

---

## Étage 1 — Cohorte v4 du jour

### Ce que c'est

Les titres qui passent, **le jour même**, les 4 règles gelées du protocole v4 signé
(archivé hors repo). Un titre qualifie si **toutes** sont vraies :

1. **Prix sous le plafond du protocole** — la zone historique des gros mouvements est
   bon marché.
2. **Aucune dilution en attente** — aucun dépôt à la SEC préparant une émission de
   nouvelles actions (formulaires S-1/S-3/F-1/F-3/424B) dans les 180 derniers jours.
   Si la donnée SEC est indisponible, le titre est disqualifié (prudence par défaut).
3. **Chute minimale sur ~1 mois** — on achète des soldes, pas des sommets.
4. **Marché lui-même en baisse** sur la fenêtre du protocole — un marché en purge brade
   des titres sans raison propre ; un titre qui s'effondre seul dans un marché haussier
   a de vraies casseroles.

Les seuils exacts sont affichés sur chaque carte (servis par l'API). **Ces 4 règles sont
les seuls critères d'entrée.** Elles sont « gelées » : aucun réglage possible sans
nouvelle version du protocole, ce qui remettrait le compteur de validation à zéro.

### D'où viennent les règles (et pourquoi pas d'autres)

L'annexe du protocole est la preuve mesurée, pas un critère de sélection :

- **Le portrait-robot** décrit à quoi ressemblaient les explosions historiques. C'est
  une photo du passé — aucun titre n'est « testé contre » elle.
- **Explosions vs crashs** explique pourquoi la règle dilution existe (drapeau plus
  fréquent avant un crash) et pourquoi les drapeaux de détresse (going-concern, retard
  de dépôt) ne sont **pas** des règles : ils annoncent un gros mouvement **sans en
  choisir le sens** — ils ne peuvent ni sélectionner ni exclure.
- **L'entonnoir** fournit les chiffres du bandeau (voir ci-dessous).
- **Le carré marché × titre** justifie la règle marché : « titre en baisse dans un
  marché en baisse » est la seule case à espérance positive.

### Le bandeau de chiffres

Cinq tuiles, toutes servies par l'API : **espérance historique à 3 mois**, **P(doubler)**,
**P(perdre −50 %)**, **t-stat** (non significatif — c'est LA raison d'être de la
validation forward), et **« 4/4 règles gelées actives »** (aucune règle modifiée depuis
la signature). Chaque tuile a son infobulle.

L'encadré jaune le rappelle : chiffres historiques, survivants seuls, seuils choisis
a posteriori — **un plafond d'espoir, pas une promesse**.

### Les cartes de titres

Chaque titre qualifié a une carte :

- **L'ordre d'affichage** suit la **profondeur de survente** (le « résidu bêta ») : de
  combien le titre a chuté EN PLUS de ce que la baisse du marché explique.
  Historiquement, plus cette part propre est profonde, meilleur a été le rebond.
  C'est un ordre de lecture, **jamais une règle d'entrée** (observationnel).
- Le premier titre porte « **à étudier en premier** » et une phrase « Pourquoi lui ».
- Les **4 pastilles** en bas de carte montrent chaque règle, la valeur du titre et le
  seuil du protocole (servi par l'API). Les marges sont affichées pour information,
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

## Étage 1 bis — Cohorte v5 (multi-fenêtres)

La généralisation du même mécanisme à **trois fenêtres pré-déclarées** (protocole v5,
archivé hors repo), pilotée par le sélecteur de l'en-tête. Six règles gelées par titre
(prix, dilution, profondeur de chute sur la fenêtre, marché baissier sur la MÊME
fenêtre, flux d'argent CMF, volume calme) — chaque carte affiche ses six pastilles avec
les seuils servis par l'API. Le bandeau de chiffres est propre à chaque fenêtre, et la
**variante primaire** (désignée d'avance pour le jugement) est marquée dans le titre de
section. Le suivi « Validation D » enregistre chaque entrée (fenêtre, date, prix).

---

## Étage 2 — Suivi des cohortes passées

Le journal de toutes les cohortes enregistrées depuis le 6 juillet 2026, ligne par ligne :

- **Entré le / prix d'entrée / aujourd'hui** : la performance réelle depuis la
  qualification (J+n).
- **Checkpoint** : point de contrôle mesuré quelques séances après l'entrée (jour et
  seuil servis par l'API). Au-dessus du seuil, les fréquences historiques penchaient
  nettement mieux ; en dessous, l'inverse — mais une part substantielle des explosions
  était encore négative à ce stade.
- **Position** : où en est le titre (au-dessus / sous le seuil / explosion / crash /
  fenêtre close).
- **Probabilités conditionnelles** : la traduction chiffrée de la position (servie par
  l'API).

**Information, jamais un ordre de vente** : vendre automatiquement sous le seuil détruit
le rendement mesuré du panier, parce que les stops coupent la réversion.

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
  (données survivantes, seuils choisis après coup), et le t-stat affiché rappelle que
  même l'espérance positive peut être du bruit. Le juge de paix est le forward, été 2027.
