"""Hacker News discovery source adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from applypilot.discovery.sources.base import DiscoverySource


@dataclass(frozen=True)
class HackerNewsSource(DiscoverySource):
    name: str = "hackernews"
    description: str = "Hacker News 'Who is Hiring?' thread"
    data_files: tuple[Path, ...] = ()

    def execute(self, *, workers: int = 1) -> dict:
        del workers
        from applypilot.discovery.sources.hackernews.hackernews import run_hn_discovery

        return run_hn_discovery()
