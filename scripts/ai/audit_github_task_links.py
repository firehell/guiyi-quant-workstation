#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_SLUG = "firehell/guiyi-quant-workstation"
DEFAULT_OUTPUT_DIR = Path("outputs/workstation-github-migration")
DEFAULT_DOC_REPORT = Path("docs/workstation/GITHUB_TASK_MIGRATION_REPORT.md")

TASK_DIRS = (
    Path("docs/tasks"),
    Path("tasks"),
    Path(".ai/tasks"),
)

EXCLUDED_TASK_PARTS = {
    "templates",
    "done",
    "examples",
}

COMPLETED_STATUSES = {
    "CLOSED",
    "DONE",
    "COMPLETED",
    "DELIVERY_READY",
    "RESULT_READY",
    "DELIVERY_READY_DOC_SOURCE_CLOSURE",
}
SUPERSEDED_STATUSES = {
    "CANCELLED",
    "CANCELED",
    "SUPERSEDED",
    "NOT_PLANNED",
    "SKIPPED",
    "SKIPPED_NOT_APPLICABLE",
    "SKIPPED_WITH_REASON",
}
ACTIVE_STATUSES = {
    "REQUIREMENT_READY",
    "PLAN_READY",
    "APPROVED_DEV",
    "CODING",
    "TESTING",
    "REVIEWING",
    "REPLAN",
    "PAUSED",
    "BLOCKED",
}


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    path: str
    status: str
    github_issue: str
    github_pr: str
    branch: str
    worktree: str
    work_level: str
    source: str


@dataclass(frozen=True)
class PullRequestRecord:
    number: int
    title: str
    url: str
    state: str
    is_draft: bool
    head_ref: str
    head_sha: str
    updated_at: str
    task_id: str


@dataclass(frozen=True)
class MatrixRow:
    item_type: str
    issue: str
    issue_title: str
    task_id: str
    task_path: str
    branch: str
    pr: str
    pr_state: str
    status: str
    last_commit: str
    classification: str
    recommendation: str
    conflicts: str
    issue_url: str
    pr_url: str


def run(cmd: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError(f"command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{detail}") from exc


def load_json_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array: {path}")
    return [item for item in data if isinstance(item, dict)]


def load_open_issues(repo_root: Path, repo: str, issues_file: Path | None) -> list[dict[str, Any]]:
    if issues_file:
        return load_json_file(issues_file)
    raw = run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,title,body,state,labels,url,updatedAt,createdAt",
        ],
        cwd=repo_root,
    )
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError("gh issue list returned non-list JSON")
    return [item for item in data if isinstance(item, dict)]


def load_open_prs(repo_root: Path, repo: str, prs_file: Path | None) -> list[dict[str, Any]]:
    if prs_file:
        return load_json_file(prs_file)
    raw = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,title,body,state,isDraft,headRefName,headRefOid,url,updatedAt,createdAt",
        ],
        cwd=repo_root,
    )
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError("gh pr list returned non-list JSON")
    return [item for item in data if isinstance(item, dict)]


def scan_tasks(repo_root: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for task_dir in TASK_DIRS:
        root = repo_root / task_dir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(repo_root)
            if set(rel.parts) & EXCLUDED_TASK_PARTS:
                continue
            if path.name in {"README.md", "TASK_TEMPLATE.md", "TASK_TEMPLATE_L1.md"}:
                continue
            if "ACCEPTANCE" in path.name:
                continue
            if path.name.startswith("EXAMPLE") or "FIXTURE" in path.name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            task_id = first_nonempty(
                field_from_meta_table(text, "Task ID"),
                yaml_field(text, "task_id"),
                task_id_from_text(path.stem),
                task_id_from_text(text[:400]),
            )
            if not task_id:
                continue
            status = normalize_status(first_nonempty(field_from_meta_table(text, "Status"), yaml_field(text, "status"), quoted_status(text)))
            records.append(
                TaskRecord(
                    task_id=task_id,
                    path=str(rel),
                    status=status,
                    github_issue=clean_ref(first_nonempty(field_from_meta_table(text, "GitHub Issue"), yaml_field(text, "github_issue"))),
                    github_pr=clean_ref(first_nonempty(field_from_meta_table(text, "GitHub PR"), field_from_meta_table(text, "PR"), yaml_field(text, "github_pr"))),
                    branch=first_nonempty(field_from_meta_table(text, "Branch"), yaml_field(text, "branch")),
                    worktree=first_nonempty(field_from_meta_table(text, "Worktree"), yaml_field(text, "worktree")),
                    work_level=first_nonempty(field_from_meta_table(text, "Work Level"), yaml_field(text, "work_level")),
                    source="local_task",
                )
            )
    return records


def branch_commits(repo_root: Path) -> dict[str, str]:
    raw = run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)|%(objectname:short)|%(committerdate:iso8601)",
            "refs/heads",
            "refs/remotes/origin",
        ],
        cwd=repo_root,
    )
    out: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        name, sha, date = parts
        out[name] = f"{sha} {date}"
        if name.startswith("origin/"):
            out.setdefault(name.removeprefix("origin/"), f"{sha} {date}")
    return out


