#!/usr/bin/env python3
"""Render validated, read-only Lean Matrix contracts from JSON input."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# The CLI's contract is stdout/stderr only. Prevent Python's import machinery
# from creating an ignored __pycache__ beside repository modules.
sys.dont_write_bytecode = True

from lean_matrix.charter import SCHEMA_VERSION, render_charter
from lean_matrix.errors import LeanMatrixError


class LeanMatrixArgumentParser(argparse.ArgumentParser):
    """Route invalid command syntax through the stable JSON error contract."""

    def error(self, message: str) -> None:
        raise LeanMatrixError("invalid_cli_arguments", message)


def _read_input(input_name: str) -> object:
    try:
        if input_name == "-":
            binary_stdin = getattr(sys.stdin, "buffer", None)
            content = binary_stdin.read().decode("utf-8") if binary_stdin else sys.stdin.read()
        else:
            content = Path(input_name).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LeanMatrixError("invalid_input_encoding", "input must be UTF-8 encoded JSON") from exc
    except OSError as exc:
        raise LeanMatrixError("input_file_unavailable", str(exc)) from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LeanMatrixError("invalid_json", exc.msg) from exc


def render(raw: object) -> dict[str, object]:
    """Backward-compatible import alias for the schema-v1 Charter renderer."""
    return render_charter(raw)


def _blocked(error: LeanMatrixError) -> int:
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "error_type": error.error_type,
        "detail": error.detail,
    }), file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = LeanMatrixArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=LeanMatrixArgumentParser)
    charter = subcommands.add_parser("charter")
    charter.add_argument("--input", required=True)
    charter.add_argument("--format", required=True, choices=("markdown", "json"))
    try:
        args = parser.parse_args(argv)
        result = render_charter(_read_input(args.input))
    except LeanMatrixError as exc:
        return _blocked(exc)
    if args.format == "markdown":
        print(result["charter_markdown"], end="")
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
