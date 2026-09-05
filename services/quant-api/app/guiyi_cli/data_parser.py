"""``guiyi data`` 子命令 argparse 定义。

使用 JsonArgumentParser：用法错误转为 CliUsageError 而非打印 help 到 stderr，
便于 main 统一输出 JSON 错误载荷。
"""

from __future__ import annotations

import argparse
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

    refresh = commands.add_parser("refresh")
    refresh.add_argument("--symbol", required=True)
    refresh.add_argument("--since", required=True)
    refresh.add_argument("--through", required=True)
    refresh.add_argument("--apply", action="store_true")

    contract_warmup = commands.add_parser("contract-warmup", allow_abbrev=False)
    contract_warmup.add_argument("--symbol", required=True)
    contract_warmup.add_argument("--contract", required=True)
    contract_warmup.add_argument("--through", required=True)
    contract_warmup.add_argument("--expected-plan-sha256")
    contract_warmup.add_argument("--apply", action="store_true")

    audit = commands.add_parser("audit")
    selector = audit.add_mutually_exclusive_group(required=True)
    selector.add_argument("--symbol")
    selector.add_argument("--universe", choices=("active",))
    audit.add_argument("--through")
    audit.add_argument("--progress", action="store_true")

    commands.add_parser("after-market")

    repair = commands.add_parser("session-anchor-repair", allow_abbrev=False)
    repair.add_argument("--phase", required=True, choices=("plan", "prepare", "publish"))
    repair.add_argument("--shadow-root")
    repair.add_argument("--manifest")
    repair.add_argument("--apply", action="store_true")
