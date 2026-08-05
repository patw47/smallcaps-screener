"""
Prévalence des marqueurs de détresse (Epic 9 S2) — rapport DESCRIPTIF, sort 0 si produit.

Le chiffre est aujourd'hui inconnu : quelle fraction des candidats porte au moins un
marqueur, et comment elle se ventile par secteur. Il décide si un epic de filtrage a
lieu d'être — et rien d'autre : aucun marqueur n'entre ici dans la sélection, le
classement ou le score.

DEUX DÉNOMINATEURS, JAMAIS CONFONDUS. Les cinq marqueurs ne vivent pas dans la même
couche de l'entonnoir :

  - couche PRIX (Passe A) — `sub_dollar_flag`, `reverse_split_flag` : dérivés des séries
    de cours, donc mesurables sur l'UNIVERS ENTIER à coût marginal nul. Ce rapport les
    recalcule sur un téléchargement frais de tout l'univers découvert du jour.
  - couche DÉPÔTS (Passe B) — `dilution_flag`, `late_filing_flag`, `going_concern_flag` :
    issus des dépôts officiels, interrogés seulement pour les survivants de l'entonnoir.
    Leur dénominateur est donc les SÉLECTIONS, jamais l'univers.

Servir l'un pour l'autre gonflerait ou écraserait la prévalence d'un facteur ~20.

La ventilation par secteur porte sur les sélections (le secteur n'est connu qu'en Passe B),
avec la biotechnologie et la pharmacie ISOLÉES : une société sans chiffre d'affaires se
finance structurellement par émission d'actions nouvelles. Si le marqueur de dilution y est
quasi universel, un futur filtre serait une exclusion sectorielle sous un nom qui ne la
désigne pas — c'est ce point que le tableau doit permettre de trancher.

Tourne dans le conteneur (`make flag-prevalence`) : réseau, univers réel, données réelles.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DATA_DIR", "/app/data")

import screener_backend as sb  # noqa: E402

PRICE_FLAGS = ("sub_dollar_flag", "reverse_split_flag")
FILING_FLAGS = ("dilution_flag", "late_filing_flag", "going_concern_flag")
ALL_FLAGS = PRICE_FLAGS + FILING_FLAGS

LABELS = {
    "sub_dollar_flag": "cours sous le plancher de cotation (série consécutive)",
    "reverse_split_flag": "regroupement d'actions récent",
    "dilution_flag": "enregistrement d'émission d'actions",
    "late_filing_flag": "rapport périodique en retard",
    "going_concern_flag": "doute sur la continuité d'exploitation",
}


def _frac(n: int, d: int) -> str:
    return "—" if not d else f"{100 * n / d:.1f} %".replace(".", ",")


def _cell(n: int, d: int) -> str:
    return f"{n}/{d} ({_frac(n, d)})"


def _count(rows: list[dict], flag: str) -> tuple[int, int]:
    """(effectif levé, effectif où le marqueur est CONNU). None = capteur muet, pas « sain »."""
    known = [r for r in rows if r.get(flag) is not None]
    return sum(1 for r in known if r[flag]), len(known)


def measure_price_layer() -> tuple[dict[str, tuple[int, int]], int, int]:
    """Couche prix sur l'univers découvert du jour : {flag: (effectif, connus)}, univers, exploitables."""
    universe = sb.discover_tickers()
    prices = sb._download_prices(universe, sb.FILTERS["rs_benchmark"])
    prices.pop(sb.FILTERS["rs_benchmark"], None)

    rows = []
    for tk, df in prices.items():
        close = df["Close"].dropna() if "Close" in df else None
        if close is None or close.empty:
            continue
        rows.append({
            "ticker": tk,
            "sub_dollar_flag": sb.sub_dollar_marker(close)[1],
            "reverse_split_flag": sb._reverse_split_marker(df)[0],
        })
    return {f: _count(rows, f) for f in PRICE_FLAGS}, len(universe), len(rows)


def _sector_bucket(stock: dict) -> str:
    """Secteur affiché, biotechnologie et pharmacie isolées du reste de la santé."""
    if sb._is_binary_event_sector(stock):
        return "Biotechnologie / pharmacie"
    return stock.get("sector") or "secteur inconnu"


