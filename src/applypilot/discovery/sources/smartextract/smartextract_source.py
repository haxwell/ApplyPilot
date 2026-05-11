"""SmartExtract discovery source adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from applypilot.discovery.sources.base import DiscoverySource
from applypilot.discovery.sources.paths import (
    COMMON_SEARCHES_EXAMPLE_PATH,
    SMARTEXTRACT_SITES_PATH,
)


@dataclass(frozen=True)
class SmartExtractSource(DiscoverySource):
    name: str = "smartextract"
    description: str = "Smart extract (AI-powered scraping, incl. Dice via sites.yaml)"
    data_files: tuple[Path, ...] = (
        SMARTEXTRACT_SITES_PATH,
        COMMON_SEARCHES_EXAMPLE_PATH,
    )

    def execute(self, *, workers: int = 1) -> dict:
        from applypilot.discovery.sources.smartextract.smartextract import run_smart_extract

        return run_smart_extract(workers=workers)
