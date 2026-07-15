#!/usr/bin/env python3
"""Sync safe Result summaries back to GitHub Issue and Draft PR."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from result_bundler import RedactionPatterns, redact
from task_meta import TaskMetaError, parse_task_file, resolve_task_file


REPO_SLUG = "firehell/guiyi-quant-workstation"
ISSUE_MARKER = "<!-- guiyi-result-sync:issue:{task_id}:{mode} -->"
PR_BLOCK_START = "<!-- guiyi-result-sync:pr-summary:start -->"
PR_BLOCK_END = "<!-- guiyi-result-sync:pr-summary:end -->"
MAX_LIST_ITEMS = 12
MAX_TEXT_CHARS = 1200


class ResultSyncError(ValueError):
    """Fail-closed result sync error."""


@dataclass(frozen=True)
class SyncContext:
    repo_root: Path
    task_id: str
    task_file: Path
    result_dir: Path
    bundle_path: Path
    bundle: dict[str, Any]
    issue_number: int
    pr_number: int


def build_context(
    repo_root: Path | str,
    task_id: str,
    *,
    task_file: Path | str | None = None,
    bundle: Path | str | None = None,
) -> SyncContext:
    root = Path(repo_root).resolve()
    try:
        resolved_task = Path(task_file).resolve() if task_file else resolve_task_file(task_id, root)
        meta = parse_task_file(resolved_task, repo_root=root)
    except TaskMetaError as exc:
        raise ResultSyncError(str(exc)) from exc

    result_dir = root / ".ai" / "results" / meta.task_id
    bundle_path = Path(bundle).resolve() if bundle else result_dir / "result_bundle.json"
    if not bundle_path.is_file():
        raise ResultSyncError(f"Result bundle not found: {bundle_path}")
    try:
        bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResultSyncError(f"Result bundle invalid JSON: {bundle_path}: {exc}") from exc

    issue_number = _parse_ref_number(str(meta.github_issue or bundle_data.get("github_issue", "")))
    pr_number = _parse_ref_number(str(meta.github_pr or bundle_data.get("github_pr", "")))
    return SyncContext(
        repo_root=root,
        task_id=meta.task_id,
        task_file=resolved_task,
        result_dir=result_dir,
        bundle_path=bundle_path,
        bundle=redact(bundle_data),
        issue_number=issue_number,
        pr_number=pr_number,
    )


def render_issue_comment(ctx: SyncContext, mode: str) -> str:
    if mode not in {"plan", "test", "review", "result", "delivery"}:
        raise ResultSyncError(f"Unsupported result sync mode: {mode}")
    bundle = ctx.bundle
    marker = ISSUE_MARKER.format(task_id=ctx.task_id, mode=mode)
    lines = [
        marker,
        f"## {mode.title()} 回流摘要 - {ctx.task_id}",
        "",
        f"- Task status: `{_value(bundle.get('task_status'))}`",
        f"- Execution status: `{_value(bundle.get('execution_status'))}`",
        f"- Current stage: `{mode}`",
        f"- Result path: `.ai/results/{ctx.task_id}/`",
        f"- Result bundle: `.ai/results/{ctx.task_id}/result_bundle.json`",
        "",
        "### Gate 状态",
        f"- Scope: `{_value(bundle.get('scope_check'))}`",
        f"- Forbidden paths: `{_value(bundle.get('forbidden_path_check'))}`",
        f"- Sensitive data: `{_value(bundle.get('sensitive_data_check'))}`",
        f"- Issue gate: `{_value(bundle.get('issue_gate'))}`",
        f"- Review: `{_value(bundle.get('review_status'))}`",
        f"- External review required: `{str(bool(bundle.get('external_review_required'))).lower()}`",
        "",
    ]

    if mode == "plan":
        lines.extend(["### Plan 摘要", *_file_excerpt(ctx.result_dir / "plan_result.md")])
    elif mode == "test":
        lines.extend(["### 测试摘要", *_test_lines(bundle)])
    elif mode == "review":
        lines.extend([
            "### Review 摘要",
            f"- Review status: `{_value(bundle.get('review_status'))}`",
            f"- External review required: `{str(bool(bundle.get('external_review_required'))).lower()}`",
            *_file_excerpt(ctx.result_dir / "review.md"),
        ])
    else:
        lines.extend(["### Delivery 摘要", *_delivery_lines(ctx)])

    blockers = list(bundle.get("warnings", []) or []) + list(bundle.get("incomplete_items", []) or [])
    lines.extend(["", "### 阻塞 / 未完成", *_bullets(blockers, empty="无")])
    lines.extend(["", "### 说明", "- 本评论由本地 result bundle 生成，只包含脱敏摘要；完整日志、数据样本和凭据不会上传。"])
    return assert_safe(render_text("\n".join(lines), ctx.repo_root))


def render_delivery_summary(ctx: SyncContext) -> str:
    bundle = ctx.bundle
    lines = [
        f"# 交付摘要 - {ctx.task_id}",
        "",
        "## 摘要",
        f"- 当前状态: {_value(bundle.get('task_status'))}",
        f"- 执行状态: {_value(bundle.get('execution_status'))}",
        f"- 工作级别: {_value(bundle.get('work_level'))}",
        f"- Issue Gate: {_value(bundle.get('issue_gate'))}",
        f"- Review: {_value(bundle.get('review_status'))}",
        f"- External Review Required: {str(bool(bundle.get('external_review_required'))).lower()}",
        f"- Evidence: `.ai/results/{ctx.task_id}/`",
        "",
        "## 变更文件",
        *_bullets(bundle.get("changed_files", []), code=True, empty="无"),
        "",
        "## 测试",
        *_test_lines(bundle),
        "",
        "## Gate",
        f"- Scope: `{_value(bundle.get('scope_check'))}`",
        f"- Forbidden paths: `{_value(bundle.get('forbidden_path_check'))}`",
        f"- Sensitive data: `{_value(bundle.get('sensitive_data_check'))}`",
        "",
        "## 风险与未完成",
        *_bullets((bundle.get("warnings", []) or []) + (bundle.get("incomplete_items", []) or []), empty="无"),
        "",
        "## 下一步",
        f"- {_value(bundle.get('next_action'))}",
    ]
    return assert_safe(render_text("\n".join(lines), ctx.repo_root))


def render_pr_summary_block(ctx: SyncContext) -> str:
    bundle = ctx.bundle
    evidence = bundle.get("evidence_index", {}) if isinstance(bundle.get("evidence_index"), dict) else {}
    lines = [
        PR_BLOCK_START,
        "## Result Sync Summary",
        "",
        f"- Task ID: `{ctx.task_id}`",
        f"- TASK path: `{_repo_relative(ctx.task_file, ctx.repo_root)}`",
        f"- Result path: `.ai/results/{ctx.task_id}/`",
        f"- Status: `{_value(bundle.get('execution_status'))}`",
        f"- Risk / work level: `{_value(bundle.get('risk_level') or bundle.get('work_level'))}` / `{_value(bundle.get('work_level'))}`",
        f"- Scope gate: `{_value(bundle.get('scope_check'))}`",
        f"- Sensitive data gate: `{_value(bundle.get('sensitive_data_check'))}`",
        f"- Review: `{_value(bundle.get('review_status'))}`",
        f"- External review required: `{str(bool(bundle.get('external_review_required'))).lower()}`",
        "",
        "### Changed Files",
        *_bullets(bundle.get("changed_files", []), code=True, empty="None"),
        "",
        "### Diff Stat",
        *_code_block(_trim_text(str(bundle.get("git_diff_stat", "") or "None"))),
        "",
        "### Tests",
        *_test_lines(bundle),
        "",
        "### Evidence",
        f"- Evidence files indexed: `{evidence.get('total_files', 0)}`",
        f"- Local-only evidence path: `.ai/results/{ctx.task_id}/`",
        "",
        "### Unresolved Items",
        *_bullets((bundle.get("warnings", []) or []) + (bundle.get("incomplete_items", []) or []), empty="None"),
        PR_BLOCK_END,
    ]
    return assert_safe(render_text("\n".join(lines), ctx.repo_root))


def merge_pr_body(existing_body: str, block: str) -> str:
    pattern = re.compile(
        rf"{re.escape(PR_BLOCK_START)}.*?{re.escape(PR_BLOCK_END)}",
        re.DOTALL,
    )
    if pattern.search(existing_body):
        return pattern.sub(block, existing_body, count=1)
    body = existing_body.rstrip()
    return f"{body}\n\n{block}\n" if body else f"{block}\n"


def sync_issue_comment(ctx: SyncContext, mode: str, *, dry_run: bool, apply: bool) -> dict[str, Any]:
    if not ctx.issue_number:
        raise ResultSyncError("TASK does not link a GitHub Issue #N")
    body = render_issue_comment(ctx, mode)
    marker = ISSUE_MARKER.format(task_id=ctx.task_id, mode=mode)
    result = {
        "target": "issue",
        "task_id": ctx.task_id,
        "issue_number": ctx.issue_number,
        "mode": mode,
        "marker": marker,
        "body": body,
        "dry_run": dry_run,
        "action": "dry_run",
    }
    if dry_run:
        return result
    if not apply:
        raise ResultSyncError("Issue operation blocked: pass --confirm-issue-ops to execute external writes")
    _require_gh()
    existing = _find_issue_comment(ctx.issue_number, marker)
    if existing:
        _gh_api(["-X", "PATCH", f"repos/{REPO_SLUG}/issues/comments/{existing['id']}", "-f", f"body={body}"])
        result["action"] = "update"
        result["comment_id"] = existing["id"]
    else:
        _gh(["issue", "comment", str(ctx.issue_number), "--repo", REPO_SLUG, "--body-file", _temp_body(body)])
        result["action"] = "create"
    result.pop("body", None)
    return result


def sync_pr_body(ctx: SyncContext, *, dry_run: bool, apply: bool, pr_number: int | None = None) -> dict[str, Any]:
    pr = pr_number or ctx.pr_number
    if not pr:
        raise ResultSyncError("TASK does not link a Draft PR #N")
    block = render_pr_summary_block(ctx)
    existing_body = ""
    if dry_run:
        updated_body = merge_pr_body(existing_body, block)
    else:
        if not apply:
            raise ResultSyncError("PR operation blocked: pass --confirm-issue-ops to execute external writes")
        _require_gh()
        view = json.loads(_gh(["pr", "view", str(pr), "--repo", REPO_SLUG, "--json", "body"], capture=True))
        existing_body = str(view.get("body") or "")
        updated_body = merge_pr_body(existing_body, block)
        body_file = _temp_body(updated_body)
        _gh(["pr", "edit", str(pr), "--repo", REPO_SLUG, "--body-file", body_file])
    return {
        "target": "pr",
        "task_id": ctx.task_id,
        "pr_number": pr,
        "dry_run": dry_run,
        "action": "dry_run" if dry_run else "update",
        "body": updated_body if dry_run else "",
    }


def _find_issue_comment(issue_number: int, marker: str) -> dict[str, Any] | None:
    raw = _gh_api([f"repos/{REPO_SLUG}/issues/{issue_number}/comments", "--paginate"], capture=True)
    try:
        comments = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ResultSyncError(f"gh returned invalid issue comments JSON: {exc}") from exc
    for comment in comments:
        if marker in str(comment.get("body") or ""):
            return comment
    return None


def _file_excerpt(path: Path) -> list[str]:
    if not path.is_file():
        return ["- 未记录"]
    text = _trim_text(path.read_text(encoding="utf-8", errors="replace"))
    return _code_block(text)


def _delivery_lines(ctx: SyncContext) -> list[str]:
    summary = ctx.result_dir / "delivery_summary.md"
    if summary.is_file():
        return _code_block(_trim_text(summary.read_text(encoding="utf-8", errors="replace")))
    bundle = ctx.bundle
    return [
        f"- Next action: {_value(bundle.get('next_action'))}",
        f"- Manual review required: `{str(bool(bundle.get('manual_review_required'))).lower()}`",
    ]


def _test_lines(bundle: dict[str, Any]) -> list[str]:
    results = bundle.get("test_results", []) or []
    if not results:
        return ["- 未记录测试"]
    lines = []
    for item in results[:MAX_LIST_ITEMS]:
        if isinstance(item, dict):
            lines.append(f"- `{item.get('status', '?')}` rc={item.get('exit_code', '?')}: `{item.get('command', '')}`")
        else:
            lines.append(f"- `{item}`")
    if len(results) > MAX_LIST_ITEMS:
        lines.append(f"- ... plus {len(results) - MAX_LIST_ITEMS} more")
    return lines


def _bullets(values: Any, *, code: bool = False, empty: str = "None") -> list[str]:
    if not values:
        return [f"- {empty}"]
    if isinstance(values, str):
        values = [values]
    lines = []
    for value in list(values)[:MAX_LIST_ITEMS]:
        text = _trim_text(str(value), limit=240)
        lines.append(f"- `{text}`" if code else f"- {text}")
    if len(values) > MAX_LIST_ITEMS:
        lines.append(f"- ... plus {len(values) - MAX_LIST_ITEMS} more")
    return lines


def _code_block(text: str) -> list[str]:
    return ["```text", text or "None", "```"]


def _trim_text(text: str, *, limit: int = MAX_TEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def render_text(text: str, repo_root: Path) -> str:
    redacted = RedactionPatterns.redact_text(text)
    return _sanitize_local_paths(redacted, repo_root)


def assert_safe(text: str) -> str:
    hits = RedactionPatterns.check_sensitive(text)
    if hits:
        raise ResultSyncError(f"Rendered GitHub summary still contains sensitive patterns: {', '.join(hits)}")
    if re.search(r"(?m)^```.*\n(?:.*\n){80,}```", text):
        raise ResultSyncError("Rendered GitHub summary is too large; refusing to upload full logs")
    return text


def _sanitize_local_paths(text: str, repo_root: Path) -> str:
    value = text.replace(str(repo_root), "<repo>")
    home = str(Path.home())
    if home and home != "/":
        value = value.replace(home, "<home>")
    value = re.sub(r"/Volumes/[^`\s)]+", "<volume-path>", value)
    return value


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _value(value: Any) -> str:
    if value in (None, ""):
        return "not_recorded"
    return _trim_text(str(value), limit=240)


def _parse_ref_number(value: str) -> int:
    match = re.search(r"#([0-9]+)", value or "")
    if match:
        return int(match.group(1))
    if str(value).strip().isdigit():
        return int(str(value).strip())
    return 0


def _require_gh() -> None:
    if not _which("gh"):
        raise ResultSyncError("gh CLI not found. Install gh and run gh auth login.")
    try:
        _gh(["auth", "status"], capture=True)
    except ResultSyncError as exc:
        raise ResultSyncError("gh is not authenticated. Run: gh auth login") from exc


def _which(name: str) -> bool:
    return any((Path(part) / name).exists() for part in os.environ.get("PATH", "").split(os.pathsep) if part)


def _gh(args: list[str], *, capture: bool = False) -> str:
    cmd = ["gh", *args]
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ResultSyncError(f"gh {' '.join(args)} failed: {detail}") from exc
    return result.stdout if capture else ""


def _gh_api(args: list[str], *, capture: bool = False) -> str:
    return _gh(["api", *args], capture=capture)


def _temp_body(body: str) -> str:
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md")
    try:
        tmp.write(body)
        return tmp.name
    finally:
        tmp.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync safe result summaries to GitHub Issue or Draft PR.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("issue", "pr", "delivery"):
        p = sub.add_parser(name)
        p.add_argument("--task", required=True)
        p.add_argument("--repo-root", default=".")
        p.add_argument("--task-file")
        p.add_argument("--bundle")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--confirm-issue-ops", action="store_true")
        p.add_argument("--json", action="store_true")
        if name == "issue":
            p.add_argument("--mode", required=True, choices=["plan", "test", "review", "result", "delivery"])
        if name == "pr":
            p.add_argument("--pr", type=int)
        if name == "delivery":
            p.add_argument("--output")

    args = parser.parse_args(argv)
    try:
        ctx = build_context(args.repo_root, args.task, task_file=args.task_file, bundle=args.bundle)
        if args.command == "issue":
            payload = sync_issue_comment(ctx, args.mode, dry_run=args.dry_run, apply=args.confirm_issue_ops)
        elif args.command == "pr":
            payload = sync_pr_body(ctx, dry_run=args.dry_run, apply=args.confirm_issue_ops, pr_number=args.pr)
        else:
            summary = render_delivery_summary(ctx)
            output = Path(args.output) if args.output else ctx.result_dir / "delivery_summary.md"
            if args.dry_run:
                payload = {"target": "delivery", "task_id": ctx.task_id, "dry_run": True, "body": summary}
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(summary + "\n", encoding="utf-8")
                payload = {"target": "delivery", "task_id": ctx.task_id, "output": str(output)}
    except ResultSyncError as exc:
        if "--json" in (argv or sys.argv[1:]):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    else:
        body = payload.get("body")
        if body:
            print(body)
        else:
            print(f"[OK] github result sync: target={payload.get('target')} task={payload.get('task_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