def render(payload: dict, price_counts: dict, n_universe: int, n_priced: int) -> str:
    picks = payload.get("stocks") or []
    n_b = len(picks)
    at_least_one = sum(1 for s in picks if any(s.get(f) for f in ALL_FLAGS))
    fully_known = sum(1 for s in picks if all(s.get(f) is not None for f in ALL_FLAGS))

    out: list[str] = []
    add = out.append
    add("# Prévalence des marqueurs de détresse")
    add("")
    add(f"- Produit le : {datetime.now(tz=timezone.utc).isoformat(timespec='seconds')}")
    add(f"- Scan de référence : `{payload.get('scanned_at')}`")
    add(f"- Univers découvert du jour : **{n_universe}** symboles, "
        f"dont **{n_priced}** avec une série de cours exploitable")
    add(f"- Sélections du scan (survivants de l'entonnoir) : **{n_b}**")
    add("")
    add("Mesure strictement descriptive : aucun marqueur n'entre dans la sélection, "
        "le classement ou le score.")
    add("")
    add("## Les deux dénominateurs")
    add("")
    add("| couche | origine | population mesurée | dénominateur |")
    add("|---|---|---|---|")
    add(f"| prix (Passe A) | séries de cours | univers entier | **{n_priced}** |")
    add(f"| dépôts officiels (Passe B) | dépôts réglementaires | survivants de l'entonnoir "
        f"| **{n_b}** |")
    add("")
    add("La couche des dépôts n'est PAS mesurable sur l'univers : les dépôts ne sont "
        "interrogés que pour les titres qui atteignent la Passe B. Rapporter sa prévalence "
        "au dénominateur de l'univers la diviserait par ~20.")
    add("")
    add("## Prévalence par marqueur")
    add("")
    add("| marqueur | couche | effectif | dénominateur | fraction |")
    add("|---|---|---|---|---|")
    for f in PRICE_FLAGS:
        n, d = price_counts[f]
        add(f"| `{f}` — {LABELS[f]} | prix | {n} | {d} | {_frac(n, d)} |")
    for f in FILING_FLAGS:
        n, d = _count(picks, f)
        add(f"| `{f}` — {LABELS[f]} | dépôts | {n} | {d} | {_frac(n, d)} |")
    add("")
    add("Le dénominateur d'une ligne est le nombre d'observations où le marqueur est "
        "CONNU : un capteur muet (dépôts indisponibles pour ce titre) ne compte pas comme "
        "un titre sain.")
    add("")
    add("## Au moins un marqueur — le chiffre décisionnel")
    add("")
    add(f"Sur les **{n_b}** sélections — la seule population où les cinq marqueurs "
        f"coexistent — **{_cell(at_least_one, n_b)}** portent au moins un marqueur.")
    add("")
    add(f"({fully_known}/{n_b} sélections ont les cinq marqueurs effectivement connus ; "
        "pour les autres, un capteur muet est compté comme non levé — la fraction "
        "ci-dessus est donc une borne basse.)")
    add("")
    add("## Ventilation par secteur (biotechnologie et pharmacie isolées)")
    add("")
    add("Population : les sélections. Le secteur n'est connu qu'en Passe B, donc cette "
        "ventilation ne peut pas porter sur l'univers. Chaque cellule : effectif / "
        "dénominateur du secteur.")
    add("")
    header = "| secteur | ≥ 1 marqueur | " + " | ".join(f"`{f}`" for f in ALL_FLAGS) + " |"
    add(header)
    add("|---" * (len(ALL_FLAGS) + 2) + "|")
    buckets: dict[str, list[dict]] = {}
    for s in picks:
        buckets.setdefault(_sector_bucket(s), []).append(s)
    for sector, rows in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        d = len(rows)
        cells = [_cell(sum(1 for r in rows if any(r.get(f) for f in ALL_FLAGS)), d)]
        cells += [_cell(*_count(rows, f)) for f in ALL_FLAGS]
        add(f"| {sector} | " + " | ".join(cells) + " |")
    add("")
    return "\n".join(out) + "\n"


def main() -> int:
    if not sb.OUTPUT_FILE.exists():
        print(f"flag-prevalence ÉCHEC — {sb.OUTPUT_FILE} absent (aucun scan à mesurer)")
        return 1
    payload = json.loads(sb.OUTPUT_FILE.read_text())
    if not payload.get("stocks"):
        print("flag-prevalence ÉCHEC — le dernier scan n'a produit aucune sélection")
        return 1

    price_counts, n_universe, n_priced = measure_price_layer()
    report = render(payload, price_counts, n_universe, n_priced)

    dest = Path(sb.DATA_DIR) / "flag_prevalence.md"
    dest.write_text(report, encoding="utf-8")
    print(report)
    print(f"[flag-prevalence] rapport écrit dans {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
