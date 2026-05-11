"""Workday discovery source adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from applypilot.discovery.sources.base import DiscoverySource
from applypilot.discovery.sources.paths import WORKDAY_EMPLOYERS_PATH


@dataclass(frozen=True)
class WorkdaySource(DiscoverySource):
    name: str = "workday"
    description: str = "Workday corporate career sites"
    data_files: tuple[Path, ...] = (WORKDAY_EMPLOYERS_PATH,)

    def execute(self, *, workers: int = 1) -> dict:
        from applypilot.discovery.sources.workday.workday import run_workday_discovery

        return run_workday_discovery(workers=workers)
