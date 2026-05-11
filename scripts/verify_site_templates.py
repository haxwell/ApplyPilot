#!/usr/bin/env python3
"""Verify configured job-site URL templates for a fixed query/location matrix.

This helper renders URLs using the same substitution logic as smartextract and
then performs deterministic, low-friction checks against each rendered URL.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote_plus
from urllib.request import Request, urlopen

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


TARGET_SITES = [
    "SimplyHired",
    "PowerToFly",
    "Techstars Jobs",
    "Startup.jobs",
    "WelcomeToTheJungle",
]
STATIC_TARGET_SITES = [
    "RemoteOK",
    "WeWorkRemotely",
    "Remotive",
    "JustRemote",
    "Himalayas",
    "Working Nomads",
    "Remote.co",
    "Nodesk",
    "DynamiteJobs",
    "4DayWeek",
]

TEST_QUERY = "senior java engineer"
TEST_LOCATION = "Denver, CO"
TIMEOUT_SECONDS = 25


@dataclass
class FetchResult:
    ok: bool
    status: int | None
    final_url: str
    title: str
    body_excerpt: str
    error: str | None


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(unescape(_strip_tags(match.group(1))).split())


def fetch_url(url: str) -> FetchResult:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )

    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read(150_000).decode("utf-8", errors="replace")
            final_url = resp.geturl()
            status = getattr(resp, "status", None)
            return FetchResult(
                ok=True,
                status=status,
                final_url=final_url,
                title=_extract_title(body),
                body_excerpt=" ".join(unescape(_strip_tags(body)).split())[:1200].lower(),
                error=None,
            )
    except HTTPError as exc:
        return FetchResult(
            ok=False,
            status=exc.code,
            final_url=url,
            title="",
            body_excerpt="",
            error=f"HTTP {exc.code}",
        )
    except URLError as exc:
        return FetchResult(
            ok=False,
            status=None,
            final_url=url,
            title="",
            body_excerpt="",
            error=f"URL error: {exc.reason}",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return FetchResult(
            ok=False,
            status=None,
            final_url=url,
            title="",
            body_excerpt="",
            error=f"{exc.__class__.__name__}: {exc}",
        )


def _query_signal(fetch: FetchResult) -> bool:
    decoded_url = unquote_plus(fetch.final_url).lower()
    query_tokens = ["senior", "java", "engineer"]
    return all(tok in decoded_url or tok in fetch.body_excerpt for tok in query_tokens)


def _location_signal(fetch: FetchResult) -> bool:
    decoded_url = unquote_plus(fetch.final_url).lower()
    return "denver" in decoded_url or "denver" in fetch.body_excerpt


def _looks_like_jobs_page(fetch: FetchResult) -> bool:
    haystack = f"{fetch.title.lower()} {fetch.body_excerpt}"
    return any(token in haystack for token in ("job", "jobs", "career", "hiring", "openings"))


def _looks_like_software_jobs_page(fetch: FetchResult) -> bool:
    haystack = f"{fetch.title.lower()} {fetch.body_excerpt} {unquote_plus(fetch.final_url).lower()}"
    has_jobs_signal = any(token in haystack for token in ("job", "jobs", "career", "hiring", "openings"))
    has_software_signal = any(
        token in haystack
        for token in (
            "software",
            "developer",
            "engineering",
            "engineer",
            "programming",
            "dev",
            "remote",
        )
    )
    return has_jobs_signal and has_software_signal


def _render_targets_for_selected_sites(selected_names: set[str]) -> list[dict]:
    cfg = _load_sites_config()
    selected_sites = [s for s in cfg.get("sites", []) if s.get("name") in selected_names]
    targets: list[dict] = []
    for site in selected_sites:
        if site.get("type", "static") != "search":
            continue
        template = site.get("url", "")
        for remote in (True, False):
            remote_param_cfg = site.get("remote_param", {}) or {}
            remote_param = remote_param_cfg.get("when_remote" if remote else "when_not_remote", "")
            remote_flag_cfg = site.get("remote_flag", {}) or {}
            remote_flag = remote_flag_cfg.get("when_remote" if remote else "when_not_remote", "")
            expanded = template
            expanded = expanded.replace("{query_encoded}", quote_plus(TEST_QUERY))
            expanded = expanded.replace("{query}", quote_plus(TEST_QUERY))
            expanded = expanded.replace("{location_encoded}", quote_plus(TEST_LOCATION))
            expanded = expanded.replace("{distance}", "25")
            expanded = expanded.replace("{distance_encoded}", quote_plus("25"))
            expanded = expanded.replace("{remote_param}", remote_param)
            expanded = expanded.replace("{remote_flag}", remote_flag)
            targets.append(
                {
                    "name": site.get("name", "Unknown"),
                    "url": expanded,
                    "query": TEST_QUERY,
                    "location": TEST_LOCATION,
                    "remote": remote,
                }
            )
    return targets


def _load_sites_config() -> dict:
    path = (
        REPO_ROOT
        / "src"
        / "applypilot"
        / "discovery"
        / "sources"
        / "smartextract"
        / "sites.yaml"
    )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _site_entry_by_name(name: str, cfg: dict) -> dict:
    for site in cfg.get("sites", []):
        if site.get("name") == name:
            return site
    return {}


def build_report(selected_names: set[str]) -> list[dict]:
    cfg = _load_sites_config()
    targets = _render_targets_for_selected_sites(selected_names)

    grouped: dict[str, dict[bool, dict]] = {}
    for t in targets:
        grouped.setdefault(t["name"], {})[bool(t["remote"])] = t

    report: list[dict] = []
    for name in sorted(selected_names):
        site_cfg = _site_entry_by_name(name, cfg)
        row_true = grouped.get(name, {}).get(True)
        row_false = grouped.get(name, {}).get(False)
        if not row_true or not row_false:
            report.append(
                {
                    "site": name,
                    "error": "missing rendered targets for both remote=true and remote=false",
                }
            )
            continue

        fetch_true = fetch_url(row_true["url"])
        fetch_false = fetch_url(row_false["url"])

        supports_location = "{location_encoded}" in site_cfg.get("url", "")
        supports_remote_param = (
            "{remote_param}" in site_cfg.get("url", "")
            or "{remote_flag}" in site_cfg.get("url", "")
            or "remote=true" in site_cfg.get("url", "").lower()
        )

        remote_true_marker = (
            str((site_cfg.get("remote_param") or {}).get("when_remote", "")).strip()
            or str((site_cfg.get("remote_flag") or {}).get("when_remote", "")).strip()
            or "remote=true"
        ).lower()
        remote_false_marker = (
            str((site_cfg.get("remote_param") or {}).get("when_not_remote", "")).strip()
            or str((site_cfg.get("remote_flag") or {}).get("when_not_remote", "")).strip()
        ).lower()

        decoded_true_url = unquote_plus(row_true["url"]).lower()
        decoded_false_url = unquote_plus(row_false["url"]).lower()

        remote_signal_true = remote_true_marker and remote_true_marker in decoded_true_url
        if remote_false_marker:
            remote_signal_false = remote_false_marker in decoded_false_url
        else:
            remote_signal_false = remote_true_marker not in decoded_false_url

        report.append(
            {
                "site": name,
                "rendered_urls": {
                    "remote_true": row_true["url"],
                    "remote_false": row_false["url"],
                },
                "load": {
                    "remote_true": {
                        "ok": fetch_true.ok,
                        "status": fetch_true.status,
                        "title": fetch_true.title,
                        "error": fetch_true.error,
                    },
                    "remote_false": {
                        "ok": fetch_false.ok,
                        "status": fetch_false.status,
                        "title": fetch_false.title,
                        "error": fetch_false.error,
                    },
                },
                "checks": {
                    "jobs_page_remote_true": _looks_like_jobs_page(fetch_true) if fetch_true.ok else False,
                    "query_applied_remote_true": _query_signal(fetch_true) if fetch_true.ok else False,
                    "location_supported": supports_location,
                    "location_applied_remote_true": (
                        _location_signal(fetch_true) if supports_location and fetch_true.ok else None
                    ),
                    "remote_supported": supports_remote_param,
                    "remote_applied_by_url_shape": (
                        bool(remote_signal_true and remote_signal_false) if supports_remote_param else None
                    ),
                },
            }
        )
    return report


def build_static_report(selected_names: set[str]) -> list[dict]:
    cfg = _load_sites_config()
    report: list[dict] = []

    for name in sorted(selected_names):
        site_cfg = _site_entry_by_name(name, cfg)
        if not site_cfg:
            report.append({"site": name, "error": "site not found in sites.yaml"})
            continue
        if site_cfg.get("type") != "static":
            report.append({"site": name, "error": "site is not type: static"})
            continue

        tested_url = site_cfg.get("url", "")
        fetch = fetch_url(tested_url)
        report.append(
            {
                "site": name,
                "tested_url": tested_url,
                "load": {
                    "ok": fetch.ok,
                    "status": fetch.status,
                    "title": fetch.title,
                    "error": fetch.error,
                },
                "checks": {
                    "jobs_page": _looks_like_jobs_page(fetch) if fetch.ok else False,
                    "software_or_remote_signal": _looks_like_software_jobs_page(fetch) if fetch.ok else False,
                },
            }
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify sites.yaml URL templates.")
    parser.add_argument(
        "--mode",
        choices=("search", "static"),
        default="search",
        help="Verification mode. search=parameterized templates, static=fixed listings pages.",
    )
    parser.add_argument(
        "--sites",
        nargs="*",
        default=None,
        help="Site names from sites.yaml.",
    )
    args = parser.parse_args()

    if args.sites:
        selected_names = set(args.sites)
    else:
        selected_names = set(TARGET_SITES if args.mode == "search" else STATIC_TARGET_SITES)

    report = build_report(selected_names) if args.mode == "search" else build_static_report(selected_names)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
