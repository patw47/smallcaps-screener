import os

os.environ.setdefault("DATA_DIR", "/tmp/screener_test")

import pytest  # noqa: E402

import screener_backend as sb  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_filing_memo(monkeypatch, tmp_path):
    """
    Répertoire de données propre par test : le mémo daté du balayage des dépôts
    (Epic 12 S2) y vit et est PERSISTANT par construction. Partagé, il ferait hériter
    un test de la cadence d'un autre.
    """
    monkeypatch.setattr(sb, "DATA_DIR", str(tmp_path / "data"))
