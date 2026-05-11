"""Discovery-source registry with official execute() contract."""

from __future__ import annotations

from applypilot.discovery.sources.base import DiscoverySource
from applypilot.discovery.sources.greenhouse.greenhouse_source import GreenhouseSource
from applypilot.discovery.sources.hackernews.hackernews_source import HackerNewsSource
from applypilot.discovery.sources.jobspy.jobspy_source import JobSpySiteSource, JobSpySource
from applypilot.discovery.sources.smartextract.smartextract_source import SmartExtractSource
from applypilot.discovery.sources.workday.workday_source import WorkdaySource


SOURCE_REGISTRY: dict[str, DiscoverySource] = {
    "jobspy": JobSpySource(),
    "linkedin": JobSpySiteSource(
        name="linkedin",
        description="LinkedIn only (via JobSpy)",
        sites_override=("linkedin",),
    ),
    "indeed": JobSpySiteSource(
        name="indeed",
        description="Indeed only (via JobSpy)",
        sites_override=("indeed",),
    ),
    "ziprecruiter": JobSpySiteSource(
        name="ziprecruiter",
        description="ZipRecruiter only (via JobSpy)",
        sites_override=("zip_recruiter",),
    ),
    "workday": WorkdaySource(),
    "greenhouse": GreenhouseSource(),
    "smartextract": SmartExtractSource(),
    "hackernews": HackerNewsSource(),
}


def source_descriptions() -> dict[str, str]:
    """Return source name -> user-facing description."""

    return {name: source.description for name, source in SOURCE_REGISTRY.items()}
