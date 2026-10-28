"""Read-only access to the ta-patterns lake: path, pinned commit, ``tools`` import.

The lake is never written: bytecode writing is switched off before ``tools`` is
imported (a ``__pycache__`` in ta-patterns would show in its ``git status``),
and every output goes to ``data/study/`` of this repo (gitignored).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Final

import yaml

logger = logging.getLogger(__name__)

# ta-patterns HEAD when the Epic 15 S1 study was written; another commit only warns.
PINNED_COMMIT: Final[str] = "5431650fedf8646d3122cda10bd873564e875134"
CONFIG_FILE: Final[Path] = Path(os.environ.get("CONFIG_FILE", "/app/config/local.yml"))
STUDY_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "data" / "study"


def native(path: str) -> Path:
    """``path`` as this interpreter sees it.

    The Windows venv of ta-patterns started from WSL gets a POSIX path from the
    config; its cwd (``\\\\wsl.localhost\\<distro>\\...``) gives the prefix.
    """
    if os.name == "nt" and path.startswith("/"):
        prefix = "\\".join(os.getcwd().split("\\")[:4])
        return Path(prefix + path.replace("/", "\\"))
    return Path(path)


def lake_dir(config: Path = CONFIG_FILE) -> Path | None:
    """``study.ta_patterns_dir`` of the local config; None when unset or absent."""
    try:
        raw = yaml.safe_load(config.read_text()) or {}
    except OSError:
        return None
    path = ((raw.get("study") or {}) if isinstance(raw, dict) else {}).get("ta_patterns_dir")
    if not path:
        return None
    p = native(str(path))
    return p if p.is_dir() else None


def head_commit(lake: Path) -> str:
    """Commit of the lake's checked-out HEAD, read from ``.git`` (no git call)."""
    git = lake / ".git"
    head = (git / "HEAD").read_text().strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    loose = git / ref
    if loose.exists():
        return loose.read_text().strip()
    for line in (git / "packed-refs").read_text().splitlines():
        if line.endswith(" " + ref):
            return line.split()[0]
    raise FileNotFoundError(f"{ref} not found in {git}")


def import_tools(lake: Path) -> str:
    """Put the lake on ``sys.path`` (no bytecode written); return its HEAD commit."""
    sys.dont_write_bytecode = True
    if str(lake) not in sys.path:
        sys.path.insert(0, str(lake))
    commit = head_commit(lake)
    if commit != PINNED_COMMIT:
        logger.warning("ta-patterns at %s, study pinned on %s", commit, PINNED_COMMIT)
    return commit
