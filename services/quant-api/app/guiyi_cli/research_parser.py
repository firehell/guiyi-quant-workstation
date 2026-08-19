"""``guiyi research`` read-only research command definitions."""

from __future__ import annotations

import argparse
from typing import Any


def add_research_commands(
    commands: argparse._SubParsersAction[Any],
) -> None:
    """Register the two Historical-only SuBing research commands."""
    calibration = commands.add_parser("subing-calibration")
    calibration.add_argument("--phase", choices=("slope", "zero-band"), required=True)
    calibration.add_argument("--mode", choices=("discovery", "validation"), required=True)
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
