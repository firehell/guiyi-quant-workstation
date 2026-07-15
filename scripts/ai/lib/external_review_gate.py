#!/usr/bin/env python3
"""GPT external PR review gate bound to GitHub PR head SHA."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from task_meta import TaskMetaError, parse_task_file, resolve_task_file


REPO_SLUG = "firehell/guiyi-quant-workstation"
REVIEW_DIR = Path(".ai") / "external-reviews"
BLOCKING_RE = re.compile(r"(?i)(request_changes|changes requested|blocking|blocker|P0|P1|阻断|必须修复|高优先级)")


class ExternalReviewError(ValueError):
    """Fail-closed external review gate error."""


@dataclass(frozen=True)
class ReviewContext:
    repo_root: Path
    task_id: str
    risk_level: str
    approval_scope: tuple[str, ...]
    pr_number: int
    required: bool
    user_approval_required: bool


def review_record_path(repo_root: Path | str, task_id: str) -> Path:
    return Path(repo_root).resolve() / REVIEW_DIR / f"{task_id}.json"


def build_context(
    repo_root: Path | str,
    task_id: str,
    *,
    task_file: str | None = None,
    pr_number: int | None = None,
) -> ReviewContext:
    root = Path(repo_root).resolve()
    try:
        path = Path(task_file).resolve() if task_file else resolve_task_file(task_id, root)
        meta = parse_task_file(path, repo_root=root)
    except TaskMetaError as exc:
        raise ExternalReviewError(str(exc)) from exc

    pr = pr_number or _parse_ref_number(meta.github_pr)
    if not pr:
        raise ExternalReviewError(f"TASK {meta.task_id} does not link a GitHub PR #N")
    risk = (meta.risk_level or "R3").upper()
    scope = tuple(meta.approval_scope or ())
    required = risk in {"R0", "R1"} or "external_review" in scope
    return ReviewContext(
        repo_root=root,
        task_id=meta.task_id,
        risk_level=risk,
        approval_scope=scope,
        pr_number=pr,
        required=required,
        user_approval_required=risk == "R0",
    )


def evaluate_external_review(
    ctx: ReviewContext,
    *,
    reviewer_type: str = "gpt",
    review_author: str = "",
    repo: str = REPO_SLUG,
) -> dict[str, Any]:
    pr = gh_pr_view(ctx.pr_number, repo=repo)
    head_sha = str(pr.get("headRefOid") or "")
    if not head_sha:
        raise ExternalReviewError(f"PR #{ctx.pr_number} missing headRefOid")

    previous = load_record(ctx.repo_root, ctx.task_id)
    reviews = gh_pr_reviews(ctx.pr_number, repo=repo)
    candidates = [
        normalize_review(item)
        for item in reviews
        if not review_author or str((item.get("user") or {}).get("login") or item.get("author", {}).get("login") or "") == review_author
    ]
    candidates = [item for item in candidates if item["action"] in {"APPROVE", "COMMENT", "REQUEST_CHANGES"}]
    candidates.sort(key=lambda item: item.get("review_timestamp") or "")

    current = [item for item in candidates if item.get("head_sha") == head_sha]
    latest = current[-1] if current else None
    stale_reviews = [item for item in candidates if item.get("head_sha") and item.get("head_sha") != head_sha]

    stale = False
    gate_status = "not_required" if not ctx.required else "missing"
    blocking_findings: list[str] = []
    review_action = ""
    review_timestamp = ""
    reviewer_login = ""

    if latest:
        review_action = latest["action"]
        review_timestamp = latest.get("review_timestamp", "")
        reviewer_login = latest.get("reviewer_login", "")
        blocking_findings = latest.get("blocking_findings", [])
        gate_status = "blocked" if blocking_findings else "passed"
    elif stale_reviews or (previous and previous.get("head_sha") and previous.get("head_sha") != head_sha):
        stale = True
        gate_status = "stale" if ctx.required else "not_required"

    if ctx.required and gate_status == "not_required":
        gate_status = "missing"

    return {
        "schema_version": 1,
        "task_id": ctx.task_id,
        "pr_number": ctx.pr_number,
        "pr_url": pr.get("url", f"https://github.com/{repo}/pull/{ctx.pr_number}"),
        "head_sha": head_sha,
        "review_action": review_action,
        "review_timestamp": review_timestamp,
        "reviewer_type": reviewer_type,
        "reviewer_login": reviewer_login,
        "review_author_filter": review_author,
        "blocking_findings": blocking_findings,
        "risk_level": ctx.risk_level,
        "approval_scope": list(ctx.approval_scope),
        "required": ctx.required,
        "user_approval_required": ctx.user_approval_required,
        "stale": stale,
        "gate_status": gate_status,
        "synced_at": utc_now(),
        "source": "github_pr_reviews",
    }


def normalize_review(item: dict[str, Any]) -> dict[str, Any]:
    state = str(item.get("state") or "").upper()
    action = {
        "APPROVED": "APPROVE",
        "COMMENTED": "COMMENT",
        "COMMENT": "COMMENT",
        "CHANGES_REQUESTED": "REQUEST_CHANGES",
        "REQUEST_CHANGES": "REQUEST_CHANGES",
    }.get(state, state)
    body = str(item.get("body") or "")
    blocking = []
    if action == "REQUEST_CHANGES":
        blocking.append("review_action=REQUEST_CHANGES")
    if BLOCKING_RE.search(body):
        blocking.append("review_body_contains_blocking_terms")
    user = item.get("user") or item.get("author") or {}
    return {
        "action": action,
        "review_timestamp": str(item.get("submitted_at") or item.get("submittedAt") or ""),
        "reviewer_login": str(user.get("login") or ""),
        "head_sha": str(item.get("commit_id") or item.get("commitID") or item.get("commitOid") or item.get("head_sha") or ""),
        "blocking_findings": sorted(set(blocking)),
    }


def save_record(repo_root: Path, task_id: str, payload: dict[str, Any]) -> Path:
    path = review_record_path(repo_root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_record(repo_root: Path, task_id: str) -> dict[str, Any]:
    path = review_record_path(repo_root, task_id)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalReviewError(f"External review record invalid JSON: {path}") from exc


def gh_pr_view(pr_number: int, *, repo: str = REPO_SLUG) -> dict[str, Any]:
    raw = _gh(["pr", "view", str(pr_number), "--repo", repo, "--json", "number,url,headRefOid"], capture=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExternalReviewError(f"gh pr view returned invalid JSON: {exc}") from exc


def gh_pr_reviews(pr_number: int, *, repo: str = REPO_SLUG) -> list[dict[str, Any]]:
    raw = _gh(["api", f"repos/{repo}/pulls/{pr_number}/reviews", "--paginate"], capture=True)
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ExternalReviewError(f"gh PR reviews returned invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ExternalReviewError("gh PR reviews payload must be a JSON list")
    return data


def _gh(args: list[str], *, capture: bool = False) -> str:
    try:
        result = subprocess.run(["gh", *args], text=True, capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise ExternalReviewError("gh CLI not found. Install gh and run gh auth login.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ExternalReviewError(f"gh {' '.join(args)} failed: {detail}") from exc
    return result.stdout if capture else ""


def _parse_ref_number(value: str) -> int:
    match = re.search(r"#([0-9]+)", value or "")
    if match:
        return int(match.group(1))
    if str(value).strip().isdigit():
        return int(str(value).strip())
    return 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def should_block(payload: dict[str, Any]) -> bool:
    return payload.get("required") is True and payload.get("gate_status") in {"missing", "stale", "blocked"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record and verify GPT external PR review gate.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--task-file")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--reviewer-type", default="gpt")
    parser.add_argument("--review-author", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        ctx = build_context(args.repo_root, args.task, task_file=args.task_file, pr_number=args.pr)
        payload = evaluate_external_review(ctx, reviewer_type=args.reviewer_type, review_author=args.review_author)
        record_path = review_record_path(ctx.repo_root, ctx.task_id)
        if not args.dry_run:
            record_path = save_record(ctx.repo_root, ctx.task_id, payload)
        payload["record_path"] = str(record_path)
        payload["dry_run"] = args.dry_run
    except ExternalReviewError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1

    ok = not should_block(payload)
    payload = {"ok": ok, **payload}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif ok:
        print(f"[OK] external review gate: task={payload['task_id']} status={payload['gate_status']}")
    else:
        print(f"External review gate failed: status={payload['gate_status']} task={payload['task_id']}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
