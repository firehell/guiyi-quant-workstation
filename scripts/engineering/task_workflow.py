#!/usr/bin/env python3
"""Shared fail-closed policy for task automation and develop integration.

This module classifies a proposed task diff.  It deliberately does not run
GitHub, merge branches, or perform production writes; those side effects stay
in narrow shell entrypoints that call this policy first.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath


class WorkflowError(RuntimeError):
    """A stable, machine-readable reason why automation must stop."""

    def __init__(self, error_type: str, message: str) -> None:
        self.error_type = error_type
        super().__init__(f"{error_type}: {message}")


class _JsonArgumentParser(argparse.ArgumentParser):
    """Convert new-CLI syntax failures into the stable blocked JSON contract."""

    def error(self, message: str) -> None:
        raise WorkflowError("invalid_cli_arguments", message)


LANE_ONE_ALLOWED_PREFIXES = (
    "experiments/",
    "tests/",
    "docs/research/",
)

LANE_TWO_FORBIDDEN_PREFIXES = (
    ".codex/",
    ".github/",
    "data/raw/",
    "data/parquet/",
    "deploy/",
    "docs/decisions/",
    "services/quant-api/alembic/",
    "services/quant-api/app/signal/",
    "services/quant-api/app/tasks/",
    "services/quant-api/app/websocket/",
    "services/quant-api/app/runtime",
    "services/quant-api/app/after_market",
    "services/quant-api/app/services/live_",
    "services/quant-api/app/services/notification_",
    "services/quant-api/app/services/signal_",
    "scripts/configure-",
    "scripts/jm_live_",
    "scripts/jm_htdy_",
    "scripts/rqdata_live_",
    "scripts/run-",
    "scripts/install-",
    ".env",
)

LANE_TWO_FORBIDDEN_PATHS = {
    "AGENTS.md",
    "DECISIONS.md",
    "PROJECT_SOURCE.md",
}

DEVELOP_TRANSITION_OPERATIONS = frozenset({
    "develop_merge",
    "merge_readback",
    "cleanup",
})

MANUAL_GATE_OPERATIONS = frozenset({
    "main",
    "tag",
    "release",
    "runtime",
    "live",
    "notification",
    "data_write",
    "db_write",
    "delete",
    "github_rules",
    "apply",
    "write",
    "enable",
})

LANE_THREE_ISOLATED_MIGRATION_PREFIX = "services/quant-api/alembic/versions/"

LANE_THREE_MIGRATION_NAME_RE = re.compile(
    r"^[0-9]{8}_[0-9]{4}_[a-z0-9]+(?:_[a-z0-9]+)*\.py$",
)

LANE_THREE_MIGRATION_FORBIDDEN_TOKENS = frozenset({
    "approval",
    "evidence",
    "receipt",
    "report",
})

DEVELOP_CHANGE_CATEGORIES = frozenset({
    "code",
    "test",
    "dry_run",
    "disabled_feature",
    "isolated_migration",
})

LANE_THREE_CODE_SUFFIXES = frozenset({
    ".bash",
    ".cjs",
    ".js",
    ".jsx",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".vue",
    ".zsh",
})

LANE_THREE_TEST_DATA_SUFFIXES = frozenset({
    ".csv",
    ".html",
    ".json",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
})

LANE_THREE_FORBIDDEN_PREFIXES = (
    "data/",
    "reports/",
    "receipts/",
)

LANE_THREE_FORBIDDEN_PARTS = frozenset({"evidence", "reports", "receipts"})

def _validate_paths(paths: Sequence[str]) -> list[str]:
    normalized = list(paths)
    if not normalized:
        raise WorkflowError("empty_diff", "automation requires at least one changed path")
    if any(not path or path.startswith("/") or ".." in path.split("/") for path in normalized):
        raise WorkflowError("invalid_changed_path", "changed paths must be non-empty repository-relative paths")
    return normalized


def classify_paths(lane: int, paths: Sequence[str]) -> str:
    """Return ``ok`` or fail closed when a diff crosses a Lane boundary."""
    normalized = _validate_paths(paths)
    if lane == 1:
        for path in normalized:
            if not path.startswith(LANE_ONE_ALLOWED_PREFIXES):
                raise WorkflowError(
                    "lane_one_path_forbidden",
                    f"Lane 1 automation only accepts isolated experiment, test, or research-doc paths: {path}",
                )
        return "ok"
    if lane == 2:
        for path in normalized:
            if path in LANE_TWO_FORBIDDEN_PATHS or path.startswith(LANE_TWO_FORBIDDEN_PREFIXES):
                raise WorkflowError(
                    "lane_two_path_forbidden",
                    f"Lane 2 automation cannot change a Lane 3, Runtime, raw-data, migration, or secret path: {path}",
                )
        return "ok"
    raise WorkflowError("invalid_lane", "lane must be 1 or 2")


def classify_develop_merge(
    lane: int,
    paths: Sequence[str],
    requested_operations: Sequence[str],
    external_gates: Sequence[str],
    *,
    change_categories: Sequence[str] = (),
) -> str:
    """Return ``ok`` only for a side-effect-free develop transition.

    Lane 1/2 retain their existing path policy. Lane 3 code, tests, dry-run,
    disabled features, and isolated migrations may be integrated as code, but
    the corresponding real operation remains behind its dedicated manual Gate.
    """
    if external_gates:
        raise WorkflowError(
            "manual_gate_required",
            "develop automation cannot consume a pending external Gate",
        )
    operations = list(requested_operations)
    if any(operation in MANUAL_GATE_OPERATIONS for operation in operations):
        raise WorkflowError(
            "manual_gate_required",
            "requested operation requires a dedicated manual Gate",
        )
    if len(operations) != 1 or any(
        not isinstance(operation, str) or operation not in DEVELOP_TRANSITION_OPERATIONS
        for operation in operations
    ):
        raise WorkflowError(
            "unknown_requested_operation",
            "requested operations must be known develop transition operations",
        )
    categories = list(change_categories)
    if any(
        not isinstance(category, str) or category not in DEVELOP_CHANGE_CATEGORIES
        for category in categories
    ) or len(categories) != len(set(categories)):
        raise WorkflowError(
            "unknown_change_category",
            "change categories must be unique members of the closed safe-category set",
        )
    if lane in (1, 2):
        return classify_paths(lane, paths)
    if lane == 3:
        normalized = _validate_paths(paths)
        if not categories:
            raise WorkflowError(
                "lane_three_change_categories_required",
                "Lane 3 requires at least one digest-bound safe change category",
            )
        category_set = set(categories)
        migration_candidates = [
            path
            for path in normalized
            if path.startswith(LANE_THREE_ISOLATED_MIGRATION_PREFIX)
        ]
        migration_paths: list[str] = []
        for path in migration_candidates:
            relative = path.removeprefix(LANE_THREE_ISOLATED_MIGRATION_PREFIX)
            name = PurePosixPath(relative).name
            slug_tokens = name.removesuffix(".py").split("_")[2:]
            if (
                "/" in relative
                or LANE_THREE_MIGRATION_NAME_RE.fullmatch(name) is None
                or any(token in LANE_THREE_MIGRATION_FORBIDDEN_TOKENS for token in slug_tokens)
                or {"production", "data"}.issubset(slug_tokens)
            ):
                raise WorkflowError(
                    "lane_three_path_forbidden",
                    f"isolated migration must be a safe Alembic Python source filename: {path}",
                )
            migration_paths.append(path)
        lane_two_surface = [
            path
            for path in normalized
            if not path.startswith(LANE_THREE_ISOLATED_MIGRATION_PREFIX)
        ]
        if lane_two_surface:
            classify_paths(2, lane_two_surface)
        for path in normalized:
            parts = PurePosixPath(path).parts
            if path.startswith(LANE_THREE_FORBIDDEN_PREFIXES) or any(
                part in LANE_THREE_FORBIDDEN_PARTS for part in parts
            ):
                raise WorkflowError(
                    "lane_three_path_forbidden",
                    f"Lane 3 automation cannot change evidence, report, receipt, or data assets: {path}",
                )
        possible_categories: set[str] = set()
        categorized_paths: list[tuple[str, set[str]]] = []
        for path in normalized:
            pure = PurePosixPath(path)
            if path in migration_paths:
                path_categories = {"isolated_migration"}
            elif (
                path.startswith("tests/")
                or "tests" in pure.parts
                or pure.name.startswith("test_")
                or ".test." in pure.name
                or ".spec." in pure.name
            ) and pure.suffix.lower() in LANE_THREE_CODE_SUFFIXES | LANE_THREE_TEST_DATA_SUFFIXES:
                path_categories = {"test"}
            elif (
                "dry_run" in pure.name.lower()
                or "dry-run" in pure.name.lower()
            ) and pure.suffix.lower() in LANE_THREE_CODE_SUFFIXES:
                path_categories = {"dry_run"}
            elif pure.suffix.lower() in LANE_THREE_CODE_SUFFIXES:
                path_categories = {"code", "disabled_feature"}
            else:
                raise WorkflowError(
                    "lane_three_path_forbidden",
                    f"Lane 3 automation requires an explicit source, test, dry-run, or migration path: {path}",
                )
            categorized_paths.append((path, path_categories))
            possible_categories.update(path_categories)
        if migration_paths and "isolated_migration" not in category_set:
            raise WorkflowError(
                "isolated_migration_category_required",
                "isolated migration paths require the isolated_migration category",
            )
        if "isolated_migration" in category_set and not migration_paths:
            raise WorkflowError(
                "isolated_migration_path_required",
                "isolated_migration requires a path under the isolated migration prefix",
            )
        for path, path_categories in categorized_paths:
            if not category_set.intersection(path_categories):
                raise WorkflowError(
                    "lane_three_change_category_mismatch",
                    f"change categories do not describe the Lane 3 path: {path}",
                )
        if not category_set.issubset(possible_categories):
            raise WorkflowError(
                "lane_three_change_category_mismatch",
                "every declared Lane 3 category must bind at least one changed path",
            )
        return "ok"
    raise WorkflowError("invalid_lane", "lane must be 1, 2, or 3")


def _legacy_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True, type=int)
    parser.add_argument("--path-file", type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if args.path_file and args.paths:
        parser.error("paths and --path-file cannot be used together")
    if args.path_file:
        try:
            paths = args.path_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(json.dumps({"status": "blocked", "error_type": "path_file_unavailable", "detail": str(exc)}))
            return 2
    else:
        paths = args.paths
    try:
        status = classify_paths(args.lane, paths)
    except WorkflowError as exc:
        print(json.dumps({"status": "blocked", "error_type": exc.error_type, "detail": str(exc)}))
        return 2
    print(json.dumps({"status": status, "lane": args.lane, "paths": paths}))
    return 0


def _develop_merge_payload(
    *,
    lane: int | None,
    operation: str | None,
    paths: Sequence[str],
    change_categories: Sequence[str],
    external_gates: Sequence[str],
) -> dict[str, object]:
    return {
        "action": "develop-merge-check",
        "change_categories": list(change_categories),
        "external_gates": list(external_gates),
        "lane": lane,
        "operation": operation,
        "paths": list(paths),
        "schema_version": 1,
        "tool": "scripts/engineering/task_workflow.py",
    }


def _print_develop_merge_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _develop_merge_check_main(argv: Sequence[str]) -> int:
    parser = _JsonArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True, type=int)
    parser.add_argument("--path-file", type=Path)
    parser.add_argument("--operation", action="append", required=True)
    parser.add_argument("--change-category", action="append", default=[])
    parser.add_argument("--external-gate", action="append", default=[])
    parser.add_argument("paths", nargs="*")
    try:
        args = parser.parse_args(argv)
    except WorkflowError as exc:
        payload = _develop_merge_payload(
            lane=None,
            operation=None,
            paths=[],
            change_categories=[],
            external_gates=[],
        )
        payload.update({
            "decision": "block",
            "detail": str(exc),
            "error_type": exc.error_type,
            "status": "blocked",
        })
        _print_develop_merge_payload(payload)
        return 2

    operations = list(args.operation)
    operation = operations[0] if len(operations) == 1 else None
    paths = list(args.paths)
    payload = _develop_merge_payload(
        lane=args.lane,
        operation=operation,
        paths=paths,
        change_categories=args.change_category,
        external_gates=args.external_gate,
    )
    try:
        if args.path_file and paths:
            raise WorkflowError(
                "invalid_cli_arguments",
                "paths and --path-file cannot be used together",
            )
        if args.path_file:
            try:
                paths = args.path_file.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise WorkflowError("path_file_unavailable", str(exc)) from exc
            payload["paths"] = paths
        classify_develop_merge(
            args.lane,
            paths,
            operations,
            args.external_gate,
            change_categories=args.change_category,
        )
    except WorkflowError as exc:
        payload.update({
            "decision": "block",
            "detail": str(exc),
            "error_type": exc.error_type,
            "status": "blocked",
        })
        _print_develop_merge_payload(payload)
        return 2
    payload.update({"decision": "allow", "status": "ok"})
    _print_develop_merge_payload(payload)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["develop-merge-check"]:
        return _develop_merge_check_main(arguments[1:])
    return _legacy_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
