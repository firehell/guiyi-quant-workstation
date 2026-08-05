#!/usr/bin/env python3
"""Static Runtime / frozen-Gate dependency inventory.

Never executes discovered strings or imports candidate modules. Paths are
normalized and must remain repository-contained.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ReferenceKind(StrEnum):
    IMPORT = "import"
    DYNAMIC_IMPORT = "dynamic_import"
    SUBPROCESS_CLI = "subprocess_cli"
    CONFIG_ENV = "config_env"
    STARTUP = "startup"
    TEST = "test"
    DOC = "doc"


class RemovalDisposition(StrEnum):
    DELETE = "delete"
    RETAIN = "retain"
    SUPERSEDED_DISABLED = "superseded_disabled"


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    source: str
    target: str
    kind: ReferenceKind

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
        }


@dataclass(frozen=True, slots=True)
class RemovalCandidate:
    path: str
    disposition: RemovalDisposition
    active_runtime_refs: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "disposition": self.disposition.value,
            "active_runtime_refs": self.active_runtime_refs,
            "detail": self.detail,
        }


_CANDIDATE_GLOBS = (
    "services/quant-api/app/services/htdy_s6_10_*.py",
    "scripts/jm_htdy_s6_10_*.py",
)

_RUNTIME_KINDS = frozenset(
    {
        ReferenceKind.IMPORT,
        ReferenceKind.DYNAMIC_IMPORT,
        ReferenceKind.SUBPROCESS_CLI,
        ReferenceKind.CONFIG_ENV,
        ReferenceKind.STARTUP,
    }
)


def _normalize_repo_path(repo_root: Path, path: Path) -> str | None:
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(repo_root.resolve())
    except Exception:
        return None
    text = relative.as_posix()
    if ".." in text.split("/"):
        return None
    return text


def discover_candidates(repo_root: Path) -> list[str]:
    found: set[str] = set()
    for pattern in _CANDIDATE_GLOBS:
        for path in repo_root.glob(pattern):
            relative = _normalize_repo_path(repo_root, path)
            if relative and path.is_file():
                found.add(relative)
    return sorted(found)


def _module_name_from_service(relative: str) -> str | None:
    if relative.startswith("services/quant-api/app/") and relative.endswith(".py"):
        body = relative[len("services/quant-api/") : -3].replace("/", ".")
        return body
    return None


def _collect_python_files(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / "services" / "quant-api",
        repo_root / "scripts",
        repo_root / "tests",
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in {".venv", "__pycache__", "node_modules"} for part in path.parts):
                continue
            files.append(path)
    return files


def _iter_import_names(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            yield node.module


def _string_literals(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def scan_references(repo_root: Path, candidates: Sequence[str]) -> list[ReferenceRecord]:
    candidate_set = set(candidates)
    module_to_path = {
        name: path
        for path in candidates
        if (name := _module_name_from_service(path)) is not None
    }
    script_names = {
        Path(path).name: path for path in candidates if path.startswith("scripts/")
    }
    records: list[ReferenceRecord] = []

    for path in _collect_python_files(repo_root):
        source = _normalize_repo_path(repo_root, path)
        if source is None:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=source)
        except (OSError, SyntaxError):
            continue

        kind_base = (
            ReferenceKind.TEST
            if "/tests/" in f"/{source}/" or source.startswith("tests/")
            else ReferenceKind.IMPORT
        )
        if source.endswith("runtime_scheduler.py") or source.endswith("main.py"):
            kind_base = ReferenceKind.STARTUP

        for node in ast.walk(tree):
            for name in _iter_import_names(node):
                for module, target in module_to_path.items():
                    if name == module or name.startswith(module + "."):
                        if source == target:
                            continue
                        records.append(ReferenceRecord(source, target, kind_base))
            if isinstance(node, ast.Call):
                func = node.func
                func_name = ""
                if isinstance(func, ast.Attribute):
                    func_name = func.attr
                elif isinstance(func, ast.Name):
                    func_name = func.id
                if func_name in {"import_module", "__import__"}:
                    for literal in _string_literals(node):
                        for module, target in module_to_path.items():
                            if literal == module or literal.startswith(module + "."):
                                records.append(
                                    ReferenceRecord(
                                        source, target, ReferenceKind.DYNAMIC_IMPORT
                                    )
                                )
                if func_name in {"run", "Popen", "call", "check_call", "check_output"}:
                    for literal in _string_literals(node):
                        base = Path(literal.replace("\\", "/")).name
                        if base in script_names:
                            records.append(
                                ReferenceRecord(
                                    source,
                                    script_names[base],
                                    ReferenceKind.SUBPROCESS_CLI,
                                )
                            )

        text = path.read_text(encoding="utf-8")
        for candidate in candidate_set:
            if candidate == source:
                continue
            stem = Path(candidate).stem
            if stem in text or candidate in text:
                if any(
                    item.source == source and item.target == candidate for item in records
                ):
                    continue
                # config/env style mention
                if re.search(
                    rf"(?:GUIYI_|HTDY_|S6_10|APPROVAL|PACKET).{{0,40}}{re.escape(stem)}",
                    text,
                    re.IGNORECASE,
                ):
                    records.append(
                        ReferenceRecord(source, candidate, ReferenceKind.CONFIG_ENV)
                    )

    # Docs references
    for doc in (repo_root / "docs").rglob("*.md") if (repo_root / "docs").exists() else []:
        source = _normalize_repo_path(repo_root, doc)
        if source is None:
            continue
        try:
            text = doc.read_text(encoding="utf-8")
        except OSError:
            continue
        for candidate in candidate_set:
            name = Path(candidate).name
            if name in text or candidate in text:
                records.append(ReferenceRecord(source, candidate, ReferenceKind.DOC))

    records.sort(key=lambda item: (item.target, item.kind.value, item.source))
    return records


def build_removal_candidates(
    candidates: Sequence[str],
    references: Sequence[ReferenceRecord],
) -> list[RemovalCandidate]:
    by_target: dict[str, list[ReferenceRecord]] = {path: [] for path in candidates}
    for ref in references:
        by_target.setdefault(ref.target, []).append(ref)

    result: list[RemovalCandidate] = []
    for path in candidates:
        refs = by_target.get(path, [])
        runtime_refs = [ref for ref in refs if ref.kind in _RUNTIME_KINDS]
        if runtime_refs:
            disposition = RemovalDisposition.RETAIN
            detail = f"{len(runtime_refs)} active runtime/code references block deletion"
        elif any(ref.kind is ReferenceKind.TEST for ref in refs):
            disposition = RemovalDisposition.RETAIN
            detail = "test-only references remain; migrate tests before delete"
        elif any(ref.kind is ReferenceKind.DOC for ref in refs):
            disposition = RemovalDisposition.RETAIN
            detail = "doc references remain; close references before delete"
        else:
            disposition = RemovalDisposition.DELETE
            detail = "zero active references"
        result.append(
            RemovalCandidate(
                path=path,
                disposition=disposition,
                active_runtime_refs=len(runtime_refs),
                detail=detail,
            )
        )
    result.sort(key=lambda item: item.path)
    if any(item.disposition is RemovalDisposition.DELETE and item.active_runtime_refs for item in result):
        raise RuntimeError("delete disposition cannot have active runtime refs")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory frozen Gate dependencies.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0

    root = Path(__file__).resolve().parents[2] if args.root is None else args.root.resolve()
    if not root.is_dir():
        print("invalid --root", file=sys.stderr)
        return 2

    candidates = discover_candidates(root)
    references = scan_references(root, candidates)
    removals = build_removal_candidates(candidates, references)
    payload = {
        "schema_version": 1,
        "operation": "runtime_dependency_inventory",
        "status": "ok",
        "candidates": [item.to_dict() for item in removals],
        "references": [item.to_dict() for item in references],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    else:
        print(f"[OK] candidates={len(removals)} references={len(references)}")
        for item in removals:
            print(
                f"  {item.path}: {item.disposition.value} runtime_refs={item.active_runtime_refs}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
