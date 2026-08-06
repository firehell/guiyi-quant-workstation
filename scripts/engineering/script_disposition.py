#!/usr/bin/env python3
"""Ordered disposition validator for tracked ``scripts/**`` paths.

Design baseline: 145 paths → 9 keep / 14 move / 122 replace-or-delete.
The validator regenerates ``git ls-files scripts/**`` and fails on drift,
overlap, or unmatched paths. Protected resources never enter deletion plans.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
import subprocess
from typing import Iterable, Sequence


DESIGN_BASELINE_TOTAL = 145
DESIGN_KEEP = 9
DESIGN_MOVE = 14
DESIGN_DELETE_OR_REPLACE = 122

FINAL_LAYOUT = (
    "scripts/dev/dev-down.sh",
    "scripts/dev/dev-healthcheck.sh",
    "scripts/dev/dev-status.sh",
    "scripts/dev/dev-up.sh",
    "scripts/engineering/personal_workflow.py",
    "scripts/engineering/preflight.ps1",
    "scripts/engineering/reference_closure.py",
    "scripts/engineering/release-tag.ps1",
    "scripts/engineering/replacement_gate.py",
    "scripts/engineering/repository_consistency.py",
    "scripts/engineering/runtime_dependency_inventory.py",
    "scripts/engineering/script_disposition.py",
    "scripts/engineering/secret-scan.ps1",
    "scripts/engineering/validate.ps1",
    "scripts/ops/linux/server-status.sh",
    "scripts/ops/macos/install-local-services.sh",
    "scripts/ops/macos/local-services-status.sh",
    "scripts/ops/macos/post-reboot-verify.sh",
    "scripts/ops/macos/rotate-local-service-logs.sh",
    "scripts/ops/macos/run-local-service.sh",
    "scripts/ops/macos/server-recover.sh",
    "scripts/ops/network/local-tunnel-healthcheck.sh",
    "scripts/ops/network/public-healthcheck.sh",
    "scripts/ops/network/tunnel-healthcheck.sh",
)

PROTECTED_PREFIXES = (
    ".kiro/specs/personal-development-mode",
    "data/",
    "receipts/",
    "reports/",
    "evidence/",
)


class Disposition(StrEnum):
    KEEP_IN_PLACE = "KEEP_IN_PLACE"
    MOVE = "MOVE"
    REPLACE_THEN_DELETE = "REPLACE_THEN_DELETE"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class DispositionRule:
    order: int
    name: str
    disposition: Disposition
    expected_count: int
    globs: tuple[str, ...] = ()
    exact: tuple[str, ...] = ()
    target_dir: str | None = None


MOVE_MAP = {
    "scripts/dev-down.sh": "scripts/dev/dev-down.sh",
    "scripts/dev-healthcheck.sh": "scripts/dev/dev-healthcheck.sh",
    "scripts/dev-status.sh": "scripts/dev/dev-status.sh",
    "scripts/dev-up.sh": "scripts/dev/dev-up.sh",
    "scripts/install-local-services.sh": "scripts/ops/macos/install-local-services.sh",
    "scripts/local-services-status.sh": "scripts/ops/macos/local-services-status.sh",
    "scripts/post-reboot-verify.sh": "scripts/ops/macos/post-reboot-verify.sh",
    "scripts/rotate-local-service-logs.sh": "scripts/ops/macos/rotate-local-service-logs.sh",
    "scripts/run-local-service.sh": "scripts/ops/macos/run-local-service.sh",
    "scripts/server-recover.sh": "scripts/ops/macos/server-recover.sh",
    "scripts/server-status.sh": "scripts/ops/linux/server-status.sh",
    "scripts/local-tunnel-healthcheck.sh": "scripts/ops/network/local-tunnel-healthcheck.sh",
    "scripts/public-healthcheck.sh": "scripts/ops/network/public-healthcheck.sh",
    "scripts/tunnel-healthcheck.sh": "scripts/ops/network/tunnel-healthcheck.sh",
}

RUNTIME_HISTORY_PATTERNS = (
    "*after-market*",
    "*after_market*",
    "*htdy*",
    "*s607*",
    "*live_signal*",
    "*live_t3*",
    "stage9_*",
)

EXACT_DATA_REPLACEMENTS = (
    "scripts/backfill_jm_price_tick.py",
    "scripts/data_stage_closure_audit.py",
    "scripts/derived_reference_inventory.py",
    "scripts/full_history_audit_v2_closure.py",
    "scripts/regenerate_jm_aggregated_bars.sh",
)

EXACT_PROFILE_COMPAT = (
    "scripts/consumer_contract_final_closeout_006.py",
    "scripts/profile_binding_rollout.py",
    "scripts/profile_binding_rollout_closeout_008b.py",
    "scripts/signal_review_lineage_gate_003.py",
    "scripts/stage13g_repair_report14_lineage.py",
)

EXACT_ONE_OFF = (
    "scripts/backtest_trust_audit.py",
    "scripts/export_su_bing_daily_score2of4_package.py",
    "scripts/export_su_bing_daily_trend_cross_score2_package.py",
    "scripts/export_su_bing_report_10_review_package.py",
    "scripts/oos_validation_run.py",
)

EXACT_OLD_RUNTIME_GATE = ("scripts/jm_eod_automation_gate.py",)

MACOS_EXACT = (
    "scripts/install-local-services.sh",
    "scripts/local-services-status.sh",
    "scripts/post-reboot-verify.sh",
    "scripts/rotate-local-service-logs.sh",
    "scripts/run-local-service.sh",
    "scripts/server-recover.sh",
)


def disposition_rules() -> tuple[DispositionRule, ...]:
    return (
        DispositionRule(
            order=1,
            name="engineering",
            disposition=Disposition.KEEP_IN_PLACE,
            expected_count=9,
            globs=("scripts/engineering/**",),
        ),
        DispositionRule(
            order=2,
            name="dev_scripts",
            disposition=Disposition.MOVE,
            expected_count=4,
            globs=("scripts/dev-*.sh",),
            target_dir="scripts/dev/",
        ),
        DispositionRule(
            order=3,
            name="macos_ops",
            disposition=Disposition.MOVE,
            expected_count=6,
            exact=MACOS_EXACT,
            target_dir="scripts/ops/macos/",
        ),
        DispositionRule(
            order=4,
            name="linux_ops",
            disposition=Disposition.MOVE,
            expected_count=1,
            exact=("scripts/server-status.sh",),
            target_dir="scripts/ops/linux/",
        ),
        DispositionRule(
            order=5,
            name="network_ops",
            disposition=Disposition.MOVE,
            expected_count=3,
            exact=(
                "scripts/local-tunnel-healthcheck.sh",
                "scripts/public-healthcheck.sh",
                "scripts/tunnel-healthcheck.sh",
            ),
            target_dir="scripts/ops/network/",
        ),
        DispositionRule(
            order=6,
            name="backup",
            disposition=Disposition.DELETE,
            expected_count=5,
            globs=("scripts/backup/**",),
        ),
        DispositionRule(
            order=7,
            name="restore",
            disposition=Disposition.DELETE,
            expected_count=3,
            globs=("scripts/restore/**",),
        ),
        DispositionRule(
            order=8,
            name="rqdata_family",
            disposition=Disposition.REPLACE_THEN_DELETE,
            expected_count=71,
            globs=("scripts/rqdata_*",),
        ),
        DispositionRule(
            order=9,
            name="runtime_history",
            disposition=Disposition.DELETE,
            expected_count=27,
            globs=RUNTIME_HISTORY_PATTERNS,
        ),
        DispositionRule(
            order=10,
            name="exact_data_replacements",
            disposition=Disposition.REPLACE_THEN_DELETE,
            expected_count=5,
            exact=EXACT_DATA_REPLACEMENTS,
        ),
        DispositionRule(
            order=11,
            name="profile_compat",
            disposition=Disposition.DELETE,
            expected_count=5,
            exact=EXACT_PROFILE_COMPAT,
        ),
        DispositionRule(
            order=12,
            name="one_off",
            disposition=Disposition.DELETE,
            expected_count=5,
            exact=EXACT_ONE_OFF,
        ),
        DispositionRule(
            order=13,
            name="old_runtime_gate",
            disposition=Disposition.DELETE,
            expected_count=1,
            exact=EXACT_OLD_RUNTIME_GATE,
        ),
    )


@dataclass(frozen=True, slots=True)
class DispositionAssignment:
    path: str
    disposition: Disposition
    rule_name: str
    target_path: str | None = None


@dataclass(frozen=True, slots=True)
class DispositionReport:
    inventory: tuple[str, ...]
    assignments: tuple[DispositionAssignment, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def list_tracked_scripts(repo_root: Path | None = None) -> tuple[str, ...]:
    root = repo_root or Path.cwd()
    completed = subprocess.run(
        ["git", "ls-files", "scripts/**"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
    return tuple(sorted(paths))


def classify_inventory(
    inventory: Sequence[str],
    *,
    rules: Sequence[DispositionRule] | None = None,
    enforce_design_totals: bool = True,
) -> DispositionReport:
    ordered_rules = tuple(rules or disposition_rules())
    remaining = list(inventory)
    assignments: list[DispositionAssignment] = []
    errors: list[str] = []

    if enforce_design_totals and len(inventory) != DESIGN_BASELINE_TOTAL:
        errors.append(
            f"baseline_drift: expected {DESIGN_BASELINE_TOTAL}, got {len(inventory)}"
        )

    for rule in ordered_rules:
        matched = [path for path in remaining if _matches_rule(path, rule)]
        if len(matched) != rule.expected_count and enforce_design_totals:
            errors.append(
                f"count_mismatch:{rule.name}: expected {rule.expected_count}, got {len(matched)}"
            )
        for path in matched:
            target = MOVE_MAP.get(path) if rule.disposition is Disposition.MOVE else None
            assignments.append(
                DispositionAssignment(
                    path=path,
                    disposition=rule.disposition,
                    rule_name=rule.name,
                    target_path=target,
                )
            )
        remaining = [path for path in remaining if path not in set(matched)]

    # Rule-overlap detection against the original inventory (not first-match residue).
    for path in inventory:
        claimants = [rule.name for rule in ordered_rules if _matches_rule(path, rule)]
        if len(claimants) > 1:
            errors.append(f"overlap:{path}:{'|'.join(claimants)}")

    # Assignment uniqueness (defensive).
    seen: dict[str, str] = {}
    for item in assignments:
        if item.path in seen:
            errors.append(f"assignment_dup:{item.path}:{seen[item.path]}|{item.rule_name}")
        seen[item.path] = item.rule_name

    if remaining:
        errors.append(f"unmatched:{','.join(remaining)}")

    keep = sum(1 for item in assignments if item.disposition is Disposition.KEEP_IN_PLACE)
    move = sum(1 for item in assignments if item.disposition is Disposition.MOVE)
    delete_or_replace = sum(
        1
        for item in assignments
        if item.disposition in {Disposition.DELETE, Disposition.REPLACE_THEN_DELETE}
    )
    if enforce_design_totals:
        if keep != DESIGN_KEEP:
            errors.append(f"keep_total:{keep}")
        if move != DESIGN_MOVE:
            errors.append(f"move_total:{move}")
        if delete_or_replace != DESIGN_DELETE_OR_REPLACE:
            errors.append(f"delete_or_replace_total:{delete_or_replace}")

    return DispositionReport(
        inventory=tuple(inventory),
        assignments=tuple(assignments),
        errors=tuple(errors),
    )


def validate_final_layout(inventory: Sequence[str]) -> DispositionReport:
    """Validate the tracked scripts left after the consolidation cutover."""
    actual = tuple(sorted(inventory))
    expected = tuple(sorted(FINAL_LAYOUT))
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    errors = tuple(
        [
            *(f"final_layout_missing:{path}" for path in missing),
            *(f"final_layout_unexpected:{path}" for path in unexpected),
        ]
    )
    return DispositionReport(inventory=actual, assignments=(), errors=errors)


def repository_deletion_plan(
    assignments: Sequence[DispositionAssignment],
) -> tuple[str, ...]:
    """Return repository source paths eligible for deletion after the replacement gate."""
    planned = []
    for item in assignments:
        if item.disposition not in {
            Disposition.DELETE,
            Disposition.REPLACE_THEN_DELETE,
        }:
            continue
        if is_protected_resource(item.path):
            continue
        planned.append(item.path)
    return tuple(planned)


def is_protected_resource(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith(PROTECTED_PREFIXES):
        return True
    if normalized == ".kiro/specs/personal-development-mode" or normalized.startswith(
        ".kiro/specs/personal-development-mode/"
    ):
        return True
    return False


def assert_protected_excluded(plan: Iterable[str]) -> None:
    leaked = [path for path in plan if is_protected_resource(path)]
    if leaked:
        raise ValueError(f"protected_resources_in_deletion_plan:{leaked}")


def _matches_rule(path: str, rule: DispositionRule) -> bool:
    name = Path(path).name
    for exact in rule.exact:
        if path == exact:
            return True
    for pattern in rule.globs:
        if "**" in pattern:
            # Directory-prefix style: scripts/engineering/**
            prefix = pattern[:-3] if pattern.endswith("/**") else pattern
            if path.startswith(prefix):
                return True
            continue
        if pattern.startswith("scripts/"):
            if fnmatch(path, pattern):
                return True
            continue
        # Basename-oriented runtime/history patterns.
        if fnmatch(name, pattern) or fnmatch(path, f"scripts/{pattern}"):
            return True
    return False


def main() -> int:
    report = validate_final_layout(list_tracked_scripts())
    for error in report.errors:
        print(error)
    if report.ok:
        print(f"ok final_layout={len(report.inventory)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
