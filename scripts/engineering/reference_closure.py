"""Active-reference scanner for superseded script/CLI entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Sequence


DEFAULT_SCAN_ROOTS = (
    "README.md",
    "TESTING.md",
    "docs",
    "deploy",
    "Makefile",
    "services",
    "apps",
    "scripts",
    "tests",
)

# Historical evidence trees are excluded from active-reference closure.
EXCLUDED_PREFIXES = (
    "data/reports/",
    "data/receipts/",
    "data/evidence/",
    ".kiro/specs/personal-development-mode/",
)

SUPERSEDED_COMMAND_PATTERNS = (
    r"\bguiyi\s+data\s+plan\b",
    r"\bguiyi\s+data\s+migrate\b",
    r"\bguiyi\s+data\s+backfill\b",
    r"--pre-2020\b",
    r"--pre2020\b",
)

SUPERSEDED_PATH_PREFIXES = (
    "scripts/rqdata_",
    "scripts/backup/",
    "scripts/restore/",
)


@dataclass(frozen=True, slots=True)
class ReferenceHit:
    path: str
    line_number: int
    kind: str
    snippet: str


def scan_active_references(
    repo_root: Path,
    *,
    deleted_paths: Sequence[str] = (),
    roots: Sequence[str] = DEFAULT_SCAN_ROOTS,
) -> tuple[ReferenceHit, ...]:
    hits: list[ReferenceHit] = []
    command_res = [re.compile(pattern) for pattern in SUPERSEDED_COMMAND_PATTERNS]
    deleted = {path.replace("\\", "/") for path in deleted_paths}

    for root_name in roots:
        root = repo_root / root_name
        if not root.exists():
            continue
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
                continue
            if path.suffix.lower() not in {
                ".md",
                ".py",
                ".sh",
                ".ps1",
                ".yml",
                ".yaml",
                ".toml",
                ".txt",
                "",
            } and path.name != "Makefile":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                for regex in command_res:
                    if regex.search(line):
                        hits.append(
                            ReferenceHit(
                                path=rel,
                                line_number=idx,
                                kind="command",
                                snippet=line.strip()[:200],
                            )
                        )
                for deleted_path in deleted:
                    if deleted_path and deleted_path in line:
                        hits.append(
                            ReferenceHit(
                                path=rel,
                                line_number=idx,
                                kind="deleted_path",
                                snippet=line.strip()[:200],
                            )
                        )
                for prefix in SUPERSEDED_PATH_PREFIXES:
                    if prefix in line and "historical" not in line.lower():
                        hits.append(
                            ReferenceHit(
                                path=rel,
                                line_number=idx,
                                kind="path_prefix",
                                snippet=line.strip()[:200],
                            )
                        )
    return tuple(hits)


def active_reference_count(hits: Iterable[ReferenceHit]) -> int:
    return len(tuple(hits))
