"""Deterministic task routing for the local AI workstation dispatcher."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from task_meta import TaskMetaError, parse_task_file, resolve_task_file, to_repo_relative


STAGES = {"route", "plan", "dev", "fix", "test", "review", "result"}
SANDBOX_RANK = {"none": 0, "read-only": 1, "workspace-write": 2}


@dataclass(frozen=True)
class Profile:
    name: str
    rank: int
    sandbox: str
    calls_model: bool


PROFILES = {
    "no-model": Profile("no-model", 0, "none", False),
    "plan-readonly": Profile("plan-readonly", 10, "read-only", True),
    "review-readonly": Profile("review-readonly", 10, "read-only", True),
    "dev-workspace-write": Profile("dev-workspace-write", 20, "workspace-write", True),
    "high-readonly": Profile("high-readonly", 30, "read-only", True),
    "high-workspace-write": Profile("high-workspace-write", 40, "workspace-write", True),
}

PROFILE_ALIASES = {
    "none": "no-model",
    "no_model": "no-model",
    "readonly": "plan-readonly",
    "read-only": "plan-readonly",
    "workspace-write": "dev-workspace-write",
    "workspace_write": "dev-workspace-write",
}

BASE_PROFILE_BY_STAGE = {
    "route": "no-model",
    "plan": "plan-readonly",
    "dev": "dev-workspace-write",
    "fix": "dev-workspace-write",
    "test": "no-model",
    "review": "review-readonly",
    "result": "no-model",
}

COMMAND_BY_STAGE = {
    "plan": ["scripts/ai/codex_plan.sh", "--task"],
    "dev": ["scripts/ai/codex_dev.sh", "--task"],
    "fix": ["scripts/ai/codex_dev.sh", "--task"],
    "test": ["scripts/ai/run_tests.sh", "--task"],
    "result": ["scripts/ai/collect_result.sh", "--task"],
}


class RouteError(ValueError):
    """Raised when a route cannot be safely resolved."""


def resolve_route(
    task_id_or_file: str,
    stage: str,
    *,
    repo_root: Path | str | None = None,
    requested_profile: str | None = None,
    explain: bool = False,
) -> dict[str, object]:
    root = Path(repo_root or Path.cwd()).resolve()
    stage = stage.lower()
    if stage not in STAGES:
        raise RouteError(f"Unsupported stage: {stage}")

    task_file = resolve_task_file(task_id_or_file, root)
    meta = parse_task_file(task_file)
    base_profile = PROFILES[BASE_PROFILE_BY_STAGE[stage]]
    resolved_profile, override_reason = _resolve_profile(stage, base_profile, requested_profile)
    command = _stage_command(stage, meta.task_id)

    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "task_id": meta.task_id,
        "task_file": to_repo_relative(meta.path, root),
        "stage": stage,
        "status": meta.status,
        "work_level": meta.work_level,
        "github_issue": meta.github_issue,
        "branch": meta.branch,
        "worktree": meta.worktree,
        "allowed_paths": list(meta.allowed_paths),
        "forbidden_paths": list(meta.forbidden_paths),
        "required_tests": list(meta.required_tests),
        "base_profile": base_profile.name,
        "resolved_profile": resolved_profile.name,
        "override_reason": override_reason,
        "sandbox": resolved_profile.sandbox,
        "calls_model": resolved_profile.calls_model,
        "approval_required": stage in {"dev", "fix"},
        "write_lock_required": stage in {"dev", "fix"},
        "command": command,
    }
    if explain:
        payload["explanation"] = _explain(stage, resolved_profile)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve a deterministic route for a TASK stage.")
    parser.add_argument("task")
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--profile")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args(argv)

    try:
        route = resolve_route(
            args.task,
            args.stage,
            repo_root=args.repo_root,
            requested_profile=args.profile,
            explain=args.explain,
        )
    except (RouteError, TaskMetaError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(route, ensure_ascii=False, indent=2 if args.json else None))
    return 0


def _resolve_profile(stage: str, base: Profile, requested: str | None) -> tuple[Profile, str]:
    if not requested:
        return base, ""
    profile = _profile_from_name(requested)
    if base.name == "no-model":
        if profile.name != "no-model":
            raise RouteError(f"{stage} stage must not call a model; requested profile={requested}")
        return profile, ""
    if profile.rank < base.rank:
        raise RouteError(f"profile downgrade is not allowed: requested={profile.name} base={base.name}")
    if SANDBOX_RANK[profile.sandbox] < SANDBOX_RANK[base.sandbox]:
        raise RouteError(f"profile sandbox downgrade is not allowed: requested={profile.sandbox} base={base.sandbox}")
    if profile.name == base.name:
        return profile, ""
    return profile, f"requested_profile_upgrade:{profile.name}"


def _profile_from_name(name: str) -> Profile:
    key = PROFILE_ALIASES.get(name, name)
    try:
        return PROFILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(PROFILES | PROFILE_ALIASES))
        raise RouteError(f"unknown profile: {name}; known profiles: {known}") from exc


def _stage_command(stage: str, task_id: str) -> list[str]:
    if stage == "route":
        return []
    if stage == "review":
        return ["scripts/ai/codex_review.sh", "--task", task_id]
    base = COMMAND_BY_STAGE[stage]
    return [base[0], base[1], task_id]


def _explain(stage: str, profile: Profile) -> str:
    if not profile.calls_model:
        return f"{stage} is deterministic and does not call a model."
    return f"{stage} uses {profile.sandbox} sandbox via profile {profile.name}."


if __name__ == "__main__":
    raise SystemExit(main())
