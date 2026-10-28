"""
Dérive les patterns grep (ERE) des valeurs PRIVÉES depuis la config locale.

Utilisé par scripts/check_edge.sh sur les cibles PROSE (frontend, docs, README) :
les valeurs ne sont JAMAIS écrites en dur dans un fichier versionné — elles sont
lues de config/local.yml au moment du check. Toute valeur décimale d'une section
autre que les sections de fonctionnement (filters, finviz, study) est privée.

Formes émises, par valeur :
  - virgule française :        « 0,15 » / « −0,15 »
  - pourcentage comparé :      « ≥ 15 % », « −15 % »
  - multiplicateur :           « 1,25× »
  - monétaire comparé :        « ≤ 8 $ »
Les décimales à point nues (0.15…) ne sont pas émises : trop génériques.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

OPERATIONAL = {"filters", "finviz", "study"}
GENERIC = {0.0, 1.0, -1.0}
# Clés dont les valeurs sont des rendements en points de % (earnings.net, Epic 15 S4) : pas de
# forme multiplicateur — un « N× » d'un post-mortem public n'est pas la fuite d'un rendement en points.
PERCENT_POINTS = {"net"}


def value_patterns(value: float, mult: bool = True) -> set[str]:
    """Formes d'écriture (ERE) d'une valeur dans de la prose publique. Le COMPARATEUR est
    exigé devant un pourcentage ou un montant, sinon « 0,8 % des titres » rougirait."""
    a = abs(float(value))
    if a in (0.0, 1.0):
        return set()
    dec = f"{a:g}"
    comma = dec.replace(".", ",") + "0*"     # la config écrit 0.1, la prose « 0,10 »
    pct = a * 100
    pats: set[str] = set()
    if "." in dec:
        pats.add(rf"(^|[^0-9,.]){comma}($|[^0-9])")
        if a > 1 and mult:
            pats.add(rf"{dec.replace('.', '[.,]')}\s*[x×]")
        if not mult:  # rendement en points : « 1.2 pt » / « 1,20 % », point ou virgule
            pats.add(rf"(^|[^0-9.,]){dec.replace('.', '[.,]')}0*\s*(pt|%)")
    if a < 1 and pct == int(pct):
        pats.add(rf"[−≥≤<>-]\s*{int(pct)}\s*%")
    num = comma if "." in dec else dec
    pats.add(rf"[≤<>≥]\s*{num}\s*\$")
    pats.add(rf"[≤<>≥]\s*\$\s*{num}($|[^0-9])")
    return pats


def _walk(node: object, parent: str = ""):
    """(clé parente du dict de valeurs, valeur) de chaque décimale non générique."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, str(key) if isinstance(value, dict) else parent)
    elif isinstance(node, float) and node not in GENERIC:
        yield parent, node


def patterns(config_path: Path) -> list[str]:
    raw = yaml.safe_load(config_path.read_text()) or {}
    pats: set[str] = set()
    for section, body in raw.items():
        if section not in OPERATIONAL:
            for parent, value in _walk(body or {}):
                pats |= value_patterns(value, mult=parent not in PERCENT_POINTS)
    return sorted(pats)


if __name__ == "__main__":
    for p in patterns(Path(sys.argv[1])):
        print(p)