def parse_prs(prs: list[dict[str, Any]]) -> list[PullRequestRecord]:
    records: list[PullRequestRecord] = []
    for pr in prs:
        body = str(pr.get("body") or "")
        title = str(pr.get("title") or "")
        records.append(
            PullRequestRecord(
                number=int(pr.get("number") or 0),
                title=title,
                url=str(pr.get("url") or ""),
                state=str(pr.get("state") or ""),
                is_draft=bool(pr.get("isDraft")),
                head_ref=str(pr.get("headRefName") or ""),
                head_sha=str(pr.get("headRefOid") or "")[:12],
                updated_at=str(pr.get("updatedAt") or ""),
                task_id=first_nonempty(field_after_label(body, "Task ID"), task_id_from_text(title), task_id_from_text(body)),
            )
        )
    return records


def build_matrix(
    issues: list[dict[str, Any]],
    tasks: list[TaskRecord],
    prs: list[PullRequestRecord],
    branches: dict[str, str],
) -> list[MatrixRow]:
    task_by_id: dict[str, list[TaskRecord]] = {}
    for task in tasks:
        task_by_id.setdefault(task.task_id, []).append(task)

    pr_by_task = {pr.task_id: pr for pr in prs if pr.task_id}
    pr_by_branch = {pr.head_ref: pr for pr in prs if pr.head_ref}
    issue_task_counts: dict[str, int] = {}
    issue_rows: list[MatrixRow] = []

    for issue in sorted(issues, key=lambda item: int(item.get("number") or 0)):
        number = int(issue.get("number") or 0)
        title = str(issue.get("title") or "")
        body = str(issue.get("body") or "")
        labels = label_names(issue)
        task_id = first_nonempty(
            field_after_label(body, "Task ID"),
            task_id_from_text(title),
            task_id_from_text(body),
        )
        branch = first_nonempty(
            field_after_label(body, "Task branch"),
            field_after_label(body, "Branch"),
            branch_from_text(body),
        )
        issue_ref = f"#{number}" if number else ""
        matches = task_by_id.get(task_id, []) if task_id else []
        linked_matches = [task for task in tasks if task.github_issue == issue_ref]
        if not matches and linked_matches:
            matches = linked_matches
            task_id = linked_matches[0].task_id
        task = choose_task(matches)
        if task and not branch:
            branch = task.branch
        pr = pr_by_task.get(task_id) or pr_by_branch.get(branch)
        pr_ref = f"#{pr.number}" if pr else clean_ref(first_nonempty(field_after_label(body, "Draft PR"), task.github_pr if task else ""))
        status = normalize_status(first_nonempty(field_after_label(body, "Current status"), task.status if task else "", status_from_labels(labels)))
        conflicts = detect_issue_conflicts(issue_ref, task_id, matches, task, branch, pr_ref, pr)
        classification = classify_issue(title, body, labels, task, matches, status, conflicts)
        recommendation = recommend_issue(classification, issue_ref, task_id, pr_ref, status)
        if task_id:
            issue_task_counts[task_id] = issue_task_counts.get(task_id, 0) + 1
        issue_rows.append(
            MatrixRow(
                item_type="issue",
                issue=issue_ref,
                issue_title=title,
                task_id=task_id,
                task_path=task.path if task else "",
                branch=branch,
                pr=pr_ref,
                pr_state=pr_state(pr),
                status=status,
                last_commit=branches.get(branch, ""),
                classification=classification,
                recommendation=recommendation,
                conflicts="; ".join(conflicts),
                issue_url=str(issue.get("url") or ""),
                pr_url=pr.url if pr else "",
            )
        )

    rows = issue_rows[:]
    open_issue_numbers = {int(issue.get("number") or 0) for issue in issues}
    issue_refs = {f"#{number}" for number in open_issue_numbers}
    issue_task_ids = {row.task_id for row in issue_rows if row.task_id}

    for task in tasks:
        status = normalize_status(task.status)
        if is_completed_status(status) or status in SUPERSEDED_STATUSES:
            continue
        if status not in ACTIVE_STATUSES:
            continue
        if task.task_id in issue_task_ids:
            continue
        issue_ref = task.github_issue
        linked_issue_open = issue_ref in issue_refs if issue_ref else False
        classification = "Active" if linked_issue_open else "Orphan TASK"
        recommendation = "补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。"
        pr = pr_by_task.get(task.task_id) or pr_by_branch.get(task.branch)
        rows.append(
            MatrixRow(
                item_type="task",
                issue=issue_ref,
                issue_title="",
                task_id=task.task_id,
                task_path=task.path,
                branch=task.branch,
                pr=f"#{pr.number}" if pr else task.github_pr,
                pr_state=pr_state(pr),
                status=status,
                last_commit=branches.get(task.branch, ""),
                classification=classification,
                recommendation=recommendation,
                conflicts="" if linked_issue_open else "no open issue linked",
                issue_url="",
                pr_url=pr.url if pr else "",
            )
        )

    for row in rows:
        if row.task_id and issue_task_counts.get(row.task_id, 0) > 1 and row.classification != "Conflict":
            rows[rows.index(row)] = MatrixRow(**{**asdict(row), "classification": "Conflict", "conflicts": append_conflict(row.conflicts, "multiple open issues reference same TASK"), "recommendation": "先人工确认唯一 Issue，再关闭或 supersede 重复 Issue。"})
    return rows


