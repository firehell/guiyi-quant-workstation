from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_MISTAKE_TAGS = ["追价", "震荡区", "逆势", "过早进场", "过早止损", "未按系统执行"]


class ReviewFromBacktestTradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_reason: str | None = None
    exit_reason: str | None = None
    mistake_tags: list[str] | None = None
    setup_tags: list[str] | None = None
    execution_note: str | None = None
    improvement_note: str | None = None
    screenshot_path: str | None = None

    @field_validator("mistake_tags", "setup_tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item.strip()]


class ReviewUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_reason: str | None = None
    exit_reason: str | None = None
    market_phase: str | None = None
    is_system_compliant: bool | None = None
    mistake_tags: list[str] | None = None
    setup_tags: list[str] | None = None
    rule_tags: list[str] | None = None
    emotion_tags: list[str] | None = None
    execution_note: str | None = None
    improvement_note: str | None = None
    lesson: str | None = None
    screenshot_path: str | None = None
    screenshot_paths: list[str] | None = None
    review_score: int | None = Field(default=None, ge=0, le=100)
    ai_summary: str | None = None

    @field_validator("mistake_tags", "setup_tags", "rule_tags", "emotion_tags", "screenshot_paths")
    @classmethod
    def validate_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item.strip()]


class ReviewAttachmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    file_type: str | None = "image"
    title: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
