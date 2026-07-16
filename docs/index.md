# SmallCaps Screener

A Dockerized dashboard that discovers and tracks US small-cap stocks. It scans the full
eligible universe (~2,500 names across NASDAQ, NYSE and AMEX) every trading day and
surfaces candidates as a **research / watchlist tool**: it displays measured historical
frequencies with their two-sided risks and runs live forward-validation experiments. It
does **not** claim a trading edge and it does **not** trade — the final call stays human.
The interface is in French; this documentation is in English.

See the [project README](https://github.com/patw47/smallcaps-screener) for the full
pitch and quickstart. This site covers:

- [Architecture](architecture.md)
- [Backend screener & scoring](backend.md)
- [API reference](api.md)
- [Frontend](frontend.md)
- [Deployment and operations](deployment.md)
- [Glossary — every displayed metric, its tooltip and its source](glossaire.md)
- [Interface reading guide — what you see, tier by tier](guide_interface.md)
- Post-mortems of the failed pre-registered theses (v2, v3)

All pre-registered theses (v1–v3) failed their study — see the post-mortems. Scoring
constants and thresholds for the current washout research (v4/v5) live outside this
repo and are never published.
