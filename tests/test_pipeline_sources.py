from __future__ import annotations

from applypilot import pipeline
from applypilot.discovery.sources.jobspy.jobspy_source import JobSpySiteSource
from applypilot.discovery.sources.registry import SOURCE_REGISTRY


def test_ziprecruiter_source_is_resolvable() -> None:
    assert "ziprecruiter" in pipeline.DISCOVERY_SOURCES
    assert pipeline.resolve_source_names(["ziprecruiter"]) == ["ziprecruiter"]
    assert pipeline.resolve_source_names(["zip_recruiter"]) == ["ziprecruiter"]


def test_ziprecruiter_maps_to_jobspy_site_override() -> None:
    source = SOURCE_REGISTRY["ziprecruiter"]
    assert isinstance(source, JobSpySiteSource)
    assert source.sites_override == ("zip_recruiter",)
