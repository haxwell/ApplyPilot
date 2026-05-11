"""Typed discovery-source interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DiscoverySource(Protocol):
    """Official contract for all discovery sources."""

    name: str
    description: str
    data_files: tuple[Path, ...]

    def execute(self, *, workers: int = 1) -> dict:
        """Run discovery and return source-specific stats."""
        ...
