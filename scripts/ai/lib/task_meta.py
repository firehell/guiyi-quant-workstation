"""Task metadata helpers for the local AI workstation dispatcher.

V2 (2026-07-13): Added YAML frontmatter parsing, risk_level, approval_scope,
depends_on, and model_profile fields. Fully backward compatible with legacy
markdown-table tasks via compat_reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
import re
import sys
import warnings

from task_runtime import TaskRuntimeError, load_task_runtime


TASK_SEARCH_DIRS = (
    Path("docs/tasks"),
    Path(".ai/tasks"),
    Path("docs/tasks/examples"),
    Path("docs/tasks/workstation"),
)

YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class TaskMetaError(ValueError):
    """Raised when a task file cannot be resolved or parsed."""


@dataclass(frozen=True)
class TaskMeta:
    path: Path
    task_id: str
    work_level: str
    github_issue: str
    github_pr: str
    branch: str
    worktree: str
    status: str
    critical: bool
    production_write_approved: bool
    task_type: str
    data_impact: str
    required_env: tuple[str, ...]
    required_mounts: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    # --- V2 fields ---
    risk_level: str = "R3"
    approval_scope: tuple[str, ...] = ("plan", "code")
    depends_on: tuple[str, ...] = ()
    resource_locks: tuple[str, ...] = ()
    model_profile: str = "balanced"
    base_branch: str = "main"
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = "1.0"


def resolve_task_file(task_id_or_file: str, repo_root: Path | str | None = None) -> Path:
    """Resolve a task ID or task file path from the repository root."""

    root = Path(repo_root or Path.cwd()).resolve()
    raw = Path(task_id_or_file).expanduser()
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(root / raw)
        for directory in TASK_SEARCH_DIRS:
            candidates.append(root / directory / f"{task_id_or_file}.md")

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise TaskMetaError(f"TASK not found: {task_id_or_file}")


def _has_yaml_frontmatter(text: str) -> bool:
    """Check if a markdown file has a YAML frontmatter block."""
    return bool(YAML_FRONTMATTER_RE.match(text))


def _parse_v2_task(task_path: Path, text: str) -> TaskMeta:
    """Parse a V2/V3 YAML-frontmatter task into TaskMeta."""
    try:
        from compat_reader import parse_task_file as compat_parse
    except ImportError:
        raise TaskMetaError("compat_reader.py required for V2 task parsing")

    data = compat_parse(str(task_path))

    # Legacy section extraction (body after YAML frontmatter)
    body = YAML_FRONTMATTER_RE.sub("", text)
    task_type = _section(body, r"## 2\.").strip()
    data_impact = _section(body, r"## 10\.").strip()

    # Extract paths from legacy sections for backward compat
    allowed_paths_v2 = tuple(data.get("allowed_paths", []))
    forbidden_paths_v2 = tuple(data.get("forbidden_paths", []))
    required_tests_v2 = tuple(data.get("required_tests", []))

    # If V2 fields are empty, fall back to legacy extraction
    if not allowed_paths_v2:
        allowed_paths_v2 = tuple(_paths_from_scope(body, forbidden=False))
    if not forbidden_paths_v2:
        forbidden_paths_v2 = tuple(_paths_from_scope(body, forbidden=True))
    if not required_tests_v2:
        required_tests_v2 = tuple(_required_tests(body))

    return TaskMeta(
        path=task_path,
        task_id=data["task_id"],
        work_level=data.get("work_level", "L2"),
        github_issue=data.get("github_issue", ""),
        github_pr=data.get("github_pr", ""),
        branch=data.get("branch", ""),
        worktree=data.get("worktree", ""),
        status=data.get("status", ""),
        critical=data.get("critical", False),
        production_write_approved=data.get("production_write_approved", False),
        task_type=task_type,
        data_impact=data_impact,
        required_env=tuple(data.get("required_env", [])),
        required_mounts=tuple(data.get("required_mounts", [])),
        allowed_paths=allowed_paths_v2,
        forbidden_paths=forbidden_paths_v2,
        required_tests=required_tests_v2,
        risk_level=data.get("risk_level", "R3"),
        approval_scope=tuple(data.get("approval_scope", ["plan", "code"])),
        depends_on=tuple(data.get("depends_on", [])),
        resource_locks=tuple(data.get("resource_locks", [])),
        model_profile=data.get("model_profile", "balanced"),
        base_branch=data.get("base_branch", "main"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        schema_version=str(data.get("schema_version", "2.0")),
    )


def parse_task_file(path: Path | str, *, repo_root: Path | str | None = None, include_runtime: bool = True) -> TaskMeta:
    """Parse a task file (V2 YAML frontmatter or legacy markdown table) into TaskMeta."""
    task_path = Path(path).resolve()
    text = task_path.read_text(encoding="utf-8")

    # V2 YAML frontmatter detection
    if _has_yaml_frontmatter(text):
        try:
            meta = _parse_v2_task(task_path, text)
            return _apply_runtime_overlay(meta, repo_root) if include_runtime else meta
        except Exception as e:
            # Fail-closed: don't fall back to legacy parsing for V2 files
            raise TaskMetaError(f"V2 task parse failed for {task_path}: {e}") from e

    # Legacy markdown-table parsing
    meta_section = _section(text, r"## 0\.")
    if not meta_section:
        raise TaskMetaError("TASK metadata section missing: ## 0.")

    fields = {
        match.group(1).strip(): match.group(2).strip()
        for match in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", meta_section, re.M)
    }
    task_id = fields.get("Task ID", "")
    if not task_id:
        raise TaskMetaError("TASK metadata missing: Task ID")

    work_level = (fields.get("Work Level") or "L2").upper().replace(" ", "")
    if work_level not in {"L0", "L1", "L2"}:
        work_level = "L2"

    # Try V2 compat reading for risk_level and approval_scope
    risk_level = "R3"
    approval_scope = ("plan", "code")
    try:
        from compat_reader import parse_task_file as compat_parse
        v2_data = compat_parse(str(task_path))
        risk_level = v2_data.get("risk_level", "R3")
        scope = v2_data.get("approval_scope", ["plan", "code"])
        approval_scope = tuple(scope) if scope else ("plan", "code")
    except Exception:
        pass  # Silently fall back to defaults for legacy tasks

    meta = TaskMeta(
        path=task_path,
        task_id=task_id,
        work_level=work_level,
        github_issue=fields.get("GitHub Issue", ""),
        github_pr=fields.get("GitHub PR", ""),
        branch=fields.get("Branch", ""),
        worktree=fields.get("Worktree", ""),
        status=fields.get("Status", ""),
        critical=_truthy(fields.get("Critical", "")),
        production_write_approved=_truthy(fields.get("Production Write Approved", "")),
        task_type=_section(text, r"## 2\.").strip(),
        data_impact=_section(text, r"## 10\.").strip(),
        required_env=tuple(_list_field(fields, ("Required Env", "required_env"))),
        required_mounts=tuple(_list_field(fields, ("Required Mounts", "required_mounts"))),
        allowed_paths=tuple(_paths_from_scope(text, forbidden=False)),
        forbidden_paths=tuple(_paths_from_scope(text, forbidden=True)),
        required_tests=tuple(_required_tests(text)),
        risk_level=risk_level,
        approval_scope=approval_scope,
        schema_version="1.0",
    )
    return _apply_runtime_overlay(meta, repo_root) if include_runtime else meta


def _apply_runtime_overlay(meta: TaskMeta, repo_root: Path | str | None = None) -> TaskMeta:
    root = Path(repo_root).resolve() if repo_root else _infer_repo_root(meta.path)
    try:
        runtime = load_task_runtime(root, meta.task_id, required=False)
    except TaskRuntimeError as exc:
        raise TaskMetaError(str(exc)) from exc
    if not runtime:
        return meta

    updates: dict[str, str] = {}
    if runtime.get("worktree"):
        updates["worktree"] = str(runtime["worktree"])
    if runtime.get("local_branch"):
        updates["branch"] = str(runtime["local_branch"])
    if runtime.get("issue_number") and not meta.github_issue:
        updates["github_issue"] = f"#{runtime['issue_number']}"
    if runtime.get("pr_number") and not meta.github_pr:
        updates["github_pr"] = f"#{runtime['pr_number']}"
    return replace(meta, **updates) if updates else meta


def _infer_repo_root(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate.resolve()
    return Path.cwd().resolve()


CRITICAL_TASK_TYPE_KEYWORDS = (
    "策略",
    "回测",
    "数据库",
    "数据中心",
    "worker",
    "scheduler",
    "风控",
    "指标",
)
CRITICAL_BODY_KEYWORDS = (
    r"\bEMA\b",
    r"\bMACD\b",
    r"\bseed\b",
    r"warm[- ]?up",
    r"external_review_required",
    r"外部审查",
)
DEEP_KEYWORDS = (
    "scheduler recovery",
    "跨模块",
    "runtime",
    "恢复",
)
DOC_FAST_KEYWORDS = ("文档", "doc", "AI 工作流", "工作流优化")
PRODUCTION_WRITE_KEYWORDS = (
    r"production",
    r"生产",
    r"真实写入",
    r"persist_to_db\s*=\s*true",
    r"生产数据库",
)


def infer_routing_tier(meta: TaskMeta, text: str, stage: str) -> str:
    if stage in {"route", "test", "result"}:
        return "economy"
    return _infer_task_routing_tier(meta, text)


def infer_external_review_required(meta: TaskMeta, text: str) -> bool:
    explicit = _field_value(text, "External Review Required").lower()
    if explicit in {"true", "yes", "required", "是", "需要"}:
        return True
    if re.search(r"(?i)required external review|external_review_required|外部审查", text):
        return True
    return _infer_task_routing_tier(meta, text) == "deep"


def is_production_write_requested(meta: TaskMeta, text: str) -> bool:
    scan = f"{meta.data_impact}\n{text}"
    return any(re.search(pattern, scan, re.I) for pattern in PRODUCTION_WRITE_KEYWORDS)


def _infer_task_routing_tier(meta: TaskMeta, text: str) -> str:
    if _is_deep_task(meta, text):
        return "deep"
    if _is_critical_task(meta, text):
        return "deep"
    if meta.work_level == "L0" and _matches_any(meta.task_type, DOC_FAST_KEYWORDS):
        return "economy"
    return "balanced"


def _is_critical_task(meta: TaskMeta, text: str) -> bool:
    if meta.critical:
        return True
    if _matches_any(meta.task_type, CRITICAL_TASK_TYPE_KEYWORDS):
        return True
    return _matches_any(text, CRITICAL_BODY_KEYWORDS)


def _is_deep_task(meta: TaskMeta, text: str) -> bool:
    scan = f"{meta.task_type}\n{text}"
    return _matches_any(scan, DEEP_KEYWORDS)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "是", "critical", "required"}


def _field_value(text: str, field: str) -> str:
    match = re.search(rf"^\|\s*{re.escape(field)}\s*\|\s*(.*?)\s*\|$", text, re.M)
    return match.group(1).strip() if match else ""


def to_repo_relative(path: Path | str, repo_root: Path | str) -> str:
    resolved = Path(path).resolve()
    root = Path(repo_root).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _section(text: str, heading_pattern: str) -> str:
    pattern = re.compile(rf"^{heading_pattern}.*$", re.M)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end() :], re.M)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end]


def _paths_from_scope(text: str, *, forbidden: bool) -> list[str]:
    section = _section(text, r"## 7\.")
    if not section:
        return []
    marker = "**禁止修改**"
    if marker in section:
        before, after = section.split(marker, 1)
        scan = after if forbidden else before
    else:
        scan = "" if forbidden else section
    return [item.strip() for item in re.findall(r"`([^`]+)`", scan) if item.strip()]


def _list_field(fields: dict[str, str], names: tuple[str, ...]) -> list[str]:
    raw = ""
    for name in names:
        if fields.get(name):
            raw = fields[name]
            break
    if not raw or raw.strip() in {"-", "无", "none", "None", "N/A", "n/a"}:
        return []
    items = re.findall(r"`([^`]+)`", raw)
    if not items:
        items = re.split(r"[,，\s]+", raw)
    return [item.strip() for item in items if item.strip() and item.strip() not in {"-", "、"}]


def _required_tests(text: str) -> list[str]:
    section = _section(text, r"## 18\.")
    if not section:
        return []
    match = re.search(r"```bash\s*\n(.*?)\n```", section, re.S)
    if not match:
        return []
    commands: list[str] = []
    for line in match.group(1).splitlines():
        command = line.strip()
        if command and not command.startswith("#"):
            commands.append(command)
    return commands
