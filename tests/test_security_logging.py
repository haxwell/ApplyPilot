from __future__ import annotations

import logging

from applypilot.discovery.sources.greenhouse import greenhouse
from applypilot.discovery.sources.smartextract import smartextract
from applypilot.discovery.sources.workday import workday


def test_workday_logs_omit_search_text_and_proxy_credentials(caplog, monkeypatch) -> None:
    employer = {
        "name": "Example Employer",
        "base_url": "https://example.wd1.myworkdayjobs.com",
        "tenant": "example",
        "site_id": "careers",
    }

    monkeypatch.setattr(workday, "workday_search", lambda *args, **kwargs: {"total": 0, "jobPostings": []})

    caplog.set_level(logging.INFO, logger="applypilot.discovery.workday")
    workday.setup_proxy("127.0.0.1:8080:user:secret")
    workday.search_employer("example", employer, "Highly Sensitive Query")

    log_text = caplog.text
    assert "Highly Sensitive Query" not in log_text
    assert "127.0.0.1" not in log_text
    assert "user" not in log_text
    assert "secret" not in log_text


def test_greenhouse_logs_omit_search_text(caplog, monkeypatch) -> None:
    monkeypatch.setattr(greenhouse, "fetch_jobs_api", lambda *args, **kwargs: {"jobs": []})

    caplog.set_level(logging.INFO, logger="applypilot.discovery.greenhouse")
    greenhouse.search_employer("safe-board", {"name": "Safe Co"}, "Highly Sensitive Query")

    assert "Highly Sensitive Query" not in caplog.text


def test_smartextract_does_not_log_job_samples(caplog, monkeypatch) -> None:
    monkeypatch.setattr(
        smartextract,
        "collect_page_intelligence",
        lambda url, headless=True: {
            "url": url,
            "json_ld": [],
            "api_responses": [],
            "data_testids": [],
            "page_title": "",
            "dom_stats": {},
            "card_candidates": [],
            "full_html": "",
        },
    )
    monkeypatch.setattr(smartextract, "format_strategy_briefing", lambda intel: "brief")
    monkeypatch.setattr(
        smartextract,
        "ask_llm",
        lambda prompt: ("{}", 0.1, {"response_chars": 2}),
    )
    monkeypatch.setattr(
        smartextract,
        "extract_json",
        lambda raw: {"strategy": "json_ld", "reasoning": "ok", "extraction": {}},
    )
    monkeypatch.setattr(
        smartextract,
        "execute_json_ld",
        lambda intel, plan: [{"title": "Secret Role", "location": "Secret City", "salary": "$999"}],
    )

    caplog.set_level(logging.INFO, logger="applypilot.discovery.smartextract")
    result = smartextract._run_one_site("Example", "https://example.com")

    assert result["status"] == "PASS"
    assert "Secret Role" not in caplog.text
    assert "Secret City" not in caplog.text
    assert "$999" not in caplog.text


def test_smartextract_logs_omit_raw_exception_text(caplog, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("secret-token-value")

    monkeypatch.setattr(smartextract, "collect_page_intelligence", _boom)

    caplog.set_level(logging.ERROR, logger="applypilot.discovery.smartextract")
    smartextract._run_one_site("Example", "https://example.com")

    assert "secret-token-value" not in caplog.text
    assert "RuntimeError" in caplog.text
