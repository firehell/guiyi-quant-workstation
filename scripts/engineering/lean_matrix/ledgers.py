"""Fail-closed recovery from local Git and digest-bound review artifacts."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Mapping

from .briefs import intake_digest
from .contracts import (
    DocumentIntakeV1,
    FinalDecisionV1,
    HandoffReportV1,
    ReviewPackageV1,
    RoleBriefV1,
)
from .digests import semantic_digest
from .errors import LeanMatrixError
from .review_git import is_ancestor, observe_current_head
from .workspace import intake_workspace


MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
ARTIFACT_KEYS = frozenset({"path", "digest"})
ROUND_KEYS = frozenset({
    "round", "implementer_brief", "implementer_handoff", "reviewer_brief",
    "review_package", "final_decision", "specialist_evidence",
})
LEDGER_KEYS = frozenset({"schema_version", "intake_digest", "rounds"})


def _mapping(raw: object, name: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise LeanMatrixError("invalid_mapping", f"{name} must be a JSON object")
    return raw


def _keys(data: Mapping[str, object], expected: frozenset[str], name: str) -> None:
    if set(data) != expected:
        raise LeanMatrixError(
            "unexpected_keys", f"{name} keys must be exactly {sorted(expected)}",
        )


def _round(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 3:
        raise LeanMatrixError("invalid_round", "ledger round must be an integer from zero through three")
    return value


def _read_regular_json(path: Path) -> tuple[object, bytes]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise LeanMatrixError(
            "review_artifact_missing", "digest-bound review artifact is missing",
        ) from exc
    except OSError as exc:
        raise LeanMatrixError(
            "review_artifact_invalid", "review artifact metadata is unavailable",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise LeanMatrixError(
            "review_artifact_symlink", "review artifacts must not be symbolic links",
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise LeanMatrixError(
            "review_artifact_not_regular", "review artifact must be a regular file",
        )
    if metadata.st_size > MAX_ARTIFACT_BYTES:
        raise LeanMatrixError(
            "review_artifact_too_large", "review artifact exceeds the 8 MiB limit",
        )
    try:
        content = path.read_bytes()
        return json.loads(content.decode("utf-8")), content
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeanMatrixError(
            "review_artifact_invalid", "review artifact must contain valid UTF-8 JSON",
        ) from exc


def _safe_artifact_path(
    repo_root: Path,
    workspace: Path,
    raw_path: object,
    name: str,
) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise LeanMatrixError("review_artifact_path_invalid", f"{name} path is invalid")
    pure = Path(raw_path)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise LeanMatrixError("review_artifact_path_invalid", f"{name} path is unsafe")
    repo = repo_root.resolve()
    candidate = repo.joinpath(*pure.parts)
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise LeanMatrixError(
            "review_artifact_outside_workspace", f"{name} must stay in the intake workspace",
        ) from exc
    current = repo
    for component in pure.parts[:-1]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise LeanMatrixError(
                "review_artifact_missing", f"{name} parent is missing",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise LeanMatrixError(
                "review_artifact_symlink", f"{name} contains a symlink component",
            )
    return pure.as_posix(), candidate


def _artifact(
    repo_root: Path,
    workspace: Path,
    raw: object,
    name: str,
) -> tuple[str, object]:
    data = _mapping(raw, name)
    _keys(data, ARTIFACT_KEYS, name)
    relative, path = _safe_artifact_path(repo_root, workspace, data["path"], name)
    supplied_digest = data["digest"]
    if (
        not isinstance(supplied_digest, str)
        or not supplied_digest.startswith("sha256:")
        or len(supplied_digest) != 71
    ):
        raise LeanMatrixError(
            "invalid_digest", f"{name} digest must be a SHA-256 digest",
        )
    parsed, content = _read_regular_json(path)
    actual = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual != supplied_digest:
        raise LeanMatrixError(
            "review_artifact_digest_mismatch", f"{name} digest does not match local bytes",
        )
    return relative, parsed


def _expected_companion(report_path: str, name: str) -> str:
    return (Path(report_path).parent / name).as_posix()


def recover_review_ledger(
    repo_root: Path,
    intake: DocumentIntakeV1,
    ledger_path: Path,
    *,
    round_zero_brief: RoleBriefV1,
) -> tuple[FinalDecisionV1, ...]:
    """Recover a complete chain; conversation history is neither accepted nor consulted."""
    if not isinstance(intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "recovery requires a trusted intake")
    if (
        not isinstance(round_zero_brief, RoleBriefV1)
        or round_zero_brief.role != "implementer"
        or round_zero_brief.round != 0
        or round_zero_brief.intake_digest != intake_digest(intake)
    ):
        raise LeanMatrixError(
            "invalid_round_zero_brief", "recovery requires the trusted round-zero implementer brief",
        )
    workspace = intake_workspace(repo_root, intake)
    expected_ledger = workspace / "review-ledger.json"
    if ledger_path.resolve() != expected_ledger.resolve():
        raise LeanMatrixError(
            "review_ledger_path_mismatch", "recovery uses only the fixed intake ledger path",
        )
    raw, _ = _read_regular_json(ledger_path)
    ledger = _mapping(raw, "review ledger")
    _keys(ledger, LEDGER_KEYS, "review ledger")
    if ledger["schema_version"] != 1:
        raise LeanMatrixError("invalid_schema_version", "review ledger schema_version must equal 1")
    if ledger["intake_digest"] != intake_digest(intake):
        raise LeanMatrixError("review_ledger_intake_mismatch", "ledger does not bind the trusted intake")
    raw_rounds = ledger["rounds"]
    if not isinstance(raw_rounds, list) or not raw_rounds:
        raise LeanMatrixError("review_chain_incomplete", "review ledger requires at least round zero")
    current_head = observe_current_head(repo_root)
    decisions: list[FinalDecisionV1] = []
    packages: list[ReviewPackageV1] = []
    implementation_contexts: set[str] = set()
    reviewer_contexts: set[str] = set()
    previous_head: str | None = None
    previous_specialist_head: str | None = None
    for expected_round, raw_entry in enumerate(raw_rounds):
        entry = _mapping(raw_entry, "review ledger round")
        _keys(entry, ROUND_KEYS, "review ledger round")
        round_number = _round(entry["round"])
        if round_number != expected_round or expected_round > 3:
            raise LeanMatrixError(
                "review_chain_gap", "review rounds must be contiguous from zero through three",
            )
        implementer_brief_path, raw_implementer_brief = _artifact(
            repo_root, workspace, entry["implementer_brief"], "implementer brief",
        )
        implementer_brief = RoleBriefV1.from_mapping(
            raw_implementer_brief,
            document_intake=intake,
            round_zero_brief=None if round_number == 0 else round_zero_brief,
        )
        if round_number == 0 and implementer_brief.to_dict() != round_zero_brief.to_dict():
            raise LeanMatrixError(
                "round_zero_brief_mismatch", "ledger cannot replace the trusted implementer identity",
            )
        if implementer_brief.context_id != round_zero_brief.context_id:
            raise LeanMatrixError(
                "implementer_context_changed", "every repair round must reuse the round-zero implementer",
            )
        expected_implementer_brief_path = _expected_companion(
            implementer_brief.report_path, "role-brief.json",
        )
        if implementer_brief_path != expected_implementer_brief_path:
            raise LeanMatrixError(
                "review_artifact_path_mismatch", "implementer brief is not at its derived path",
            )
        handoff_path, raw_handoff = _artifact(
            repo_root, workspace, entry["implementer_handoff"], "implementer handoff",
        )
        if handoff_path != implementer_brief.report_path:
            raise LeanMatrixError(
                "review_artifact_path_mismatch", "implementer handoff is not at its derived path",
            )
        implementer_handoff = HandoffReportV1.from_mapping(
            raw_handoff, role_brief=implementer_brief,
        )
        reviewer_brief_path, raw_reviewer_brief = _artifact(
            repo_root, workspace, entry["reviewer_brief"], "reviewer brief",
        )
        reviewer_brief = RoleBriefV1.from_mapping(
            raw_reviewer_brief,
            document_intake=intake,
            round_zero_brief=None if round_number == 0 else round_zero_brief,
        )
        if reviewer_brief.role != "reviewer" or reviewer_brief.round != round_number:
            raise LeanMatrixError(
                "reviewer_brief_mismatch", "ledger reviewer brief has the wrong role or round",
            )
        if reviewer_brief_path != _expected_companion(
            reviewer_brief.report_path, "role-brief.json",
        ):
            raise LeanMatrixError(
                "review_artifact_path_mismatch", "reviewer brief is not at its derived path",
            )
        raw_specialists = entry["specialist_evidence"]
        if not isinstance(raw_specialists, list):
            raise LeanMatrixError(
                "specialist_evidence_invalid", "specialist evidence must be a JSON list",
            )
        specialist_evidence: list[tuple[RoleBriefV1, HandoffReportV1]] = []
        for specialist_entry in raw_specialists:
            specialist = _mapping(specialist_entry, "specialist evidence")
            _keys(specialist, frozenset({"brief", "handoff"}), "specialist evidence")
            specialist_brief_path, raw_specialist_brief = _artifact(
                repo_root, workspace, specialist["brief"], "specialist brief",
            )
            specialist_brief = RoleBriefV1.from_mapping(
                raw_specialist_brief, document_intake=intake,
            )
            specialist_handoff_path, raw_specialist_handoff = _artifact(
                repo_root, workspace, specialist["handoff"], "specialist handoff",
            )
            if (
                specialist_brief_path
                != _expected_companion(specialist_brief.report_path, "role-brief.json")
                or specialist_handoff_path != specialist_brief.report_path
            ):
                raise LeanMatrixError(
                    "review_artifact_path_mismatch", "specialist artifacts are not at derived paths",
                )
            specialist_handoff = HandoffReportV1.from_mapping(
                raw_specialist_handoff, role_brief=specialist_brief,
            )
            specialist_evidence.append((specialist_brief, specialist_handoff))
            implementation_contexts.add(specialist_brief.context_id)
        package_path, raw_package = _artifact(
            repo_root, workspace, entry["review_package"], "review package",
        )
        if package_path != _expected_companion(reviewer_brief.report_path, "review-package.json"):
            raise LeanMatrixError(
                "review_artifact_path_mismatch", "review package is not at its derived path",
            )
        package = ReviewPackageV1.from_mapping(
            raw_package,
            repo_root=repo_root,
            document_intake=intake,
            implementer_brief=implementer_brief,
            implementer_handoff=implementer_handoff,
            reviewer_brief=reviewer_brief,
            specialist_evidence=tuple(specialist_evidence),
            require_current_head=round_number == len(raw_rounds) - 1,
        )
        specialist_reviewed_head = (
            specialist_evidence[0][1].exact_head_sha if specialist_evidence else None
        )
        if previous_head is not None and not is_ancestor(repo_root, previous_head, package.exact_head_sha):
            raise LeanMatrixError(
                "review_head_rewritten", "repair round HEAD must descend from prior reviewed HEAD",
            )
        if round_number > 0:
            predecessor_package = packages[-1]
            if (
                package.specialist_evidence_digests
                != predecessor_package.specialist_evidence_digests
                or specialist_reviewed_head != previous_specialist_head
            ):
                raise LeanMatrixError(
                    "specialist_predecessor_mismatch",
                    "repair package must retain the predecessor specialist evidence and reviewed HEAD",
                )
        previous_head = package.exact_head_sha
        previous_specialist_head = specialist_reviewed_head
        decision_path, raw_decision = _artifact(
            repo_root, workspace, entry["final_decision"], "final decision",
        )
        if decision_path != reviewer_brief.report_path:
            raise LeanMatrixError(
                "review_artifact_path_mismatch", "final decision is not at its derived path",
            )
        decision = FinalDecisionV1.from_mapping(raw_decision, review_package=package)
        if round_number > 0:
            predecessor = decisions[-1]
            predecessor_digest = semantic_digest(predecessor.to_dict())
            if predecessor.decision != "要求修正后再集成" or not predecessor.has_load_bearing_findings:
                raise LeanMatrixError(
                    "unnecessary_fix_round", "repair rounds require unresolved prior load-bearing findings",
                )
            if (
                implementer_brief.predecessor_decision_digest != predecessor_digest
                or reviewer_brief.predecessor_decision_digest != predecessor_digest
                or implementer_handoff.predecessor_decision_digest != predecessor_digest
            ):
                raise LeanMatrixError(
                    "review_predecessor_mismatch", "repair artifacts do not bind the prior decision",
                )
        implementation_contexts.add(implementer_brief.context_id)
        reviewer_contexts.add(reviewer_brief.context_id)
        if implementation_contexts & reviewer_contexts:
            raise LeanMatrixError(
                "context_reuse", "historical implementation and reviewer context sets must be disjoint",
            )
        decisions.append(decision)
        packages.append(package)
        if decision.decision == "阻塞" and round_number != len(raw_rounds) - 1:
            raise LeanMatrixError(
                "round_three_review_blocked", "a blocked round-three decision terminates recovery",
            )
    if previous_head != current_head:
        raise LeanMatrixError(
            "stale_package_head", "latest recovered decision does not bind current local HEAD",
        )
    return tuple(decisions)
