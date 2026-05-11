"""Discovery source interfaces and registry."""

from applypilot.discovery.sources.base import DiscoverySource
from applypilot.discovery.sources.registry import SOURCE_REGISTRY, source_descriptions

__all__ = ["DiscoverySource", "SOURCE_REGISTRY", "source_descriptions"]
