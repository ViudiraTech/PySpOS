"""Stable repository paths shared by tests, regardless of working directory."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
APPS = SRC / "apps"
