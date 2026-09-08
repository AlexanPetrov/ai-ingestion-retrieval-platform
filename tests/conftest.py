"""Shared pytest fixtures and test bootstrap utilities."""

import sys
from pathlib import Path

import pytest

# Allow tests to import the src-layout package with plain `uv run pytest`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def isolate_database_runtime_from_local_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep ordinary tests independent of the developer's local database.

    Persistence-specific tests may still explicitly enable the database through
    Settings(database_enabled=True, ...), because constructor values take
    precedence over environment values.
    """
    monkeypatch.setenv(
        "DATABASE_ENABLED",
        "false",
    )