def choose_task(matches: list[TaskRecord]) -> TaskRecord | None:
    if not matches:
        return None
    active = [task for task in matches if task.status in ACTIVE_STATUSES]
    return (active or matches)[0]


def classify_issue(
    title: str,
    body: str,
    labels: list[str],
    task: TaskRecord | None,
    matches: list[TaskRecord],
    status: str,
    conflicts: list[str],
) -> str:
    text = f"{title}\n{body}\n{' '.join(labels)}".lower()
    if conflicts:
        return "Conflict"
    if not task and not matches:
        return "Orphan Issue"
    if status in SUPERSEDED_STATUSES or "superseded" in text or "not planned" in text:
        return "Superseded"
    if is_completed_status(status) or "status/delivery-ready" in labels or "delivery_ready" in text:
        return "Completed"
    return "Active"


def recommend_issue(classification: str, issue_ref: str, task_id: str, pr_ref: str, status: str) -> str:
    if classification == "Active":
        missing = []
        if not task_id:
            missing.append("TASK")
        if not pr_ref:
            missing.append("Draft PR")
        if missing:
            return f"迁移到 V3，补充 {' / '.join(missing)} 关联后继续。"
        return "迁移到 V3；确认 Issue/TASK/branch/PR 同步后继续。"
    if classification == "Completed":
        return "补交付摘要和结果链接，用户确认后关闭 Issue。"
    if classification == "Superseded":
        return "用户确认后关闭为 not planned / superseded，不删除历史 TASK。"
    if classification == "Orphan Issue":
        return "补 TASK/branch/PR 字段；若已无效，用户确认后关闭。"
    if classification == "Orphan TASK":
        return "补 Issue 或归档 TASK；不要删除历史 TASK。"
    if classification == "Conflict":
        return "先人工消歧，确认唯一 Issue/TASK/branch/PR 后再迁移。"
    return "人工复核。"


