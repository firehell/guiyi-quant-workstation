"""``guiyi data`` 子命令 argparse 定义。

使用 JsonArgumentParser：用法错误转为 CliUsageError 而非打印 help 到 stderr，
便于 main 统一输出 JSON 错误载荷。
"""

from __future__ import annotations

import argparse
from datetime import date
import re
from typing import Any, NoReturn


class CliUsageError(ValueError):
    """CLI 参数/用法错误；code 供 exception_error_payload 识别为公开错误码。"""

    code = "CLI_ARGUMENT_INVALID"


class JsonArgumentParser(argparse.ArgumentParser):
    """将 argparse.error 转为 CliUsageError，避免非 JSON 的 stderr 输出。"""

    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)

    def parse_args(self, args=None, namespace=None):
        result = super().parse_args(args, namespace)
        if getattr(result, "data_command", None) == "au-calendar-correction":
            if re.fullmatch(r"[0-9a-f]{64}", result.expected_evidence_sha256) is None:
                self.error("exact evidence hash required")
            if result.apply:
                if not isinstance(result.expected_plan_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", result.expected_plan_sha256) is None:
                    self.error("apply requires exact plan hash")
            elif result.expected_plan_sha256 is not None:
                self.error("dry-run does not accept apply hash")
        if getattr(result, "data_command", None) == "metadata-repair":
            if result.phase == "plan":
                if not result.targets or result.plan or result.snapshot or result.apply or result.expected_plan_sha256 or result.expected_snapshot_sha256:
                    self.error("plan requires only targets and optional classification")
            else:
                if result.targets or result.classification or result.evidence_sources or result.exchange_universes or result.exchange_inventory_evidence or not result.apply:
                    self.error("fetch/apply require an explicit phase and --apply")
                if not isinstance(result.expected_plan_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", result.expected_plan_sha256) is None:
                    self.error("expected plan hash required")
                if result.phase == "fetch" and (not result.plan or result.snapshot or result.expected_snapshot_sha256):
                    self.error("fetch requires plan only")
                if result.phase == "apply" and (result.plan or not result.snapshot or not isinstance(result.expected_snapshot_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", result.expected_snapshot_sha256) is None):
                    self.error("apply requires snapshot and its exact hash")
        if getattr(result, "data_command", None) == "session-anchor-repair":
            phase = result.phase
            has_any_path = bool(result.shadow_root or result.manifest)
            has_all_paths = bool(result.shadow_root and result.manifest)
            if phase == "plan" and (has_any_path or result.apply):
                self.error("plan does not accept mutation arguments")
            if phase in {"prepare", "publish"} and (
                not has_all_paths or not result.apply
            ):
                self.error("prepare/publish require paths and --apply")
        if getattr(result, "data_command", None) == "contract-warmup":
            expected_hash = result.expected_plan_sha256
            if not result.apply and expected_hash is not None:
                self.error("dry-run does not accept an expected plan hash")
            if result.apply and (
                not isinstance(expected_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            ):
                self.error("apply requires a lowercase SHA-256 plan hash")
        if getattr(result, "data_command", None) == "daily-recovery":
            expected_hash = result.expected_plan_sha256
            if (
                re.fullmatch(r"[0-9a-f]{40}", result.runtime_commit) is None
                or re.fullmatch(r"[0-9a-f]{64}", result.expected_status_sha256)
                is None
            ):
                self.error("exact runtime identity required")
            if not result.apply and expected_hash is not None:
                self.error("dry-run does not accept an expected plan hash")
            if result.apply and (
                not isinstance(expected_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            ):
                self.error("apply requires a lowercase SHA-256 plan hash")
        if getattr(result, "data_command", None) == "current-day-metadata-recovery":
            exact_identity = (
                re.fullmatch(r"[0-9a-f]{40}", result.runtime_commit) is not None
                and re.fullmatch(r"[0-9a-f]{64}", result.expected_status_sha256)
                is not None
            )
            snapshot_hash = result.expected_snapshot_sha256
            plan_hash = result.expected_plan_sha256
            valid_snapshot_hash = (
                isinstance(snapshot_hash, str)
                and re.fullmatch(r"[0-9a-f]{64}", snapshot_hash) is not None
            )
            valid_plan_hash = (
                isinstance(plan_hash, str)
                and re.fullmatch(r"[0-9a-f]{64}", plan_hash) is not None
            )
            if not exact_identity:
                self.error("exact runtime identity required")
            if result.phase == "capture":
                if not result.apply or result.snapshot or snapshot_hash or plan_hash:
                    self.error("capture requires only explicit --apply")
            elif result.phase == "plan":
                if result.apply or not result.snapshot or not valid_snapshot_hash or plan_hash:
                    self.error("plan requires exact snapshot only")
            elif (
                not result.apply
                or not result.snapshot
                or not valid_snapshot_hash
                or not valid_plan_hash
            ):
                self.error("apply requires exact snapshot and plan hashes")
        if getattr(result, "data_command", None) == "compatible-recovery-proof":
            if (
                re.fullmatch(r"[0-9a-f]{40}", result.candidate_commit) is None
                or re.fullmatch(r"[0-9a-f]{40}", result.runtime_commit) is None
                or re.fullmatch(r"[0-9a-f]{64}", result.expected_status_sha256)
                is None
                or re.fullmatch(
                    r"[0-9a-f]{64}",
                    result.expected_operational_products_sha256,
                )
                is None
            ):
                self.error("exact candidate and runtime identities required")
        return result


def add_data_commands(
    commands: argparse._SubParsersAction[Any],
) -> None:
    """注册 data 下的维护与不可变席位快照子解析器。"""
    update = commands.add_parser("update")
    selector = update.add_mutually_exclusive_group(required=True)
    selector.add_argument("--symbol")
    selector.add_argument("--universe", choices=("active",))
    update.add_argument("--since")
    update.add_argument("--through")
    update.add_argument("--apply", action="store_true")

    recovery = commands.add_parser("daily-recovery", allow_abbrev=False)
    recovery.add_argument("--runtime-root", required=True)
    recovery.add_argument("--runtime-commit", required=True)
    recovery.add_argument("--expected-status-sha256", required=True)
    recovery.add_argument("--through", type=date.fromisoformat, required=True)
    recovery.add_argument("--expected-plan-sha256")
    recovery.add_argument("--apply", action="store_true")

    current_metadata = commands.add_parser(
        "current-day-metadata-recovery", allow_abbrev=False
    )
    current_metadata.add_argument(
        "--phase", required=True, choices=("capture", "plan", "apply")
    )
    current_metadata.add_argument("--runtime-root", required=True)
    current_metadata.add_argument("--runtime-commit", required=True)
    current_metadata.add_argument("--expected-status-sha256", required=True)
    current_metadata.add_argument("--trading-day", type=date.fromisoformat, required=True)
    current_metadata.add_argument("--snapshot")
    current_metadata.add_argument("--expected-snapshot-sha256")
    current_metadata.add_argument("--expected-plan-sha256")
    current_metadata.add_argument("--apply", action="store_true")

    compatible_recovery = commands.add_parser(
        "compatible-recovery-proof", allow_abbrev=False
    )
    compatible_recovery.add_argument("--candidate-root", required=True)
    compatible_recovery.add_argument("--candidate-commit", required=True)
    compatible_recovery.add_argument("--runtime-root", required=True)
    compatible_recovery.add_argument("--runtime-commit", required=True)
    compatible_recovery.add_argument("--expected-status-sha256", required=True)
    compatible_recovery.add_argument(
        "--expected-operational-products-sha256", required=True
    )

    refresh = commands.add_parser("refresh")
    refresh.add_argument("--symbol", required=True)
    refresh.add_argument("--since", required=True)
    refresh.add_argument("--through", required=True)
    refresh.add_argument("--apply", action="store_true")

    contract_warmup = commands.add_parser("contract-warmup", allow_abbrev=False)
    contract_warmup.add_argument("--symbol", required=True)
    contract_warmup.add_argument("--contract", required=True)
    contract_warmup.add_argument("--through", required=True)
    contract_warmup.add_argument("--frequency", choices=("1d", "1w", "15m", "60m"))
    contract_warmup.add_argument("--expected-plan-sha256")
    contract_warmup.add_argument("--apply", action="store_true")

    audit = commands.add_parser("audit")
    selector = audit.add_mutually_exclusive_group(required=True)
    selector.add_argument("--symbol")
    selector.add_argument("--universe", choices=("active", "operational"))
    audit.add_argument("--through")
    audit.add_argument("--progress", action="store_true")

    readiness = commands.add_parser("newow-readiness", allow_abbrev=False)
    selector = readiness.add_mutually_exclusive_group(required=True)
    selector.add_argument("--symbol")
    selector.add_argument("--universe", choices=("active",))
    readiness.add_argument("--as-of", required=True)
    readiness.add_argument("--matrix", action="store_true")
    readiness.add_argument("--max-work", type=int, default=10000)
    readiness.add_argument("--timeout-seconds", type=int, default=300)

    commands.add_parser("after-market")
    commands.add_parser("weekly-audit")
    closeout = commands.add_parser("close-interrupted-after-market", allow_abbrev=False)
    closeout.add_argument("--runtime-root", required=True)
    closeout.add_argument("--runtime-commit", required=True)
    closeout.add_argument("--expected-status-sha256", required=True)
    closeout.add_argument("--apply", action="store_true")

    correction = commands.add_parser("au-calendar-correction", allow_abbrev=False)
    correction.add_argument("--evidence", required=True)
    correction.add_argument("--expected-evidence-sha256", required=True)
    correction.add_argument("--expected-plan-sha256")
    correction.add_argument("--apply", action="store_true")

    metadata = commands.add_parser("metadata-repair", allow_abbrev=False)
    metadata.add_argument("--phase", choices=("plan", "fetch", "apply"), default="plan")
    metadata.add_argument("--targets")
    metadata.add_argument("--classification")
    metadata.add_argument("--evidence-sources")
    metadata.add_argument("--exchange-universes")
    metadata.add_argument("--exchange-inventory-evidence")
    metadata.add_argument("--plan")
    metadata.add_argument("--snapshot")
    metadata.add_argument("--expected-plan-sha256")
    metadata.add_argument("--expected-snapshot-sha256")
    metadata.add_argument("--apply", action="store_true")

    repair = commands.add_parser("session-anchor-repair", allow_abbrev=False)
    repair.add_argument("--phase", required=True, choices=("plan", "prepare", "publish"))
    repair.add_argument("--shadow-root")
    repair.add_argument("--manifest")
    repair.add_argument("--apply", action="store_true")
