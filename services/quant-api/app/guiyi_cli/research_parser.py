"""``guiyi research`` read-only research command definitions."""

from __future__ import annotations

import argparse
from typing import Any


RESEARCH_COMMAND_NAMES = (
    "subing-calibration",
    "subing-lifecycle",
    "n-structure",
)


def add_research_commands(
    commands: argparse._SubParsersAction[Any],
) -> None:
    """Register the Historical-only research commands."""
    calibration = commands.add_parser("subing-calibration")
    calibration.add_argument("--phase", choices=("slope", "zero-band"), required=True)
    calibration.add_argument(
        "--mode", choices=("discovery", "validation"), required=True
    )
    calibration.add_argument("--frequency", choices=("5m", "15m", "1d"), required=True)
    calibration.add_argument("--since", required=True)
    calibration.add_argument("--through", required=True)
    calibration.add_argument("--symbol")
    calibration.add_argument("--slope-threshold-bps")
    calibration.add_argument("--slope-threshold-5m-bps")
    calibration.add_argument("--slope-threshold-15m-bps")
    calibration.add_argument("--zero-band-bps")

    lifecycle = commands.add_parser("subing-lifecycle")
    lifecycle.add_argument("--since", required=True)
    lifecycle.add_argument("--through", required=True)
    lifecycle.add_argument("--symbol")

    n_structure = commands.add_parser("n-structure")
    n_structure.add_argument("--since", required=True)
    n_structure.add_argument("--through", required=True)
    n_structure.add_argument("--symbol")

    if tuple(commands.choices) != RESEARCH_COMMAND_NAMES:
        raise RuntimeError("CLI_RESEARCH_COMMAND_REGISTRY_INVALID")
