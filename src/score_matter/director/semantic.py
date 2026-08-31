from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from score_matter.errors import DirectorError


AXIS_NAMES = (
    "palette",
    "register",
    "density",
    "articulation",
    "harmony",
    "rhythm",
    "energy",
    "foreground_occupancy",
    "entry_exit",
    "loop_behaviour",
)

_FORBIDDEN_KEYS = {
    "approval",
    "approved",
    "creative_review",
    "human_review",
    "package_approval",
    "plan_review",
    "release_decision",
    "rights_review",
    "tool_calls",
    "function_call",
    "shell_command",
    "consumer_verification",
}
_FORBIDDEN_CLAIM_PATTERNS = (
    re.compile(r"\b(?:approved|rights[- ]cleared|release[- ]ready|package[- ]approved|consumer[- ]verified)\b", re.I),
    re.compile(r"(?:已批准|权利已清除|版权已确认|可商用|可发布|已在游戏验证|发布就绪)"),
)


def reject_authority_escalation(value: Any) -> None:
    """Reject authority-bearing keys and affirmative claims in agent content."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _FORBIDDEN_KEYS:
                raise DirectorError(
                    f"director output contains forbidden authority key: {key}",
                    code="director_authority_escalation",
                )
            reject_authority_escalation(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            reject_authority_escalation(item)
        return
    if isinstance(value, str):
        for pattern in _FORBIDDEN_CLAIM_PATTERNS:
            if pattern.search(value):
                raise DirectorError(
                    "director output contains a forbidden authority claim",
                    code="director_authority_escalation",
                )


def direction_axis_difference_count(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    """Count deterministic normalized differences across the ten frozen axes."""

    return sum(
        _normalize_axis(left.get(name)) != _normalize_axis(right.get(name))
        for name in AXIS_NAMES
    )


def has_material_direction_pair(directions: Sequence[Mapping[str, Any]]) -> bool:
    for left_index, left in enumerate(directions):
        left_axes = left.get("axes")
        if not isinstance(left_axes, Mapping):
            continue
        for right in directions[left_index + 1 :]:
            right_axes = right.get("axes")
            if isinstance(right_axes, Mapping) and direction_axis_difference_count(
                left_axes, right_axes
            ) >= 2:
                return True
    return False


def contains_frozen_phrase(text: str, phrase: str) -> bool:
    """Match a hidden phrase without treating it as an arbitrary substring.

    ASCII letters and digits at either edge require an ASCII word boundary, so
    a frozen claim such as ``approved`` does not match ``unapproved``.  Other
    scripts retain exact case-folded substring matching because their word
    segmentation cannot be inferred safely by this deterministic validator.
    """

    needle = phrase.casefold()
    if not needle:
        return False
    prefix = r"(?<![a-z0-9])" if needle[0].isascii() and needle[0].isalnum() else ""
    suffix = r"(?![a-z0-9])" if needle[-1].isascii() and needle[-1].isalnum() else ""
    if prefix or suffix:
        return re.search(f"{prefix}{re.escape(needle)}{suffix}", text.casefold()) is not None
    return needle in text.casefold()


def _normalize_axis(value: Any) -> str:
    if not isinstance(value, str):
        return repr(value)
    return " ".join(value.casefold().split())
