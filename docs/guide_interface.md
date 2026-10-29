# Guide de lecture de la page

Ce document explique ce qu'on voit à l'écran, section par section, en langage simple. Les
termes sont définis dans [glossaire.md](glossaire.md). Aucune valeur mesurée n'est écrite ici :
le gain mesuré est servi à la page par l'API depuis la configuration privée.

**Le principe** : la page ne dit jamais « achète ». Elle liste les sociétés dont le dernier
résultat trimestriel a nettement dépassé leur habitude, puis ce qui s'est passé ensuite. Elle ne
compare pas ses propres chiffres à une promesse : le journal montre ce que les alertes ont réellement
rapporté.

## Accès

La page est servie sur le VPS et lisible **uniquement par tunnel SSH** (rien n'est exposé à
Internet : elle affiche le gain mesuré, qui est privé) :

```bash
ssh -N -L 8019:127.0.0.1:8019 hetzner-vps    # puis http://localhost:8019
```

En local, `http://localhost:5173` montre la page avec un journal vide (le vrai journal vit sur le VPS).
Le bouton **FR / EN** de l'en-tête change la langue sans recharger la page ; le choix est mémorisé.

## 1. En-tête et introduction

Titre, choix de la langue, puis un paragraphe : une alerte part quand une société publie un
bénéfice trimestriel nettement supérieur à celui du même trimestre de l'année précédente,
rapporté à la variabilité habituelle de ses résultats (surprise saisonnière, quintile supérieur).
Les drapeaux de risque sont une information : ils n'écartent aucune alerte.

## 2. Publications du jour

Les alertes de la dernière séance close, dans le même tableau que le journal. Si aucune
publication n'a atteint le quintile supérieur, la page l'écrit pour la séance concernée.

## 3. Journal

- **Rendement réalisé moyen par horizon** : pour 5, 21 et 63 séances, le nombre d'alertes échues,
  le rendement moyen, celui d'IWM sur les mêmes dates, l'écart, le nombre d'alertes « sans
  cours » et le nombre « en attente ». Un horizon avec peu d'alertes échues n'est pas une
  statistique : il faut lire le nombre avant la moyenne.
- **Gain mesuré sur l'historique** (bloc en pointillés, seulement si la configuration le sert) :
  mesure d'une autre nature que le rendement réalisé (écart avec les titres comparables, net du
  spread). Les deux chiffres ne se comparent pas.
- **Tableau de toutes les alertes** : titre (lien Finviz), séance de publication, jour d'entrée,
  surprise (SUE), un rendement par horizon avec celui d'IWM dessous, et les drapeaux de risque.
  Plus récent d'abord.

## Lire une case

| Case | Sens |
|---|---|
| un pourcentage, IWM dessous | rendement réalisé écrit par le job du soir |
| en attente | la séance d'horizon n'est pas encore close |
| sans cours | la séance d'horizon est passée, aucun cours (retrait de la cote, cotation suspendue) |

## Drapeaux de risque

Une ligne par drapeau, rouge si la gravité est élevée, orange sinon, avec la date du fait quand
elle existe ; l'infobulle explique. « Aucun » : aucun fait EDGAR relevé. Un drapeau n'écarte pas
l'alerte.
