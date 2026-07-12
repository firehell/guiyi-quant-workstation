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
        allowed_paths=tuple(_paths_from_scope(text, forbidden=False)),
        forbidden_paths=tuple(_paths_from_scope(text, forbidden=True)),
        required_tests=tuple(_required_tests(text)),
    )


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
