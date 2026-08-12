"""``guiyi data`` 子命令 argparse 定义。

使用 JsonArgumentParser：用法错误转为 CliUsageError 而非打印 help 到 stderr，
便于 main 统一输出 JSON 错误载荷。
"""

from __future__ import annotations

import argparse
from typing import Any, NoReturn


class CliUsageError(ValueError):
    """CLI 参数/用法错误；code 供 exception_error_payload 识别为公开错误码。"""

    code = "CLI_ARGUMENT_INVALID"


class JsonArgumentParser(argparse.ArgumentParser):
    """将 argparse.error 转为 CliUsageError，避免非 JSON 的 stderr 输出。"""

    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)


def add_data_commands(
    commands: argparse._SubParsersAction[Any],
) -> None:
    """注册 data 下的 update、refresh、audit、after-market 子解析器。"""
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

    audit = commands.add_parser("audit")
    selector = audit.add_mutually_exclusive_group(required=True)
    selector.add_argument("--symbol")
    selector.add_argument("--universe", choices=("active",))
    audit.add_argument("--through")

    commands.add_parser("after-market")
