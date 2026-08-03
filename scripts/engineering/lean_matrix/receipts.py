"""Validation helpers for plan-bound transition proposals and receipts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .contracts import TransitionProposalV1, TransitionReceiptV1
from .digests import semantic_digest
from .errors import LeanMatrixError


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    proposal: TransitionProposalV1
    receipt: TransitionReceiptV1


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    records: tuple[EvidenceRecord, ...]

    @property
    def attempted_actions(self) -> frozenset[str]:
        return frozenset(record.proposal.action for record in self.records)

    @property
    def successful_actions(self) -> frozenset[str]:
        return frozenset(
            record.proposal.action for record in self.records if record.receipt.result == "PASS"
        )


def artifact_name(transition_id: str, payload: dict[str, object]) -> str:
    digest = semantic_digest(payload).removeprefix("sha256:")
    return f"{transition_id}.{digest}.json"


def read_bound_artifact(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeanMatrixError("workspace_artifact_invalid", f"cannot read runtime artifact: {path.name}") from exc
    if not isinstance(raw, dict):
        raise LeanMatrixError("workspace_artifact_invalid", f"runtime artifact is not an object: {path.name}")
    stem, separator, digest_and_suffix = path.name.partition(".")
    expected_digest, separator_two, suffix = digest_and_suffix.partition(".")
    if not separator or not separator_two or suffix != "json" or not stem:
        raise LeanMatrixError("workspace_artifact_invalid", f"runtime artifact has invalid name: {path.name}")
    actual_digest = semantic_digest(raw).removeprefix("sha256:")
    if expected_digest != actual_digest:
        raise LeanMatrixError("workspace_artifact_tampered", f"runtime artifact digest mismatch: {path.name}")
    return raw
