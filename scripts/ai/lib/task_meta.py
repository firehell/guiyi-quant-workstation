"""Task metadata helpers for the local AI workstation dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


TASK_SEARCH_DIRS = (
    Path("docs/tasks"),
    Path(".ai/tasks"),
    Path("docs/tasks/examples"),
)


class TaskMetaError(ValueError):
    """Raised when a task file cannot be resolved or parsed."""


@dataclass(frozen=True)
class TaskMeta:
    path: Path
    task_id: str
    work_level: str
    github_issue: str
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


def parse_task_file(path: Path | str) -> TaskMeta:
    task_path = Path(path).resolve()
    text = task_path.read_text(encoding="utf-8")
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

    return TaskMeta(
        path=task_path,
        task_id=task_id,
        work_level=work_level,
        github_issue=fields.get("GitHub Issue", ""),
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
    )


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
        return "fast"
    return _infer_task_routing_tier(meta, text)


def infer_external_review_required(meta: TaskMeta, text: str) -> bool:
    if meta.critical:
        return True
    explicit = _field_value(text, "External Review Required").lower()
    if explicit in {"true", "yes", "required", "是", "需要"}:
        return True
    if re.search(r"(?i)\bcritical\b|外部审查|required external review|external_review_required", text):
        return True
    if _matches_any(text, CRITICAL_BODY_KEYWORDS):
        return True
    if _matches_any(meta.task_type, CRITICAL_TASK_TYPE_KEYWORDS):
        return True
    return False


def is_production_write_requested(meta: TaskMeta, text: str) -> bool:
    scan = f"{meta.data_impact}\n{text}"
    return any(re.search(pattern, scan, re.I) for pattern in PRODUCTION_WRITE_KEYWORDS)


def _infer_task_routing_tier(meta: TaskMeta, text: str) -> str:
    if _is_deep_task(meta, text):
        return "deep"
    if _is_critical_task(meta, text):
        return "critical"
    if meta.work_level == "L0" and _matches_any(meta.task_type, DOC_FAST_KEYWORDS):
        return "fast"
    return "standard"


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
