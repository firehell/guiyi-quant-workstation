"""Reconstruct Lean Matrix execution state from local Git facts only."""

from __future__ import annotations

import os
import hashlib
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .contracts import ExecutionPlanV1, ObservedStateV1
from .digests import semantic_digest
from .errors import LeanMatrixError


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ObservedExecution:
    """Public observation plus the minimum derived facts needed by transitions."""

    state: ObservedStateV1
    phase: str
    base_matches_plan: bool
    task_head: str | None
    local_develop_sha: str | None
    remote_develop_sha: str
    local_branch_exists: bool
    remote_branch_exists: bool
    worktree_registered: bool


def _environment() -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
        if key in os.environ
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _git(
    repo: Path,
    arguments: Sequence[str],
    *,
    runner: Runner,
    error_type: str = "git_observation_failed",
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            ["git", "-c", "core.fsmonitor=false", *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            env=_environment(),
        )
    except OSError as exc:
        raise LeanMatrixError("git_unavailable", "git executable is unavailable") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "local Git observation failed").strip()
        raise LeanMatrixError(error_type, detail)
    return result


def _git_result(repo: Path, arguments: Sequence[str], *, runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            ["git", "-c", "core.fsmonitor=false", *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            env=_environment(),
        )
    except OSError as exc:
        raise LeanMatrixError("git_unavailable", "git executable is unavailable") from exc


def _optional_ref(repo: Path, ref: str, *, runner: Runner) -> str | None:
    result = _git_result(repo, ("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"), runner=runner)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise LeanMatrixError("invalid_git_sha", f"local Git ref {ref} returned an invalid SHA")
    return value


def _worktree_entries(output: str) -> dict[Path, dict[str, str]]:
    entries: dict[Path, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in [*output.splitlines(), ""]:
        if not line:
            if "worktree" in current:
                entries[Path(current["worktree"]).resolve()] = current
            current = {}
        else:
            key, _, value = line.partition(" ")
            current[key] = value
    return entries


def _nul_paths(output: str) -> set[str]:
    return {path for path in output.split("\0") if path}


def _is_ancestor(repo: Path, ancestor: str, descendant: str, *, runner: Runner) -> bool:
    result = _git_result(repo, ("merge-base", "--is-ancestor", ancestor, descendant), runner=runner)
    if result.returncode not in (0, 1):
        detail = (result.stderr or result.stdout or "merge-base failed").strip()
        raise LeanMatrixError("git_observation_failed", detail)
    return result.returncode == 0


def _state(payload: dict[str, object], *, local_facts: dict[str, object]) -> ObservedStateV1:
    payload["state_digest"] = semantic_digest({
        "observed_state": payload,
        "local_facts": local_facts,
    })
    return ObservedStateV1.from_mapping(payload)


def _worktree_content_digest(task_path: Path, changed_paths: set[str], *, runner: Runner) -> str:
    """Bind index metadata and working-tree bytes without persisting file content."""
    index = _git(task_path, ("ls-files", "--stage", "-z"), runner=runner).stdout
    entries: list[dict[str, str]] = []
    for relative in sorted(changed_paths):
        candidate = task_path / relative
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            entries.append({"path": relative, "kind": "missing", "digest": semantic_digest(None)})
            continue
        if stat.S_ISLNK(metadata.st_mode):
            payload = os.readlink(candidate).encode("utf-8", errors="surrogateescape")
            kind = "symlink"
        elif stat.S_ISREG(metadata.st_mode):
            try:
                payload = candidate.read_bytes()
            except OSError as exc:
                raise LeanMatrixError(
                    "worktree_content_unreadable",
                    f"cannot fingerprint changed path: {relative}",
                ) from exc
            kind = "file"
        else:
            payload = f"mode:{metadata.st_mode}".encode("ascii")
            kind = "other"
        entries.append({
            "path": relative,
            "kind": kind,
            "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
        })
    return semantic_digest({"index": index, "entries": entries})


def observe_execution_plan(
    plan: ExecutionPlanV1,
    repo_root: Path,
    *,
    runner: Runner = subprocess.run,
) -> ObservedExecution:
    """Observe a plan without fetch, network, locks, filesystem writes, or fallback refs."""
    if plan.base.ref != "origin/develop":
        raise LeanMatrixError("unsupported_base_ref", "local orchestration requires base.ref=origin/develop")
    repo = repo_root.resolve()
    top_level = _git(repo, ("rev-parse", "--show-toplevel"), runner=runner, error_type="not_a_git_repository")
    if Path(top_level.stdout.strip()).resolve() != repo:
        raise LeanMatrixError("repository_identity_mismatch", "repo_root must be the current Git worktree root")

    remote_develop = _git(
        repo,
        ("rev-parse", "--verify", f"{plan.base.ref}^{{commit}}"),
        runner=runner,
        error_type="base_ref_unavailable",
    ).stdout.strip()
    if len(remote_develop) != 40 or any(character not in "0123456789abcdef" for character in remote_develop):
        raise LeanMatrixError("invalid_base_sha", "local origin/develop did not resolve to one 40-hex commit")

    local_branch_ref = f"refs/heads/{plan.task.branch}"
    remote_branch_ref = f"refs/remotes/origin/{plan.task.branch}"
    local_task_head = _optional_ref(repo, local_branch_ref, runner=runner)
    remote_task_head = _optional_ref(repo, remote_branch_ref, runner=runner)
    worktrees = _worktree_entries(
        _git(repo, ("worktree", "list", "--porcelain"), runner=runner).stdout
    )
    for path, entry in worktrees.items():
        if entry.get("branch") in {"refs/heads/main", "refs/heads/master", "refs/heads/develop"}:
            status = _git(path, ("status", "--porcelain=v1", "-z"), runner=runner).stdout
            if status:
                raise LeanMatrixError(
                    "protected_checkout_dirty",
                    f"protected checkout must be clean before local orchestration: {path}",
                )
    task_path = Path(plan.task.worktree).resolve()
    worktree_registered = task_path in worktrees
    local_develop = _optional_ref(repo, "refs/heads/develop", runner=runner)

    branch: str | None = None
    worktree: str | None = None
    task_head = local_task_head or remote_task_head
    merge_state = "NOT_RUN"
    phase = "planned"
    dirty = False
    changed_paths: set[str] = set()
    cleanup_safe = False
    content_digest: str | None = None
    if worktree_registered:
        entry_branch = worktrees[task_path].get("branch", "").removeprefix("refs/heads/")
        actual_branch = _git(task_path, ("branch", "--show-current"), runner=runner).stdout.strip()
        if entry_branch != plan.task.branch or actual_branch != plan.task.branch:
            raise LeanMatrixError(
                "worktree_identity_mismatch",
                "planned worktree is registered to a different branch",
            )
        actual_head = _git(task_path, ("rev-parse", "HEAD"), runner=runner).stdout.strip()
        if task_head is not None and actual_head != task_head:
            raise LeanMatrixError("worktree_identity_mismatch", "task branch and worktree HEAD differ")
        task_head = actual_head
        status = _git(task_path, ("status", "--porcelain=v1", "-z"), runner=runner).stdout
        dirty = bool(status)
        changed_paths |= _nul_paths(
            _git(
                task_path,
                ("diff", "--name-only", "-z", f"{plan.base.expected_sha}...HEAD"),
                runner=runner,
            ).stdout
        )
        for arguments in (
            ("diff", "--cached", "--name-only", "-z"),
            ("diff", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            changed_paths |= _nul_paths(_git(task_path, arguments, runner=runner).stdout)
        content_digest = _worktree_content_digest(task_path, changed_paths, runner=runner)
        local_contains = bool(local_develop) and _is_ancestor(
            repo, task_head, "refs/heads/develop", runner=runner,
        )
        remote_contains = _is_ancestor(repo, task_head, plan.base.ref, runner=runner)
        merged = local_contains and remote_contains
        merge_state = "PASS" if merged else "FAIL"
        cleanup_safe = merged and not dirty and task_head != plan.base.expected_sha
        branch = actual_branch
        worktree = str(task_path)
        phase = "merged-develop-observed" if cleanup_safe else "implementation-ready"
    elif task_head is not None:
        branch = plan.task.branch
        local_contains = bool(local_develop) and _is_ancestor(
            repo, task_head, "refs/heads/develop", runner=runner,
        )
        remote_contains = _is_ancestor(repo, task_head, plan.base.ref, runner=runner)
        merged = local_contains and remote_contains
        merge_state = "PASS" if merged else "FAIL"
        phase = "closed" if merged else "orphaned-task-state"

    state = _state(
        {
            "branch": branch,
            "worktree": worktree,
            "base_sha": remote_develop,
            "dirty": dirty,
            "changed_paths": sorted(changed_paths),
            "pr_number": None,
            "pr_head_sha": None,
            "ci_state": "NOT_RUN",
            "review_state": "NOT_RUN",
            "merge_state": merge_state,
            "cleanup_safe": cleanup_safe,
        },
        local_facts={
            "phase": phase,
            "task_head": task_head,
            "local_develop_sha": local_develop,
            "remote_develop_sha": remote_develop,
            "local_task_head": local_task_head,
            "remote_task_head": remote_task_head,
            "worktree_registered": worktree_registered,
            "content_digest": content_digest,
        },
    )
    return ObservedExecution(
        state=state,
        phase=phase,
        base_matches_plan=remote_develop == plan.base.expected_sha,
        task_head=task_head,
        local_develop_sha=local_develop,
        remote_develop_sha=remote_develop,
        local_branch_exists=local_task_head is not None,
        remote_branch_exists=remote_task_head is not None,
        worktree_registered=worktree_registered,
    )
