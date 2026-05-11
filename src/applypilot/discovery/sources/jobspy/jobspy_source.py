"""JobSpy discovery source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from applypilot.discovery.sources.base import DiscoverySource
from applypilot.discovery.sources.paths import COMMON_SEARCHES_EXAMPLE_PATH


@dataclass(frozen=True)
class JobSpySource(DiscoverySource):
    name: str = "jobspy"
    description: str = "JobSpy aggregator (LinkedIn, Indeed, ZipRecruiter)"
    data_files: tuple[Path, ...] = (COMMON_SEARCHES_EXAMPLE_PATH,)

    def execute(self, *, workers: int = 1) -> dict:
        del workers
        from applypilot.discovery.sources.jobspy.jobspy import run_discovery

        return run_discovery()


@dataclass(frozen=True)
class JobSpySiteSource(DiscoverySource):
    name: str
    description: str
    sites_override: tuple[str, ...]
    data_files: tuple[Path, ...] = (COMMON_SEARCHES_EXAMPLE_PATH,)

    def execute(self, *, workers: int = 1) -> dict:
        del workers
        from applypilot.discovery.sources.jobspy.jobspy import run_discovery

        return run_discovery(sites_override=list(self.sites_override))
