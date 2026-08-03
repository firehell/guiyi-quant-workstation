"""Fixed, read-only local Git observations shared by review builders and ledgers."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contracts import ReviewPackageV1
from .errors import LeanMatrixError


MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SIMPLE_STATUS_RE = re.compile(r"^[ADMTUXB]$")
SIMILARITY_STATUS_RE = re.compile(r"^([RC])([0-9]{1,3})$")


@dataclass(frozen=True, slots=True)
class GitDiffObservation:
    changed_paths: tuple[str, ...]
    diff_digest: str


def validate_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise LeanMatrixError("invalid_sha", f"{field} must be 40 lowercase hexadecimal characters")
    return value


def _git_environment() -> dict[str, str]:
    return {
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _run_git(repo_root: Path, arguments: tuple[str, ...]) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            env=_git_environment(),
            shell=False,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise LeanMatrixError("git_observation_failed", "local Git observation could not start") from exc
    if len(result.stdout) > MAX_GIT_OUTPUT_BYTES or len(result.stderr) > MAX_GIT_OUTPUT_BYTES:
        raise LeanMatrixError("git_output_too_large", "local Git output exceeds the 8 MiB limit")
    if result.returncode != 0:
        raise LeanMatrixError("git_observation_failed", "fixed local Git observation failed")
    if result.stderr:
        raise LeanMatrixError(
            "git_observation_stderr",
            "successful fixed local Git observation produced unexpected stderr",
        )
    return result.stdout


def _verify_commit(repo_root: Path, sha: str, field: str) -> None:
    try:
        _run_git(repo_root, ("cat-file", "-e", f"{sha}^{{commit}}"))
    except LeanMatrixError as exc:
        if exc.error_type == "git_observation_failed":
            raise LeanMatrixError("git_commit_missing", f"{field} is not a local commit") from exc
        raise


def observe_current_head(repo_root: Path) -> str:
    """Return the current local HEAD commit through one fixed, read-only Git command."""
    try:
        value = _run_git(repo_root, ("rev-parse", "--verify", "HEAD^{commit}"))
        decoded = value.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise LeanMatrixError("git_sha_invalid", "local HEAD is not an ASCII SHA") from exc
    return validate_sha(decoded, "current_head_sha")


def _repository_path(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LeanMatrixError("git_path_encoding_invalid", "changed paths must be valid UTF-8") from exc
    pure = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or ".." in pure.parts
        or value in {".", ""}
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise LeanMatrixError("git_path_invalid", "Git returned an unsafe repository path")
    return value


def _status(raw: bytes) -> tuple[str, bool]:
    try:
        status = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise LeanMatrixError("git_status_invalid", "Git returned a non-ASCII change status") from exc
    if SIMPLE_STATUS_RE.fullmatch(status):
        return status, False
    similarity = SIMILARITY_STATUS_RE.fullmatch(status)
    if similarity is None or int(similarity.group(2)) > 100:
        raise LeanMatrixError("git_status_invalid", "Git returned an unsupported change status")
    return status, True


def _parse_name_status(raw: bytes) -> tuple[str, ...]:
    fields = raw.split(b"\0")
    if fields[-1:] == [b""]:
        fields.pop()
    paths: list[str] = []
    index = 0
    while index < len(fields):
        _, has_source = _status(fields[index])
        index += 1
        required = 2 if has_source else 1
        if len(fields) - index < required:
            raise LeanMatrixError("git_status_ambiguous", "Git returned a truncated name-status record")
        if has_source:
            paths.append(_repository_path(fields[index]))
            index += 1
        paths.append(_repository_path(fields[index]))
        index += 1
    return tuple(sorted(set(paths)))


def _parse_paths(raw: bytes, field: str) -> tuple[str, ...]:
    values = raw.split(b"\0")
    if values[-1:] == [b""]:
        values.pop()
    paths = tuple(_repository_path(value) for value in values)
    if len(paths) != len(set(paths)):
        raise LeanMatrixError("git_path_duplicate", f"Git returned duplicate {field} paths")
    return tuple(sorted(paths))


def validate_worktree_clean(repo_root: Path, allowed_workspace: Path) -> None:
    """Reject commit-affecting worktree state; ignored local assets are noncanonical."""
    repo = repo_root.resolve()
    workspace = allowed_workspace.resolve()
    try:
        workspace.relative_to(repo)
    except ValueError as exc:
        raise LeanMatrixError(
            "invalid_workspace_path", "allowed review workspace must be below repo_root",
        ) from exc
    tracked_commands = (
        ("diff", "--name-only", "-z", "--"),
        ("diff", "--cached", "--name-only", "-z", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z", "--"),
    )
    for arguments in tracked_commands:
        if _parse_paths(_run_git(repo, arguments), "dirty worktree"):
            raise LeanMatrixError(
                "worktree_not_clean",
                "staged, unstaged tracked, or untracked canonical changes are forbidden",
            )


def observe_exact_diff(repo_root: Path, base_sha: str, head_sha: str) -> GitDiffObservation:
    """Observe one exact local commit range with config-independent safe diff options."""
    base = validate_sha(base_sha, "base_sha")
    head = validate_sha(head_sha, "head_sha")
    _verify_commit(repo_root, base, "base_sha")
    _verify_commit(repo_root, head, "head_sha")
    name_status = _run_git(
        repo_root,
        (
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-status",
            "-z",
            "--find-renames=50%",
            "--find-copies=50%",
            "--find-copies-harder",
            "-l0",
            f"{base}..{head}",
            "--",
        ),
    )
    raw_diff = _run_git(
        repo_root,
        (
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames=50%",
            "--find-copies=50%",
            "--find-copies-harder",
            "-l0",
            "--binary",
            "--full-index",
            f"{base}..{head}",
        ),
    )
    return GitDiffObservation(
        changed_paths=_parse_name_status(name_status),
        diff_digest="sha256:" + hashlib.sha256(raw_diff).hexdigest(),
    )


def validate_stored_package_git(repo_root: Path, package: ReviewPackageV1) -> None:
    """Recompute every load-bearing local Git field of a stored package."""
    observation = observe_exact_diff(repo_root, package.exact_base_sha, package.exact_head_sha)
    if (
        package.changed_paths != observation.changed_paths
        or package.diff_digest != observation.diff_digest
    ):
        raise LeanMatrixError(
            "stored_package_git_mismatch",
            "stored review package does not match recomputed exact-head Git evidence",
        )


def is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    """Return whether one validated local commit is an ancestor of another."""
    before = validate_sha(ancestor, "ancestor_sha")
    after = validate_sha(descendant, "descendant_sha")
    _verify_commit(repo_root, before, "ancestor_sha")
    _verify_commit(repo_root, after, "descendant_sha")
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", before, after],
            cwd=repo_root,
            env=_git_environment(),
            shell=False,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise LeanMatrixError("git_observation_failed", "local Git ancestry observation failed") from exc
    if len(result.stdout) > MAX_GIT_OUTPUT_BYTES or len(result.stderr) > MAX_GIT_OUTPUT_BYTES:
        raise LeanMatrixError("git_output_too_large", "local Git output exceeds the 8 MiB limit")
    if result.returncode not in {0, 1}:
        raise LeanMatrixError("git_observation_failed", "fixed local Git ancestry observation failed")
    if result.stderr:
        raise LeanMatrixError(
            "git_observation_stderr",
            "successful fixed local Git ancestry observation produced unexpected stderr",
        )
    return result.returncode == 0
