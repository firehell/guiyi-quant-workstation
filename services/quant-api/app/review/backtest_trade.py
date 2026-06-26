from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.review import ReviewNote, ReviewTag
from app.schemas.review import DEFAULT_MISTAKE_TAGS
from app.services.review_center import review_payload, tag_payload


def apply_review_fields(note: ReviewNote, data: dict[str, Any]) -> None:
    for key in ("entry_reason", "exit_reason", "market_phase", "is_system_compliant", "mistake_tags", "emotion_tags", "review_score", "ai_summary"):
        if key in data:
            setattr(note, key, data[key])
    if "setup_tags" in data:
        note.rule_tags = data["setup_tags"]
    elif "rule_tags" in data:
        note.rule_tags = data["rule_tags"]
    if "improvement_note" in data:
        note.lesson = data["improvement_note"]
    elif "lesson" in data:
        note.lesson = data["lesson"]
    extra = dict(note.extra or {})
    if "execution_note" in data:
        extra["execution_note"] = data["execution_note"]
    note.extra = extra
    if "screenshot_path" in data:
        note.screenshot_paths = [data["screenshot_path"]] if data["screenshot_path"] else []
    elif "screenshot_paths" in data:
        note.screenshot_paths = data["screenshot_paths"]


def review_response(note: ReviewNote, *, include_source: bool = False, session: Session | None = None) -> dict[str, Any]:
    payload = review_payload(note, include_source=include_source, session=session)
    screenshot_paths = list(payload.get("screenshot_paths") or [])
    extra = dict(payload.get("extra") or {})
    payload.update(
        {
            "review_object_type": _review_object_type(note.source_type),
            "setup_tags": list(payload.get("rule_tags") or []),
            "execution_note": extra.get("execution_note"),
            "improvement_note": payload.get("lesson"),
            "screenshot_path": screenshot_paths[0] if screenshot_paths else None,
        }
    )
    return payload


def tag_response(tag: ReviewTag) -> dict[str, Any]:
    return tag_payload(tag)


def default_mistake_tag_payloads(existing_names: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": -index,
            "tag_type": "mistake",
            "name": name,
            "description": "内置错误标签",
            "sort_order": index,
            "is_active": True,
        }
        for index, name in enumerate(DEFAULT_MISTAKE_TAGS, start=1)
        if name not in existing_names
    ]


def _review_object_type(source_type: str) -> str:
    if source_type == "backtest_trade":
        return "backtest_trade"
    if source_type == "manual_trade":
        return "manual_trade"
    return source_type
