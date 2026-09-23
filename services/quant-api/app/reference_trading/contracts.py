"""Strict application DTOs for reference-trading persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Generic, Literal, TypeVar

from guiyi_quant.reference_trading import (
    RecordingMode,
    ReferenceAction,
    ReferenceTransition,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint


ItemT = TypeVar("ItemT")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _non_negative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _sha256(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{name} must be a lowercase sha256")
    return text


def _canonical_manifest(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("manifest must be finite canonical JSON") from error


def manifest_sha256(value: object) -> str:
    return sha256(_canonical_manifest(value).encode()).hexdigest()


def _append_only(prior: object, new: object) -> bool:
    if isinstance(prior, dict) and isinstance(new, dict):
        return all(key in new and _append_only(value, new[key]) for key, value in prior.items())
    if isinstance(prior, list) and isinstance(new, list):
        if (
            len(prior) == len(new) == 3
            and all(isinstance(item, str) for item in (*prior, *new))
            and prior[:2] == new[:2]
        ):
            try:
                return date.fromisoformat(new[2]) >= date.fromisoformat(prior[2])
            except ValueError:
                pass
        return len(new) >= len(prior) and all(
            _append_only(value, new[index]) for index, value in enumerate(prior)
        )
    return type(prior) is type(new) and prior == new


def _prior_projection(prior: object, new: object) -> object:
    """Project the new manifest onto the exact prior prefix after validation."""
    if isinstance(prior, dict) and isinstance(new, dict):
        return {key: _prior_projection(value, new[key]) for key, value in prior.items()}
    if isinstance(prior, list) and isinstance(new, list):
        if (
            len(prior) == len(new) == 3
            and all(isinstance(item, str) for item in (*prior, *new))
            and prior[:2] == new[:2]
        ):
            try:
                if date.fromisoformat(new[2]) >= date.fromisoformat(prior[2]):
                    return list(prior)
            except ValueError:
                pass
        return [
            _prior_projection(value, new[index])
            for index, value in enumerate(prior)
        ]
    return new


@dataclass(frozen=True, slots=True)
class DependencyAdvance:
    expected_prior_digest: str
    new_manifest: dict[str, object]
    new_digest: str
    prior_prefix_digest: str
    new_prefix_digest: str
    appended_ranges: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "expected_prior_digest", "new_digest", "prior_prefix_digest",
            "new_prefix_digest",
        ):
            _sha256(getattr(self, name), name)
        if not isinstance(self.new_manifest, dict) or not self.new_manifest:
            raise ValueError("new_manifest must be non-empty")
        object.__setattr__(self, "appended_ranges", tuple(self.appended_ranges))
        if not self.appended_ranges or any(
            not isinstance(item, str) or not item for item in self.appended_ranges
        ):
            raise ValueError("appended_ranges must be non-empty text")
        if manifest_sha256(self.new_manifest) != self.new_digest:
            raise ValueError("new dependency digest does not match manifest")


def prove_dependency_append(
    prior_manifest: dict[str, object],
    new_manifest: dict[str, object],
    *,
    appended_ranges: tuple[str, ...],
) -> DependencyAdvance:
    """Create a proof only after validating structural prefix preservation."""
    if (
        not isinstance(prior_manifest, dict)
        or not prior_manifest
        or not isinstance(new_manifest, dict)
        or not new_manifest
        or not _append_only(prior_manifest, new_manifest)
        or prior_manifest == new_manifest
    ):
        raise ValueError("dependency manifest is not append-only")
    prior_digest = manifest_sha256(prior_manifest)
    new_digest = manifest_sha256(new_manifest)
    new_prefix_digest = manifest_sha256(
        _prior_projection(prior_manifest, new_manifest)
    )
    return DependencyAdvance(
        expected_prior_digest=prior_digest,
        new_manifest=new_manifest,
        new_digest=new_digest,
        prior_prefix_digest=prior_digest,
        new_prefix_digest=new_prefix_digest,
        appended_ranges=appended_ranges,
    )


def validate_dependency_advance(
    prior_manifest: dict[str, object], advance: DependencyAdvance,
) -> None:
    if (
        manifest_sha256(prior_manifest) != advance.expected_prior_digest
        or advance.prior_prefix_digest != advance.expected_prior_digest
        or advance.new_prefix_digest != advance.expected_prior_digest
        or not _append_only(prior_manifest, advance.new_manifest)
        or prior_manifest == advance.new_manifest
        or manifest_sha256(
            _prior_projection(prior_manifest, advance.new_manifest)
        ) != advance.new_prefix_digest
    ):
        raise ValueError("dependency manifest is not append-only")


@dataclass(frozen=True, slots=True)
class CheckpointToken:
    stream_id: str
    revision_id: str
    seq: int
    row_version: int
    state_hash: str

    def __post_init__(self) -> None:
        _text(self.stream_id, "stream_id")
        _text(self.revision_id, "revision_id")
        _non_negative(self.seq, "seq")
        _non_negative(self.row_version, "row_version")
        _sha256(self.state_hash, "state_hash")


@dataclass(frozen=True, slots=True)
class StoredStream:
    stream_id: str
    enabled: bool
    active_revision_id: str | None
    latest_seq: int
    row_version: int
    health: str


@dataclass(frozen=True, slots=True)
class SeedChunk:
    batch_key: str
    index: int
    count: int
    root_hash: str
    content: str

    def __post_init__(self) -> None:
        _text(self.batch_key, "batch_key")
        _non_negative(self.index, "index")
        if type(self.count) is not int or self.count <= 0:
            raise ValueError("count must be a positive integer")
        if self.index >= self.count:
            raise ValueError("index must be less than count")
        _sha256(self.root_hash, "root_hash")
        if not isinstance(self.content, str):
            raise TypeError("content must be text")
        if len(self.content.encode()) > 262_144:
            raise ValueError("seed chunk exceeds size limit")


@dataclass(frozen=True, slots=True)
class SourceAction:
    action: ReferenceAction
    observed_at: datetime | None = None
    origin_revision_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ReferenceAction):
            raise TypeError("action must be ReferenceAction")
        if self.action.stream.recording_mode is RecordingMode.FORWARD_OBSERVATION:
            if (
                not isinstance(self.observed_at, datetime)
                or self.observed_at.tzinfo is None
                or self.observed_at.utcoffset() is None
            ):
                raise ValueError("forward action requires timezone-aware observed_at")
        elif self.observed_at is not None:
            raise ValueError("historical action must not set observed_at")
        if self.origin_revision_id is not None:
            _text(self.origin_revision_id, "origin_revision_id")


@dataclass(frozen=True, slots=True)
class PreparedBatch:
    stream_id: str
    revision_id: str
    batch_key: str
    expected: CheckpointToken
    dependency_manifest: dict[str, object]
    source_actions: tuple[SourceAction, ...]
    transitions: tuple[ReferenceTransition, ...]
    checkpoint: AdapterCheckpoint[object]
    strategy_schema: str
    source_evidence: dict[str, object]
    input_observed_at: datetime | None = None
    dependency_advance: DependencyAdvance | None = None

    def __post_init__(self) -> None:
        for name in ("stream_id", "revision_id", "batch_key", "strategy_schema"):
            _text(getattr(self, name), name)
        if not isinstance(self.expected, CheckpointToken):
            raise TypeError("expected must be CheckpointToken")
        if (
            self.expected.stream_id != self.stream_id
            or self.expected.revision_id != self.revision_id
        ):
            raise ValueError("expected token identity does not match batch")
        object.__setattr__(self, "source_actions", tuple(self.source_actions))
        object.__setattr__(self, "transitions", tuple(self.transitions))
        if not all(isinstance(item, SourceAction) for item in self.source_actions):
            raise TypeError("source_actions must contain SourceAction")
        if not all(isinstance(item, ReferenceTransition) for item in self.transitions):
            raise TypeError("transitions must contain ReferenceTransition")
        if not self.transitions:
            raise ValueError("transitions must not be empty")
        if self.checkpoint.stream is None or self.checkpoint.reference_state is None:
            raise ValueError("checkpoint must include stream and reference_state")
        if self.checkpoint.stream.stream_id != self.stream_id:
            raise ValueError("checkpoint stream does not match batch")
        if self.checkpoint.stream.recording_mode is RecordingMode.FORWARD_OBSERVATION:
            if (
                not isinstance(self.input_observed_at, datetime)
                or self.input_observed_at.tzinfo is None
                or self.input_observed_at.utcoffset() is None
            ):
                raise ValueError("forward batch requires timezone-aware input_observed_at")
        elif self.input_observed_at is not None:
            raise ValueError("historical batch must not set input_observed_at")
        if self.dependency_advance is not None:
            if not isinstance(self.dependency_advance, DependencyAdvance):
                raise TypeError("dependency_advance must be DependencyAdvance")
            if self.dependency_advance.new_manifest != self.dependency_manifest:
                raise ValueError("dependency advance manifest does not match batch")
        if self.transitions[-1].state != self.checkpoint.reference_state:
            raise ValueError("checkpoint reference state does not match final transition")


@dataclass(frozen=True, slots=True)
class CommitResult:
    outcome: Literal["committed", "noop"]
    revision_id: str
    seq: int
    checkpoint_hash: str

    def __post_init__(self) -> None:
        if self.outcome not in {"committed", "noop"}:
            raise ValueError("outcome is invalid")
        _text(self.revision_id, "revision_id")
        _non_negative(self.seq, "seq")
        _sha256(self.checkpoint_hash, "checkpoint_hash")


@dataclass(frozen=True, slots=True)
class StoredRevisionState:
    stream: StoredStream
    revision_id: str
    revision_status: str
    dependency_manifest: dict[str, object]
    dependency_digest: str
    checkpoint: CheckpointToken
    checkpoint_batch_key: str
    source_evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    stream_id: str
    revision_id: str
    seq: int

    def __post_init__(self) -> None:
        _text(self.stream_id, "stream_id")
        _text(self.revision_id, "revision_id")
        _non_negative(self.seq, "seq")


@dataclass(frozen=True, slots=True)
class StoredPage(Generic[ItemT]):
    items: tuple[ItemT, ...]
    next_key: tuple[object, ...] | None
    snapshot: SnapshotIdentity

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if not isinstance(self.snapshot, SnapshotIdentity):
            raise TypeError("snapshot must be SnapshotIdentity")
