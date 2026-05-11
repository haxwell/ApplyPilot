"""Greenhouse discovery source adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from applypilot.discovery.sources.base import DiscoverySource
from applypilot.discovery.sources.paths import GREENHOUSE_EMPLOYERS_PATH


@dataclass(frozen=True)
class GreenhouseSource(DiscoverySource):
    name: str = "greenhouse"
    description: str = "Greenhouse ATS career sites"
    data_files: tuple[Path, ...] = (GREENHOUSE_EMPLOYERS_PATH,)

    def execute(self, *, workers: int = 1) -> dict:
        from applypilot.discovery.sources.greenhouse.greenhouse import search_all

        new, existing = search_all("", workers=workers)
        return {"new": new, "existing": existing}
