"""
Gate anti-fuite des secrets (Epic 11 S2) — sort 0 si propre.

Deux vérifications, sur les fichiers VERSIONNÉS (`git ls-files`) :

  1. **Aucune valeur de secret.** Deux passes complémentaires :
     - passe locale (si `.env` existe) : chaque valeur du fichier d'environnement est
       recherchée telle quelle dans le dépôt. C'est la seule passe capable de voir un
       secret qui ne ressemble à rien de connu ;
     - passe par motifs (toujours) : formes reconnaissables des jetons utilisés par le
       projet. Elle tourne même sans `.env` — sur une machine tierce ou en intégration,
       où la passe locale n'a rien à comparer.
  2. **`.env.example` documente les NOMS** des deux variables d'export, sans valeurs.

Ce script est lui-même versionné : il ne contient donc aucune valeur, il les lit à
l'exécution. Il n'imprime JAMAIS ce qu'il trouve — seulement le fichier, la ligne et le
NOM de la variable ou du motif. Une gate qui recopie le secret dans son rapport le fuite
dans les journaux qu'elle est censée protéger.

Appelé par `make check-secrets`.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"

# Variables dont le fichier d'exemple doit porter le nom, sans valeur (Epic 11 S2).
REQUIRED_NAMES = ("NOTION_API_KEY", "NOTION_RESULTS_DB_ID")

# Formes reconnaissables des jetons du projet — jamais une valeur, seulement une forme.
TOKEN_PATTERNS = {
    "jeton d'intégration Notion": re.compile(r"\bntn_[A-Za-z0-9]{20,}"),
    "secret d'intégration Notion (ancien format)": re.compile(r"\bsecret_[A-Za-z0-9]{30,}"),
    "jeton de bot Telegram": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "clé d'API Anthropic": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
}

# Une valeur plus courte que ça n'est pas un secret : la chercher telle quelle dans le
# dépôt ne produirait que des collisions (« true », « 24 », un identifiant de chat court).
MIN_SECRET_LEN = 12


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / name for name in out.split("\0") if name]


def _env_values() -> dict[str, str]:
    """Valeurs du fichier d'environnement local, par nom de variable. {} s'il est absent."""
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if len(value) >= MIN_SECRET_LEN:
            values[name.strip()] = value
    return values


def _scan(files: list[Path], values: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for path in files:
        try:
            text = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue                                   # binaire ou illisible : rien à fuiter
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, value in values.items():
                if value in line:
                    findings.append(f"  {rel}:{lineno} — valeur de {name} en clair")
            for label, pattern in TOKEN_PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"  {rel}:{lineno} — {label}")
    return findings


def _check_example() -> list[str]:
    if not EXAMPLE_FILE.exists():
        return [f"  {EXAMPLE_FILE.name} absent"]
    problems = []
    lines = EXAMPLE_FILE.read_text().splitlines()
    for name in REQUIRED_NAMES:
        declared = [ln for ln in lines if ln.strip().startswith(f"{name}=")]
        if not declared:
            problems.append(f"  {EXAMPLE_FILE.name} — nom {name} absent")
        elif any(ln.split("=", 1)[1].strip() for ln in declared):
            problems.append(f"  {EXAMPLE_FILE.name} — {name} porte une valeur")
    return problems


def main() -> int:
    values = _env_values()
    if not values:
        print("[check-secrets] .env absent — passe par motifs seule")
    findings = _scan(_tracked_files(), values) + _check_example()
    if findings:
        print("check-secrets ÉCHEC :")
        print("\n".join(dict.fromkeys(findings)))
        return 1
    print(f"[check-secrets] {len(values)} valeur(s) locale(s) et {len(TOKEN_PATTERNS)} motif(s) "
          f"recherchés · noms {', '.join(REQUIRED_NAMES)} documentés sans valeur")
    print("check-secrets OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
