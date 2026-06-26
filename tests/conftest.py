"""Shared pytest fixtures and test bootstrap utilities."""

import sys
from pathlib import Path

# Allow tests to import the src-layout package with plain `uv run pytest`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
