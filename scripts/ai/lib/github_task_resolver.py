"""Resolve and bootstrap GitHub Issue-first workstation tasks."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse

from task_meta import TaskMetaError, parse_task_file, resolve_task_file
from task_runtime import update_task_runtime


REPO_SLUG = "firehell/guiyi-quant-workstation"
REMOTE_NAME = "origin"
BLOCKED_STATUSES = {"CLOSED", "CANCELLED", "SKIPPED_NOT_APPLICABLE", "SKIPPED_WITH_REASON"}


class GitHubTaskError(ValueError):
    """Fail-closed GitHub task bootstrap error."""


@dataclass(frozen=True)
class IssueContext:
    number: int
    title: str
    body: str
    state: str
    url: str


@dataclass(frozen=True)
class ResolvedGitHubTask:
    task_id: str
    issue_number: int
    pr_number: int
    branch: str
    task_file: str
    local_task_file: str
    worktree: str
    status: str
    issue_url: str
    pr_ref: str
    dry_run: bool
    remote_status: str
    next_command: str


def parse_issue_input(raw: str) -> tuple[str, int | str]:
    value = raw.strip()
    if not value:
        raise GitHubTaskError("Issue input is required")
    if re.fullmatch(r"TASK-[A-Za-z0-9_-]+", value):
        return "task_id", value
    if re.fullmatch(r"#?[0-9]+", value):
        return "issue_number", int(value.lstrip("#"))
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 4 and parts[2] == "issues" and parts[3].isdigit():
            repo = f"{parts[0]}/{parts[1]}"
            if repo != REPO_SLUG:
                raise GitHubTaskError(f"Issue repository mismatch: expected={REPO_SLUG} actual={repo}")
            return "issue_number", int(parts[3])
    raise GitHubTaskError(f"Unsupported issue input: {raw}")


def gh_issue_view(issue_number: int, *, repo: str = REPO_SLUG) -> IssueContext:
    cmd = [
        "gh",
        "issue",
        "view",
        str(issue_number),
        "--repo",
        repo,
        "--json",
        "number,title,body,state,url",
    ]
    try:
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise GitHubTaskError("gh CLI not found. Install gh and run gh auth login.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise GitHubTaskError(f"Failed to read GitHub Issue #{issue_number}: {detail}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubTaskError(f"gh issue view returned invalid JSON for #{issue_number}: {exc}") from exc
    return IssueContext(
        number=int(data.get("number") or issue_number),
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
        state=str(data.get("state") or ""),
        url=str(data.get("url") or f"https://github.com/{repo}/issues/{issue_number}"),
    )


def gh_file_content(repo: str, path: str, branch: str) -> str:
    cmd = ["gh", "api", f"repos/{repo}/contents/{path}", "-F", f"ref={branch}"]
    try:
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise GitHubTaskError("gh CLI not found. Install gh and run gh auth login.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise GitHubTaskError(f"Failed to read TASK file from GitHub branch {branch}: {detail}") from exc
    try:
        data = json.loads(raw)
        encoded = str(data.get("content") or "")
        return base64.b64decode(encoded.encode("utf-8"), validate=False).decode("utf-8")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        raise GitHubTaskError(f"GitHub TASK content is invalid for {path}@{branch}: {exc}") from exc


def resolve_from_task_id(repo_root: Path, task_id: str) -> tuple[Path, int | None]:
    try:
        task_file = resolve_task_file(task_id, repo_root)
        meta = parse_task_file(task_file, repo_root=repo_root, include_runtime=False)
    except TaskMetaError as exc:
        raise GitHubTaskError(str(exc)) from exc
    issue_number = _parse_ref_number(meta.github_issue)
    return task_file, issue_number


def parse_issue_fields(issue: IssueContext) -> dict[str, str]:
    if issue.state.upper() != "OPEN":
        raise GitHubTaskError(f"Issue #{issue.number} is not open: state={issue.state}")
    table = _parse_markdown_table(issue.body)
    text = issue.body

    fields = {
        "task_id": _clean(table.get("Task ID") or _field_after_label(text, "Task ID")),
        "branch": _clean(table.get("Task branch") or table.get("Branch") or _field_after_label(text, "Task branch")),
        "task_file": _clean(table.get("TASK file path") or table.get("TASK path") or _field_after_label(text, "TASK file path")),
        "draft_pr": _clean(table.get("Draft PR") or _field_after_label(text, "Draft PR")),
        "status": _clean(table.get("Current status") or table.get("Status") or _field_after_label(text, "Current status")),
    }
    missing = [key for key in ("task_id", "branch", "task_file") if not fields[key]]
    if missing:
        raise GitHubTaskError(f"Issue #{issue.number} missing required field(s): {', '.join(missing)}")
    if not re.fullmatch(r"TASK-[A-Za-z0-9_-]+", fields["task_id"]):
        raise GitHubTaskError(f"Issue #{issue.number} has invalid Task ID: {fields['task_id']}")
    _validate_task_path(fields["task_file"])
    if fields["status"].upper() in BLOCKED_STATUSES:
        raise GitHubTaskError(f"Issue #{issue.number} task status is not executable: {fields['status']}")
    return fields


def resolve_task(
    issue_arg: str,
    *,
    repo_root: Path | str,
    dry_run: bool = True,
    offline: bool = False,
    worktree_root: Path | str | None = None,
    repo: str = REPO_SLUG,
    remote: str = REMOTE_NAME,
) -> ResolvedGitHubTask:
    if repo != REPO_SLUG:
        raise GitHubTaskError(f"Refuse to read unexpected repository: {repo}")
    root = Path(repo_root).resolve()
    kind, parsed = parse_issue_input(issue_arg)
    if offline:
        return resolve_offline_task(root, kind, parsed, worktree_root=worktree_root)

    issue: IssueContext | None = None
    if kind == "task_id":
        task_file, linked_issue = resolve_from_task_id(root, str(parsed))
        if not linked_issue:
            raise GitHubTaskError(f"TASK {parsed} does not link a GitHub Issue #N")
        issue = gh_issue_view(linked_issue, repo=repo)
    else:
        issue = gh_issue_view(int(parsed), repo=repo)

    fields = parse_issue_fields(issue)
    branch = fields["branch"]
    worktree = resolve_worktree_path(root, fields["task_id"], worktree_root)
    task_file = prepare_task_file_for_parse(root, fields, repo=repo, dry_run=dry_run, worktree=worktree, remote=remote)

    try:
        meta = parse_task_file(task_file, repo_root=root, include_runtime=False)
    except TaskMetaError as exc:
        raise GitHubTaskError(f"TASK schema/metadata invalid: {exc}") from exc

    pr_number = _parse_ref_number(fields.get("draft_pr", ""))
    _validate_consistency(issue, fields, meta)

    if not dry_run:
        runtime_payload = update_task_runtime(
            root,
            fields["task_id"],
            {
                "worktree": str(worktree),
                "local_branch": branch,
                "issue_number": issue.number,
                "pr_number": pr_number or 0,
                "updated_by": "script",
            },
        )
        mirror_task_runtime(worktree, fields["task_id"], runtime_payload)

    return ResolvedGitHubTask(
        task_id=fields["task_id"],
        issue_number=issue.number,
        pr_number=pr_number or 0,
        branch=branch,
        task_file=fields["task_file"],
        local_task_file=str(task_file) if not dry_run or task_file.is_file() else "",
        worktree=str(worktree),
        status=meta.status,
        issue_url=issue.url,
        pr_ref=f"#{pr_number}" if pr_number else "",
        dry_run=dry_run,
        remote_status="verified",
        next_command=f'cd "{worktree}" && scripts/ai/dispatch_task.sh {fields["task_id"]} plan --json',
    )


def resolve_offline_task(
    repo_root: Path,
    kind: str,
    parsed: int | str,
    *,
    worktree_root: Path | str | None = None,
) -> ResolvedGitHubTask:
    if kind == "task_id":
        task_id = str(parsed)
        runtime = _runtime_for_task(repo_root, task_id)
    else:
        runtime = _runtime_for_issue(repo_root, int(parsed))
        task_id = str(runtime.get("task_id") or "")
    if not task_id:
        raise GitHubTaskError("Offline Issue lookup failed: runtime overlay does not contain task_id")

    worktree_value = str(runtime.get("worktree") or "")
    worktree = Path(worktree_value).expanduser().resolve() if worktree_value else resolve_worktree_path(repo_root, task_id, worktree_root)
    task_file = _resolve_local_task_for_offline(repo_root, worktree, task_id)
    try:
        meta = parse_task_file(task_file, repo_root=repo_root, include_runtime=False)
    except TaskMetaError as exc:
        raise GitHubTaskError(f"Offline TASK schema/metadata invalid: {exc}") from exc

    issue_number = int(runtime.get("issue_number") or _parse_ref_number(meta.github_issue) or 0)
    if kind == "issue_number" and issue_number != int(parsed):
        raise GitHubTaskError(f"Offline Issue mismatch: requested=#{parsed} runtime=#{issue_number}")
    expected_issue = f"#{issue_number}" if issue_number else ""
    if expected_issue and meta.github_issue and meta.github_issue != expected_issue:
        raise GitHubTaskError(f"Offline TASK issue mismatch: runtime={expected_issue} task={meta.github_issue}")

    branch = str(runtime.get("local_branch") or meta.branch or "")
    if meta.branch and branch and meta.branch != branch:
        raise GitHubTaskError(f"Offline branch mismatch: runtime={branch} task={meta.branch}")
    if meta.status.upper() in BLOCKED_STATUSES:
        raise GitHubTaskError(f"Offline TASK status is not executable: {meta.status}")

    pr_number = int(runtime.get("pr_number") or _parse_ref_number(meta.github_pr) or 0)
    return ResolvedGitHubTask(
        task_id=task_id,
        issue_number=issue_number,
        pr_number=pr_number,
        branch=branch,
        task_file=_task_path_for_payload(task_file, worktree, repo_root),
        local_task_file=str(task_file),
        worktree=str(worktree),
        status=meta.status,
        issue_url=f"https://github.com/{REPO_SLUG}/issues/{issue_number}" if issue_number else "",
        pr_ref=f"#{pr_number}" if pr_number else "",
        dry_run=False,
        remote_status="unknown",
        next_command=f'cd "{worktree}" && scripts/ai/dispatch_task.sh {task_id} plan --json',
    )


def prepare_task_file_for_parse(
    repo_root: Path,
    fields: dict[str, str],
    *,
    repo: str,
    dry_run: bool,
    worktree: Path,
    remote: str,
) -> Path:
    if dry_run:
        local_task = (repo_root / fields["task_file"]).resolve()
        if local_task.is_file():
            return local_task
        content = gh_file_content(repo, fields["task_file"], fields["branch"])
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False)
        try:
            handle.write(content)
            return Path(handle.name)
        finally:
            handle.close()

    ensure_remote_branch(repo_root, fields["branch"], remote=remote)
    ensure_tracking_branch(repo_root, fields["branch"], remote=remote)
    ensure_worktree(repo_root, fields["branch"], worktree)
    task_file = (worktree / fields["task_file"]).resolve()
    if not task_file.is_file():
        raise GitHubTaskError(f"TASK file from Issue does not exist in worktree: {fields['task_file']}")
    return task_file


def _runtime_for_task(repo_root: Path, task_id: str) -> dict[str, Any]:
    path = repo_root / ".ai" / "task-runtime" / f"{task_id}.json"
    if not path.is_file():
        raise GitHubTaskError(f"Offline runtime overlay missing for TASK: {task_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GitHubTaskError(f"Offline runtime overlay invalid JSON: {path}") from exc
    if data.get("task_id") != task_id:
        raise GitHubTaskError(f"Offline runtime task_id mismatch: {path}")
    return data


def mirror_task_runtime(worktree: Path, task_id: str, payload: dict[str, Any]) -> None:
    target = worktree.resolve() / ".ai" / "task-runtime" / f"{task_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def _runtime_for_issue(repo_root: Path, issue_number: int) -> dict[str, Any]:
    runtime_dir = repo_root / ".ai" / "task-runtime"
    if not runtime_dir.is_dir():
        raise GitHubTaskError(f"Offline runtime overlay directory missing: {runtime_dir}")
    matches: list[dict[str, Any]] = []
    for path in sorted(runtime_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GitHubTaskError(f"Offline runtime overlay invalid JSON: {path}") from exc
        if int(data.get("issue_number") or 0) == issue_number:
            matches.append(data)
    if not matches:
        raise GitHubTaskError(f"Offline runtime overlay not found for Issue #{issue_number}")
    if len(matches) > 1:
        raise GitHubTaskError(f"Offline runtime overlay ambiguous for Issue #{issue_number}")
    return matches[0]


def _resolve_local_task_for_offline(repo_root: Path, worktree: Path, task_id: str) -> Path:
    candidates = [worktree, repo_root]
    for root in candidates:
        try:
            return resolve_task_file(task_id, root)
        except TaskMetaError:
            continue
    raise GitHubTaskError(f"Offline TASK file not found for {task_id} in repo or worktree")


def _task_path_for_payload(task_file: Path, worktree: Path, repo_root: Path) -> str:
    for root in (worktree, repo_root):
        try:
            return task_file.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return str(task_file)


def ensure_remote_branch(repo_root: Path, branch: str, *, remote: str = REMOTE_NAME) -> None:
    _run_git(repo_root, ["fetch", remote, branch])
    remote_ref = f"refs/remotes/{remote}/{branch}"
    if not _git_ref_exists(repo_root, remote_ref):
        raise GitHubTaskError(f"Remote branch not found after fetch: {remote}/{branch}")


def ensure_tracking_branch(repo_root: Path, branch: str, *, remote: str = REMOTE_NAME) -> None:
    if _git_ref_exists(repo_root, f"refs/heads/{branch}"):
        return
    _run_git(repo_root, ["branch", "--track", branch, f"{remote}/{branch}"])


def ensure_worktree(repo_root: Path, branch: str, worktree: Path) -> None:
    if (worktree / ".git").exists() or (worktree / ".git").is_file():
        current = _git_output(worktree, ["branch", "--show-current"]).strip()
        if current != branch:
            raise GitHubTaskError(f"Worktree branch mismatch: worktree={worktree} current={current} expected={branch}")
        return
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _run_git(repo_root, ["worktree", "add", str(worktree), branch])


def resolve_worktree_path(repo_root: Path, task_id: str, worktree_root: Path | str | None = None) -> Path:
    root = Path(worktree_root).expanduser().resolve() if worktree_root else _default_worktree_root(repo_root)
    return root / task_slug_from_id(task_id)


def task_slug_from_id(task_id: str) -> str:
    slug = re.sub(r"^TASK-", "", task_id)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()
    return slug or task_id.lower()


def to_payload(resolved: ResolvedGitHubTask) -> dict[str, Any]:
    return asdict(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve and bootstrap a GitHub Issue-first TASK.")
    parser.add_argument("--issue", required=True, help="Issue number, #N, Issue URL, or TASK_ID")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--worktree-root")
    parser.add_argument("--remote", default=REMOTE_NAME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Resolve only from local runtime overlay; remote status is unknown.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        resolved = resolve_task(
            args.issue,
            repo_root=args.repo_root,
            dry_run=args.dry_run,
            offline=args.offline,
            worktree_root=args.worktree_root,
            remote=args.remote,
        )
    except GitHubTaskError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1

    payload = {"ok": True, **to_payload(resolved)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[OK] task={resolved.task_id} issue=#{resolved.issue_number} branch={resolved.branch}")
        print(f"Worktree: {resolved.worktree}")
        print(f"Next: {resolved.next_command}")
    return 0


def _parse_markdown_table(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if set(cells[0]) <= {"-", ":"} or cells[0].lower() in {"field", "字段"}:
            continue
        rows[cells[0]] = cells[1]
    return rows


def _field_after_label(text: str, label: str) -> str:
    pattern = re.compile(rf"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[:：]\s*(.+?)\s*$")
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _clean(value: str) -> str:
    value = str(value or "").strip()
    value = value.strip("`").strip()
    if value.lower() in {"", "-", "n/a", "none", "pending", "待创建", "待定"}:
        return ""
    return value


def _parse_ref_number(value: str) -> int | None:
    match = re.search(r"#([0-9]+)", value or "")
    if match:
        return int(match.group(1))
    if str(value).strip().isdigit():
        return int(str(value).strip())
    return None


def _validate_task_path(path: str) -> None:
    if path.startswith("/") or ".." in Path(path).parts:
        raise GitHubTaskError(f"TASK path must be repo-relative and safe: {path}")
    if not (path.startswith("docs/tasks/") or path.startswith(".ai/tasks/")):
        raise GitHubTaskError(f"TASK path must be under docs/tasks/ or .ai/tasks/: {path}")
    if not path.endswith(".md"):
        raise GitHubTaskError(f"TASK path must be a markdown file: {path}")


def _validate_consistency(issue: IssueContext, fields: dict[str, str], meta: Any) -> None:
    if meta.task_id != fields["task_id"]:
        raise GitHubTaskError(f"TASK ID mismatch: issue={fields['task_id']} task={meta.task_id}")
    if meta.branch and meta.branch != fields["branch"]:
        raise GitHubTaskError(f"Branch mismatch: issue={fields['branch']} task={meta.branch}")
    expected_issue = f"#{issue.number}"
    if meta.github_issue and meta.github_issue != expected_issue:
        raise GitHubTaskError(f"Issue mismatch: issue={expected_issue} task={meta.github_issue}")
    if meta.status.upper() in BLOCKED_STATUSES:
        raise GitHubTaskError(f"TASK status is not executable: {meta.status}")


def _default_worktree_root(repo_root: Path) -> Path:
    if os.environ.get("GUIYI_WORKTREE_ROOT"):
        return Path(os.environ["GUIYI_WORKTREE_ROOT"]).expanduser().resolve()
    return (repo_root.parent / "guiyi-parallel").resolve()


def _git_output(cwd: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise GitHubTaskError(f"git {' '.join(args)} failed: {detail}") from exc


def _run_git(cwd: Path, args: list[str]) -> None:
    _git_output(cwd, args)


def _git_ref_exists(repo_root: Path, ref: str) -> bool:
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=repo_root,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
