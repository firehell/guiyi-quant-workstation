"""Bounded durable source observations for forward reference projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json


MAX_CAPTURE_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class ForwardCapture:
    stream_id: str
    revision_id: str
    generation: int
    source_key: str
    bar_end: datetime
    observed_at: datetime
    source_kind: str
    input_payload: dict[str, object]
    source_proof: dict[str, object]
    eligibility: str

    def __post_init__(self) -> None:
        if not self.stream_id or not self.revision_id or not self.source_key or len(self.source_key) > 80:
            raise ValueError("CAPTURE_IDENTITY_INVALID")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("CAPTURE_GENERATION_INVALID")
        for value in (self.bar_end, self.observed_at):
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("CAPTURE_TIME_INVALID")
        if self.bar_end > self.observed_at or not self.source_kind or not self.eligibility:
            raise ValueError("CAPTURE_SOURCE_INVALID")
        if not isinstance(self.input_payload, dict) or not isinstance(self.source_proof, dict):
            raise ValueError("CAPTURE_PAYLOAD_INVALID")
        if len(self.canonical_text.encode()) > MAX_CAPTURE_BYTES:
            raise ValueError("CAPTURE_BUDGET_EXCEEDED")

    @property
    def canonical_text(self) -> str:
        return json.dumps({
            "stream_id": self.stream_id, "revision_id": self.revision_id,
            "generation": self.generation, "source_key": self.source_key,
            "bar_end": self.bar_end.isoformat(), "observed_at": self.observed_at.isoformat(),
            "source_kind": self.source_kind, "input_payload": self.input_payload,
            "source_proof": self.source_proof, "eligibility": self.eligibility,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)

    @property
    def capture_hash(self) -> str:
        return sha256(self.canonical_text.encode()).hexdigest()

    @property
    def batch_key(self) -> str:
        return f"capture:{self.source_key}"

    def evidence(self) -> dict[str, object]:
        return {"forward_capture_v1": {
            "generation": self.generation, "hash": self.capture_hash,
            "source_key": self.source_key, "bar_end": self.bar_end.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "source_kind": self.source_kind, "input_payload": self.input_payload,
            "source_proof": self.source_proof, "eligibility": self.eligibility,
        }}
