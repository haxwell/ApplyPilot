from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DispositionAction:
    action: str
    reason: str = ""
    replacement: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_report_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": self.action}
        if self.reason:
            payload["reason"] = self.reason
        if self.replacement:
            payload["replacement"] = self.replacement
        for key, value in self.metadata.items():
            if value in (None, "", [], {}):
                continue
            payload[key] = value
        return payload


@dataclass
class SkillDisposition:
    claim: str
    coverage_status: str = ""
    final_action: str = ""
    reason: str = ""
    action_history: list[DispositionAction] = field(default_factory=list)
    user_action: str | None = None
    replacement: str | None = None
    supported_replacement_candidates_available_raw: int = 0
    usable_supported_replacement_candidates_available: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def _ensure_user_action(self) -> None:
        if self.user_action:
            return
        self.user_action = (
            f"Add a truthful experience bullet, compact summary, or project summary showing {self.claim} work if this skill should remain visible."
        )

    def mark_replacement_not_found(self, reason: str) -> None:
        self.final_action = "kept"
        self.reason = reason
        self.action_history.append(DispositionAction(action="replacement_not_found", reason=reason))
        self._ensure_user_action()

    def mark_replaced(self, replacement: str, reason: str) -> None:
        self.final_action = "replaced"
        self.reason = reason
        self.replacement = replacement

    def mark_removed(self, reason: str) -> None:
        if self.final_action == "replaced":
            self.action_history.append(
                DispositionAction(
                    action="replaced",
                    reason=self.reason,
                    replacement=self.replacement,
                )
            )
        elif self.final_action == "kept":
            prior_action = "replacement_not_found"
            if self.reason not in {
                "no_supported_retained_replacement_available",
                "replacement_duplicate_or_alias_conflict",
            }:
                prior_action = "replacement_not_kept"
            self.action_history.append(DispositionAction(action=prior_action, reason=self.reason))
        self.final_action = "removed"
        self.reason = reason
        self.replacement = None
        self.action_history.append(DispositionAction(action="removed", reason=reason))
        self._ensure_user_action()

    def to_report_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim": self.claim,
            "coverage_status": self.coverage_status,
            "final_action": self.final_action,
            "reason": self.reason,
        }
        if self.action_history:
            payload["action_history"] = [item.to_report_dict() for item in self.action_history]
        if self.user_action:
            payload["user_action"] = self.user_action
        if self.replacement and self.final_action != "removed":
            payload["replacement"] = self.replacement
        if self.supported_replacement_candidates_available_raw:
            payload["supported_replacement_candidates_available_raw"] = int(
                self.supported_replacement_candidates_available_raw
            )
        if self.usable_supported_replacement_candidates_available:
            payload["usable_supported_replacement_candidates_available"] = int(
                self.usable_supported_replacement_candidates_available
            )
        for key, value in self.metadata.items():
            if value in (None, "", [], {}):
                continue
            payload[key] = value
        return payload


@dataclass
class ReplacementCandidate:
    original_claim: str
    candidate: str
    coverage_status: str = ""
    supported: bool = False
    already_visible: bool = False
    already_used: bool = False
    alias_conflict: bool = False
    failed_page_fit: bool = False
    usable: bool = False
    rejection_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_report_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim": self.original_claim,
            "candidate": self.candidate,
            "coverage_status": self.coverage_status,
            "supported": self.supported,
            "usable": self.usable,
        }
        if self.already_visible:
            payload["already_visible"] = True
        if self.already_used:
            payload["already_used"] = True
        if self.alias_conflict:
            payload["alias_conflict"] = True
        if self.failed_page_fit:
            payload["failed_page_fit"] = True
        if self.rejection_reasons:
            payload["rejection_reasons"] = list(self.rejection_reasons)
        for key, value in self.metadata.items():
            if value in (None, "", [], {}):
                continue
            payload[key] = value
        return payload


@dataclass
class PlanningOperation:
    step: str
    claim: str | None = None
    action: str | None = None
    reason: str | None = None
    replacement: str | None = None
    fit: bool | None = None
    visible_skill_count_before: int | None = None
    visible_skill_count_after: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_report_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"step": self.step}
        if self.claim:
            payload["claim"] = self.claim
        if self.action:
            payload["action"] = self.action
        if self.reason:
            payload["reason"] = self.reason
        if self.replacement:
            payload["replacement"] = self.replacement
        if self.fit is not None:
            payload["fit"] = self.fit
        if self.visible_skill_count_before is not None:
            payload["visible_skill_count_before"] = self.visible_skill_count_before
        if self.visible_skill_count_after is not None:
            payload["visible_skill_count_after"] = self.visible_skill_count_after
        for key, value in self.metadata.items():
            if value in (None, "", [], {}):
                continue
            payload[key] = value
        return payload
