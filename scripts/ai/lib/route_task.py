#!/usr/bin/env python3
"""Deterministic model-profile router for Guiyi workstation TASK files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from task_meta import load_task_metadata


VALID_STAGES = {"plan", "dev", "fix", "test", "review", "result"}
TIER_RANK = {"fast": 0, "standard": 1, "deep": 2, "critical": 3}
PROFILE_BY_TIER = {
    "fast": {
        "profile": "guiyi-fast",
        "model_family": "Luna",
        "reasoning_effort": "low",
    },
    "standard": {
        "profile": "guiyi-standard",
        "model_family": "Terra",
        "reasoning_effort": "medium",
    },
    "deep": {
        "profile": "guiyi-deep",
        "model_family": "Sol",
        "reasoning_effort": "high",
    },
    "critical": {
        "profile": "guiyi-critical",
        "model_family": "Sol",
        "reasoning_effort": "xhigh",
    },
}

CRITICAL_PATTERNS = {
    "critical_quant_core": r"packages/quant-core",
    "critical_indicator_semantics": r"\b(indicator kernel|指标内核|seed|warm[- ]?up|nan|smoothing|平滑)\b",
    "critical_strategy_realtime_consistency": (
        r"\b(strategy signal|策略信号|仓位|position|backtest.*realtime|"
        r"实时.*回测|撮合|look[- ]?ahead|未来函数)\b"
    ),
    "critical_database_schema": r"\b(postgresql schema|db schema|database schema|数据迁移|alembic|migration)\b",
    "critical_jm_realtime_1m": r"\b(jm.*实时.*1m|jm.*1m.*核心|live.*1m|realtime.*1m)\b",
    "critical_production_security_trading": (
        r"\b(production|生产环境|security|安全|secret|token|password|api key|"
        r"交易执行|实盘|下单|broker|ctp)\b"
    ),
}

DEEP_PATTERNS = {
    "deep_runtime": r"\b(runtime|scheduler|调度|concurrency|并发|recovery|恢复|worker|daemon)\b",
    "deep_refactor": r"\b(refactor|重构|大范围)\b",
    "deep_complex_test_failure": r"\b(complex test failure|复杂测试失败|flaky|回归失败)\b",
}

FAST_PATTERNS = {
    "fast_docs": r"\b(docs?|documentation|文档|readme)\b",
    "fast_format_log": r"\b(format|格式|日志|log)\b",
    "fast_simple_ui": r"\b(simple ui|简单 ui|文案|样式|布局)\b",
}

MAJOR_ROOTS = {"apps", "services", "packages", "scripts", "deploy", "configs"}


def _task_text(task_file: str | Path) -> str:
    return Path(task_file).read_text(encoding="utf-8")


def _search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.I | re.S) is not None


def _path_roots(paths: list[str]) -> set[str]:
    roots: set[str] = set()
    for path in paths:
        root = path.strip().split("/", 1)[0]
        if root in MAJOR_ROOTS:
            roots.add(root)
    return roots


def _automatic_tier(metadata: dict[str, Any], text: str) -> tuple[str, list[str]]:
    haystack = "\n".join(
        [
            text,
            "\n".join(metadata.get("allowed_paths", [])),
            "\n".join(metadata.get("forbidden_paths", [])),
        ]
    )
    reason_codes: list[str] = []

    for code, pattern in CRITICAL_PATTERNS.items():
        if _search(pattern, haystack):
            reason_codes.append(code)
    if metadata.get("routing", {}).get("requested_tier") == "critical":
        reason_codes.append("requested_tier_critical")
    if any(metadata.get("permissions", {}).values()):
        reason_codes.append("critical_sensitive_permission_requested")
    if reason_codes:
        return "critical", sorted(set(reason_codes))

    for code, pattern in DEEP_PATTERNS.items():
        if _search(pattern, haystack):
            reason_codes.append(code)

    roots = _path_roots(metadata.get("allowed_paths", []))
    if len(roots) >= 2:
        reason_codes.append("deep_cross_major_modules")
    if len(metadata.get("allowed_paths", [])) >= 6:
        reason_codes.append("deep_many_expected_files")
    if metadata.get("work_level") == "L2":
        reason_codes.append("deep_l2_delivery")
    if reason_codes:
        return "deep", sorted(set(reason_codes))

    if metadata.get("work_level") == "L0":
        return "fast", ["fast_l0"]
    fast_reasons = [code for code, pattern in FAST_PATTERNS.items() if _search(pattern, haystack)]
    if fast_reasons and len(metadata.get("allowed_paths", [])) <= 3:
        return "fast", sorted(set(fast_reasons + ["fast_low_file_count"]))

    return "standard", ["standard_default"]


def _apply_requested_tier(
    automatic_tier: str, metadata: dict[str, Any], reason_codes: list[str]
) -> tuple[str, list[str], list[str]]:
    warnings: list[str] = []
    requested = metadata.get("routing", {}).get("requested_tier", "auto")
    if requested == "auto":
        return automatic_tier, reason_codes, warnings

    if TIER_RANK[requested] > TIER_RANK[automatic_tier]:
        return requested, sorted(set(reason_codes + [f"requested_tier_{requested}"])), warnings

    if TIER_RANK[requested] < TIER_RANK[automatic_tier]:
        warnings.append(f"requested_tier_{requested}_below_required_{automatic_tier}")
        reason_codes = sorted(set(reason_codes + ["requested_tier_below_required"]))
    return automatic_tier, reason_codes, warnings


def _stage_policy(stage: str) -> tuple[str, str]:
    if stage in {"plan", "review"}:
        return "read-only", "never"
    if stage in {"dev", "fix"}:
        return "workspace-write", "on-request"
    return "deterministic_no_model", "deterministic_no_model"


def route_task(task_file: str | Path, stage: str) -> dict[str, Any]:
    stage = stage.strip().lower()
    if stage not in VALID_STAGES:
        raise ValueError(f"stage must be one of: {', '.join(sorted(VALID_STAGES))}")

    metadata = load_task_metadata(task_file)
    text = _task_text(task_file)
    automatic, reason_codes = _automatic_tier(metadata, text)
    resolved_tier, reason_codes, request_warnings = _apply_requested_tier(
        automatic, metadata, reason_codes
    )
    sandbox_mode, approval_policy = _stage_policy(stage)
    profile = PROFILE_BY_TIER[resolved_tier].copy()
    warnings = list(metadata.get("warnings", [])) + request_warnings

    if stage in {"test", "result"}:
        profile = {
            "profile": "deterministic_no_model",
            "model_family": "deterministic_no_model",
            "reasoning_effort": "deterministic_no_model",
        }
        reason_codes = sorted(set(reason_codes + ["deterministic_no_model_stage"]))

    permissions = metadata.get("permissions", {})
    if permissions.get("production_access_allowed"):
        warnings.append("production_access_not_granted_by_router")
    if permissions.get("push_allowed") or permissions.get("merge_allowed") or permissions.get("deploy_allowed"):
        warnings.append("git_or_deploy_permission_not_granted_by_router")

    return {
        "task_id": metadata["task_id"],
        "stage": stage,
        "resolved_tier": resolved_tier,
        "profile": profile["profile"],
        "model_family": profile["model_family"],
        "reasoning_effort": profile["reasoning_effort"],
        "sandbox_mode": sandbox_mode,
        "approval_policy": approval_policy,
        "reason_codes": sorted(set(reason_codes)),
        "external_review_required": resolved_tier == "critical",
        "allow_auto_escalation": bool(metadata.get("routing", {}).get("allow_auto_escalation", True)),
        "max_auto_escalations": int(metadata.get("routing", {}).get("max_auto_escalations", 1)),
        "warnings": sorted(set(warnings)),
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route a TASK to a deterministic model profile.")
    parser.add_argument("task_file")
    parser.add_argument("stage", choices=sorted(VALID_STAGES))
    parser.add_argument("--json", action="store_true", help="Print stable JSON output.")
    parser.add_argument("--explain", action="store_true", help="Append a human-readable explanation.")
    args = parser.parse_args(argv)

    try:
        result = route_task(args.task_file, args.stage)
    except (OSError, ValueError) as exc:
        print(f"route_task failed: {exc}", file=sys.stderr)
        return 1

    _print_json(result)
    if args.explain:
        print(
            "\n"
            f"tier={result['resolved_tier']} profile={result['profile']} "
            f"reasons={','.join(result['reason_codes'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
