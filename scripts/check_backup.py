"""
Double des instantanés hors du volume (Epic 11 S1).

Deux vérifications sur le répertoire de destination :

1. **Complétude** — tout instantané présent à la source a sa copie à destination,
   même nom et même taille. Un manquant nomme le fichier et fait rougir la cible.
2. **Non-régression** — les empreintes relevées au passage PRÉCÉDENT sont retrouvées
   à l'identique, et le nombre de fichiers ne décroît jamais. L'inventaire est écrit
   à destination (`.manifest.tsv`, hors instantanés) : le répertoire étant exclu du
   versionnement, un différentiel de dépôt serait vide par construction et incapable
   de virer au rouge. C'est cet inventaire qui donne au gate sa mémoire.

Tourne dans le conteneur, seul à voir à la fois le volume et le montage hôte :
`make check-backup`.
"""
import hashlib
import sys
from pathlib import Path

from screener_backend import HISTORY_DIR
from track import BACKUP_DIR

MANIFEST_NAME = ".manifest.tsv"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    entries = {}
    for line in path.read_text().splitlines():
        name, _, digest = line.partition("\t")
        if name and digest:
            entries[name] = digest
    return entries


def main() -> int:
    if not BACKUP_DIR.is_dir():
        print(f"check-backup ÉCHEC — destination absente : {BACKUP_DIR} (montage hôte manquant ?)")
        return 1

    sources = sorted(Path(HISTORY_DIR).glob("*.json"))
    copies = {p.name: p for p in sorted(BACKUP_DIR.glob("*.json"))}

    missing = [
        f"{s.name} ({'absent' if s.name not in copies else f'{copies[s.name].stat().st_size} o ≠ {s.stat().st_size} o'})"
        for s in sources
        if s.name not in copies or copies[s.name].stat().st_size != s.stat().st_size
    ]

    manifest = BACKUP_DIR / MANIFEST_NAME
    previous = _read_manifest(manifest)
    current = {name: _digest(p) for name, p in copies.items()}

    vanished = sorted(set(previous) - set(current))
    rewritten = sorted(n for n, d in previous.items() if n in current and current[n] != d)

    print(f"[check-backup] {len(sources)} instantanés à la source · {len(copies)} copies "
          f"· {len(previous)} au passage précédent")

    failed = False
    if missing:
        failed = True
        print("check-backup ÉCHEC — instantanés sans copie conforme :")
        for m in missing:
            print(f"  - {m}")
    if vanished:
        failed = True
        print("check-backup ÉCHEC — copies disparues depuis le passage précédent :")
        for v in vanished:
            print(f"  - {v}")
    if rewritten:
        failed = True
        print("check-backup ÉCHEC — copies réécrites (empreinte différente) :")
        for r in rewritten:
            print(f"  - {r}")

    # Inventaire réécrit même en échec : il doit refléter l'état constaté, sinon la
    # prochaine exécution rejugerait sur un passé périmé.
    manifest.write_text("".join(f"{n}\t{d}\n" for n, d in sorted(current.items())))

    if failed:
        return 1
    print("check-backup OK (toute source copiée, aucune copie disparue ni réécrite)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