def detect_issue_conflicts(
    issue_ref: str,
    task_id: str,
    matches: list[TaskRecord],
    task: TaskRecord | None,
    branch: str,
    pr_ref: str,
    pr: PullRequestRecord | None,
) -> list[str]:
    conflicts: list[str] = []
    if len(matches) > 1:
        conflicts.append("multiple local TASK files match task_id")
    if task and task.github_issue and task.github_issue != issue_ref:
        conflicts.append(f"TASK links {task.github_issue}, issue is {issue_ref}")
    if task and task.branch and branch and task.branch != branch:
        conflicts.append(f"branch mismatch issue={branch} task={task.branch}")
    if pr and branch and pr.head_ref and pr.head_ref != branch:
        conflicts.append(f"PR branch mismatch pr={pr.head_ref} issue/task={branch}")
    if pr and pr_ref and pr_ref != f"#{pr.number}":
        conflicts.append(f"PR number mismatch issue/task={pr_ref} resolved=#{pr.number}")
    return conflicts


def append_conflict(existing: str, value: str) -> str:
    return f"{existing}; {value}" if existing else value


def pr_state(pr: PullRequestRecord | None) -> str:
    if not pr:
        return ""
    return f"{'draft ' if pr.is_draft else ''}{pr.state}".strip()


def label_names(issue: dict[str, Any]) -> list[str]:
    labels = issue.get("labels") or []
    if not isinstance(labels, list):
        return []
    names = []
    for label in labels:
        if isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
        elif isinstance(label, str):
            names.append(label)
    return names


def status_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith("status/"):
            return label.split("/", 1)[1].replace("-", "_").upper()
    return ""


def task_id_from_text(text: str) -> str:
    match = re.search(r"\bTASK-[A-Za-z0-9_.-]+", text)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)")


def branch_from_text(text: str) -> str:
    patterns = [
        r"(?:分支|branch)\s*[:：]\s*([A-Za-z0-9_./-]+)",
        r"\b(codex/[A-Za-z0-9_./-]+)\b",
        r"\b(feature/[A-Za-z0-9_./-]+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1).rstrip(".,;:)，。")
    return ""


