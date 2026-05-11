"""Canonical paths for source-specific and shared discovery YAML files."""

from __future__ import annotations

from pathlib import Path


SOURCES_DIR = Path(__file__).resolve().parent
COMMON_DIR = SOURCES_DIR / "common"

COMMON_SEARCHES_EXAMPLE_PATH = COMMON_DIR / "searches.example.yaml"
WORKDAY_EMPLOYERS_PATH = SOURCES_DIR / "workday" / "employers.yaml"
GREENHOUSE_EMPLOYERS_PATH = SOURCES_DIR / "greenhouse" / "greenhouse.yaml"
SMARTEXTRACT_SITES_PATH = SOURCES_DIR / "smartextract" / "sites.yaml"
SMARTEXTRACT_SITES_EXAMPLE_PATH = SOURCES_DIR / "smartextract" / "sites.example.yaml"
