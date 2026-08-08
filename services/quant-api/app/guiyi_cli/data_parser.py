from __future__ import annotations

import argparse
from typing import Any, NoReturn


class CliUsageError(ValueError):
    code = "CLI_ARGUMENT_INVALID"


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)


def add_data_commands(
    commands: argparse._SubParsersAction[Any],
) -> None:
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
    audit.add_argument("--universe", choices=("active",), required=True)
