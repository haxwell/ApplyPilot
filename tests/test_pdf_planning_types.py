from __future__ import annotations

from applypilot.scoring.pdf_planning_types import SkillDisposition


def test_skill_disposition_mark_removed_adds_user_action() -> None:
    disposition = SkillDisposition(
        claim="PostgreSQL",
        coverage_status="unsupported",
        final_action="kept",
        reason="no_supported_retained_replacement_available",
    )
    disposition.mark_removed("unsupported_no_replacement_no_source_evidence")

    assert disposition.final_action == "removed"
    assert disposition.reason == "unsupported_no_replacement_no_source_evidence"
    assert disposition.user_action is not None
    payload = disposition.to_report_dict()
    assert "user_action" in payload


def test_replaced_then_removed_keeps_replacement_only_in_history() -> None:
    disposition = SkillDisposition(
        claim="PostgreSQL",
        coverage_status="unsupported",
        final_action="replaced",
        reason="replaced_by_supported_retained_skill",
        replacement="CI/CD",
    )
    disposition.mark_removed("unsupported_no_replacement_no_source_evidence")

    payload = disposition.to_report_dict()
    assert payload["final_action"] == "removed"
    assert "replacement" not in payload
    assert payload["action_history"] == [
        {
            "action": "replaced",
            "reason": "replaced_by_supported_retained_skill",
            "replacement": "CI/CD",
        },
        {
            "action": "removed",
            "reason": "unsupported_no_replacement_no_source_evidence",
        },
    ]


def test_replacement_not_found_then_removed_history_is_clear() -> None:
    disposition = SkillDisposition(
        claim="Jenkins CI",
        coverage_status="unsupported",
        final_action="kept",
        reason="no_supported_retained_replacement_available",
    )
    disposition.mark_removed("unsupported_no_replacement_no_source_evidence")

    payload = disposition.to_report_dict()
    assert payload["action_history"] == [
        {
            "action": "replacement_not_found",
            "reason": "no_supported_retained_replacement_available",
        },
        {
            "action": "removed",
            "reason": "unsupported_no_replacement_no_source_evidence",
        },
    ]