def field_after_label(text: str, label: str) -> str:
    patterns = [
        rf"(?im)^\s*[-*]?\s*{re.escape(label)}\s*[:：]\s*(.+?)\s*$",
        rf"(?im)^\s*\|\s*{re.escape(label)}\s*\|\s*(.+?)\s*\|",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_cell(match.group(1))
    return ""


def field_from_meta_table(text: str, field: str) -> str:
    meta = re.search(r"##\s*0\..*?(?=\n##\s|\Z)", text, re.S)
    target = meta.group(0) if meta else text[:2000]
    return field_after_label(target, field)


def yaml_field(text: str, field: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", text[:1500])
    return clean_cell(match.group(1)) if match else ""


def quoted_status(text: str) -> str:
    match = re.search(r"状态[：:]\s*`?([A-Z0-9_-]+)`?", text[:1200])
    return match.group(1) if match else ""


def clean_cell(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("`", "").strip()
    value = re.sub(r"\s+", " ", value)
    if value in {"-", "—", "待创建", "待创建（L1 可选）", "待定", "N/A"}:
        return ""
    return value


def clean_ref(value: str) -> str:
    value = clean_cell(value)
    if not value:
        return ""
    match = re.search(r"#(\d+)", value)
    if match:
        return f"#{match.group(1)}"
    if value.isdigit():
        return f"#{value}"
    return value


def normalize_status(value: str) -> str:
    return clean_cell(value).upper().replace("-", "_").replace(" ", "_")


def is_completed_status(status: str) -> bool:
    return status in COMPLETED_STATUSES or status.startswith("DELIVERY_READY") or status.startswith("RESULT_READY")


def first_nonempty(*values: str) -> str:
    for value in values:
        cleaned = clean_cell(value)
        if cleaned:
            return cleaned
    return ""


def write_csv(path: Path, rows: list[MatrixRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(rows[0]).keys()) if rows else list(MatrixRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_report(rows: list[MatrixRow], *, repo: str, generated_at: str, output_dir: Path) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.classification] = counts.get(row.classification, 0) + 1
    lines = [
        "# GitHub TASK Migration Report",
        "",
        f"生成时间：{generated_at}",
        "",
        f"Repository：`{repo}`",
        "",
        "## 范围",
        "",
        f"- Open Issues：{sum(1 for row in rows if row.item_type == 'issue')}",
        f"- Open / Draft PRs：{sum(1 for row in rows if row.pr)} linked in matrix",
        f"- Matrix Rows：{len(rows)}",
        "",
        "## 结论",
        "",
        "本报告是 WS-GH-014 第一轮只读审计结果。未关闭 Issue，未修改标签，未写 GitHub，未修改业务代码或数据。",
        "",
        "## 分类统计",
        "",
        "| 分类 | 数量 |",
        "|---|---:|",
    ]
    for key in ["Active", "Completed", "Superseded", "Orphan Issue", "Orphan TASK", "Conflict"]:
        lines.append(f"| {key} | {counts.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## 迁移矩阵",
            "",
            "| Item | Issue | Task ID | TASK path | Branch | PR | Status | Last commit | Class | Recommendation | Conflict |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.item_type,
                    row.issue or "-",
                    row.task_id or "-",
                    row.task_path or "-",
                    row.branch or "-",
                    row.pr or "-",
                    row.status or "-",
                    row.last_commit or "-",
                    row.classification,
                    row.recommendation,
                    row.conflicts or "-",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 建议执行顺序",
            "",
            "1. 先处理 `Conflict`：确认唯一 Issue / TASK / branch / PR，避免多个 active Issue 指向同一 TASK。",
            "2. 再处理 `Completed`：补 delivery summary / result summary，用户确认后关闭。",
            "3. 再处理 `Orphan Issue`：补 TASK 或关闭为 superseded / not planned。",
            "4. 再处理 `Orphan TASK`：补 Issue 或归档，不删除历史 TASK。",
            "5. 最后处理 `Active`：迁移到 V3，补齐 Draft PR 和 Issue/TASK/branch/PR 字段。",
            "",
            "## 审计产物",
            "",
            f"- `{output_dir / 'migration_matrix.csv'}`",
            f"- `{output_dir / 'migration_matrix.json'}`",
            f"- `{output_dir / 'migration_report.md'}`",
            "",
            "## 禁止动作",
            "",
            "- 本轮不关闭 Issue。",
            "- 本轮不改 GitHub label。",
            "- 本轮不创建或删除 TASK。",
            "- 本轮不 push、merge、deploy。",
            "- 本轮不删除历史 TASK。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of GitHub Issue/TASK/PR links for V3 migration.")
    parser.add_argument("--repo", default=REPO_SLUG)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--doc-report", default=str(DEFAULT_DOC_REPORT))
    parser.add_argument("--issues-file", type=Path, help="offline JSON fixture for open issues")
    parser.add_argument("--prs-file", type=Path, help="offline JSON fixture for open PRs")
    parser.add_argument("--json", action="store_true", help="print summary JSON")
    args = parser.parse_args(argv)

    repo_root = Path.cwd().resolve()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    issues = load_open_issues(repo_root, args.repo, args.issues_file)
    prs_raw = load_open_prs(repo_root, args.repo, args.prs_file)
    tasks = scan_tasks(repo_root)
    prs = parse_prs(prs_raw)
    branches = branch_commits(repo_root)
    rows = build_matrix(issues, tasks, prs, branches)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(rows, repo=args.repo, generated_at=generated_at, output_dir=Path(args.output_dir))
    write_csv(output_dir / "migration_matrix.csv", rows)
    write_json(
        output_dir / "migration_matrix.json",
        {
            "repo": args.repo,
            "generated_at": generated_at,
            "open_issue_count": len(issues),
            "open_pr_count": len(prs),
            "task_count": len(tasks),
            "rows": [asdict(row) for row in rows],
        },
    )
    (output_dir / "migration_report.md").write_text(report, encoding="utf-8")

    doc_report = Path(args.doc_report)
    if not doc_report.is_absolute():
        doc_report = repo_root / doc_report
    doc_report.parent.mkdir(parents=True, exist_ok=True)
    doc_report.write_text(report, encoding="utf-8")

    if args.json:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.classification] = counts.get(row.classification, 0) + 1
        print(json.dumps({"open_issues": len(issues), "open_prs": len(prs), "tasks": len(tasks), "rows": len(rows), "classifications": counts}, ensure_ascii=False, indent=2))
    else:
        print(f"wrote {output_dir / 'migration_report.md'}")
        print(f"wrote {doc_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
