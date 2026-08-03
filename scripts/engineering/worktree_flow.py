#!/usr/bin/env python3
"""Fail-closed local worktree lifecycle helper.

This tool intentionally manages local Git state only.  It never pushes,
merges, changes GitHub settings, or touches the Runtime checkout.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/Volumes/扩展盘/GuiyiWorktrees")
PROTECTED_BRANCHES = {"main", "master", "develop"}
KIND_RE = re.compile(r"^(feature|fix|docs|research|refactor)$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class FlowError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        self.error_type = error_type
        super().__init__(message)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if check and result.returncode:
        message = (result.stderr or result.stdout or "git command failed").strip()
        raise FlowError("git_command_failed", message)
    return result


def repo_root(value: str | None) -> Path:
    candidate = Path(value).expanduser().resolve() if value else Path.cwd().resolve()
    result = git(candidate, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def require_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_absolute() or not root.is_dir():
        raise FlowError("worktree_root_unavailable", "worktree root must already exist")
    return root


def require_ref(repo: Path, ref: str) -> str:
    if not TOKEN_RE.fullmatch(ref.replace("/", "-")):
        raise FlowError("invalid_git_ref", "base and integration refs contain unsupported characters")
    result = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    if result.returncode:
        raise FlowError("base_ref_unavailable", f"required Git ref is unavailable: {ref}")
    return result.stdout.strip()


def clean(repo: Path) -> None:
    result = git(repo, "status", "--porcelain")
    if result.stdout.strip():
        raise FlowError("worktree_not_clean", "target worktree has uncommitted or untracked paths")


def safe_token(value: str, field: str) -> str:
    if not TOKEN_RE.fullmatch(value) or "/" in value:
        raise FlowError("invalid_identifier", f"{field} must be a simple identifier")
    return value


def task_identity(kind: str, task_id: str, slug: str) -> tuple[str, str]:
    if not KIND_RE.fullmatch(kind):
        raise FlowError("invalid_branch_kind", "kind must be feature, fix, docs, research, or refactor")
    return safe_token(task_id, "task id"), safe_token(slug, "slug")


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def report(
    action: str,
    mode: str,
    status: str,
    *,
    facts: dict[str, Any] | None = None,
    checks: list[dict[str, str]] | None = None,
    planned: list[list[str]] | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "scripts/engineering/worktree_flow.py",
        "action": action,
        "mode": mode,
        "status": status,
        "bound_facts": facts or {},
        "checks": checks or [],
        "planned_commands": planned or [],
        **({"error_type": error_type} if error_type else {}),
    }


def worktree_paths(repo: Path) -> list[Path]:
    output = git(repo, "worktree", "list", "--porcelain").stdout.splitlines()
    return [Path(line.removeprefix("worktree ")).resolve() for line in output if line.startswith("worktree ")]


def action_audit(repo: Path, root: Path, apply: bool) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for path in worktree_paths(repo):
        branch = git(path, "branch", "--show-current").stdout.strip() or "detached"
        head = git(path, "rev-parse", "HEAD").stdout.strip()
        entries.append({"path": str(path), "branch": branch, "head": head})
    return report("audit", "apply" if apply else "dry-run", "ok", facts={"repo": str(repo), "worktree_root": str(root), "worktrees": entries})


def action_init(repo: Path, root: Path, args: argparse.Namespace) -> dict[str, Any]:
    base_sha = require_ref(repo, args.base_ref)
    target = (root / "guiyi-develop").resolve()
    if target.exists():
        raise FlowError("develop_worktree_exists", "develop worktree destination already exists")
    if git(repo, "show-ref", "--verify", "--quiet", "refs/heads/develop", check=False).returncode == 0:
        raise FlowError("develop_branch_exists", "local develop branch already exists")
    if git(repo, "show-ref", "--verify", "--quiet", "refs/remotes/origin/develop", check=False).returncode == 0:
        raise FlowError("develop_branch_exists", "origin/develop already exists; attach it manually after audit")
    planned = [["git", "worktree", "add", "-b", "develop", str(target), args.base_ref]]
    if args.apply:
        clean(repo)
        git(repo, "worktree", "add", "-b", "develop", str(target), args.base_ref)
    return report(
        "init", "apply" if args.apply else "dry-run", "ok",
        facts={"repo": str(repo), "base_ref": args.base_ref, "base_sha": base_sha, "develop_path": str(target)},
        planned=planned,
    )


def action_task_create(repo: Path, root: Path, args: argparse.Namespace) -> dict[str, Any]:
    task_id, slug = task_identity(args.kind, args.task_id, args.slug)
    base_sha = require_ref(repo, args.base_ref)
    tasks_root = (root / "tasks").resolve()
    target = (tasks_root / f"{task_id}-{slug}").resolve()
    if not is_under(target, tasks_root):
        raise FlowError("invalid_task_path", "task worktree must be below the configured tasks root")
    if target.exists():
        raise FlowError("task_worktree_exists", "task worktree destination already exists")
    branch = f"{args.kind}/{task_id}-{slug}"
    if git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
        raise FlowError("task_branch_exists", "task branch already exists")
    planned = [["git", "worktree", "add", "-b", branch, str(target), args.base_ref]]
    if args.apply:
        tasks_root.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "-b", branch, str(target), args.base_ref)
    return report(
        "task-create", "apply" if args.apply else "dry-run", "ok",
        facts={
            "repo": str(repo), "base_ref": args.base_ref, "base_sha": base_sha,
            "task_branch": branch, "task_path": str(target), "integration_branch": args.integration_branch,
        },
        planned=planned,
    )


def action_task_cleanup(repo: Path, root: Path, args: argparse.Namespace) -> dict[str, Any]:
    tasks_root = (root / "tasks").resolve()
    path = Path(args.task_path).expanduser().resolve()
    if not path.is_dir() or not is_under(path, tasks_root):
        raise FlowError("invalid_task_path", "task path must be an existing managed task worktree")
    if path not in worktree_paths(repo):
        raise FlowError("unregistered_worktree", "task path is not registered in this repository")
    branch = git(path, "branch", "--show-current").stdout.strip()
    if not branch or branch in PROTECTED_BRANCHES:
        raise FlowError("protected_or_detached_branch", "only a non-protected task branch may be cleaned")
    if not KIND_RE.fullmatch(branch.split("/", 1)[0]):
        raise FlowError("invalid_task_branch", "managed task branch has an unsupported prefix")
    clean(path)
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    integration_sha = require_ref(repo, args.integration_branch)
    if git(repo, "merge-base", "--is-ancestor", head, args.integration_branch, check=False).returncode:
        raise FlowError("task_not_integrated", "task HEAD is not reachable from the integration branch")
    planned = [["git", "worktree", "remove", str(path)], ["git", "branch", "-d", branch]]
    if args.apply:
        git(repo, "worktree", "remove", str(path))
        git(repo, "branch", "-d", branch)
    return report(
        "task-cleanup", "apply" if args.apply else "dry-run", "ok",
        facts={"repo": str(repo), "task_path": str(path), "task_branch": branch, "task_head": head, "integration_branch": args.integration_branch, "integration_sha": integration_sha},
        planned=planned,
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("audit", "init", "task-create", "task-cleanup"))
    p.add_argument("--repo", help="Git repository root; defaults to the current repository")
    p.add_argument("--worktree-root", default=str(DEFAULT_ROOT))
    p.add_argument("--apply", action="store_true", help="perform the validated local Git action")
    p.add_argument("--json", action="store_true", help="emit one JSON result")
    p.add_argument("--base-ref", default="origin/develop")
    p.add_argument("--integration-branch", default="develop")
    p.add_argument("--kind")
    p.add_argument("--task-id")
    p.add_argument("--slug")
    p.add_argument("--task-path")
    return p


def main() -> int:
    args = parser().parse_args()
    mode = "apply" if args.apply else "dry-run"
    try:
        repo = repo_root(args.repo)
        root = require_root(args.worktree_root)
        if args.action == "audit":
            payload = action_audit(repo, root, args.apply)
        elif args.action == "init":
            payload = action_init(repo, root, args)
        elif args.action == "task-create":
            if not all((args.kind, args.task_id, args.slug)):
                raise FlowError("missing_task_identity", "task-create requires --kind, --task-id, and --slug")
            payload = action_task_create(repo, root, args)
        else:
            if not args.task_path:
                raise FlowError("missing_task_path", "task-cleanup requires --task-path")
            payload = action_task_cleanup(repo, root, args)
    except FlowError as exc:
        payload = report(args.action, mode, "blocked", error_type=exc.error_type, checks=[{"name": "validation", "status": "failed", "detail": str(exc)}])
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"[{payload['status'].upper()}] action={payload['action']} mode={payload['mode']}")
        for check in payload["checks"]:
            print(f"[{check['status'].upper()}] {check['name']}: {check['detail']}")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
