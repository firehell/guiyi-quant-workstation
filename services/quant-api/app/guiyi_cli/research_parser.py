"""``guiyi research`` read-only research command definitions."""

from __future__ import annotations

import argparse
from typing import Any


RESEARCH_COMMAND_NAMES = (
    "subing-calibration",
    "subing-lifecycle",
    "n-structure",
    "jdj-1m",
    "candidate-validation",
    "candidate-robustness",
    "candidate-dossier",
    "candidate-relationships",
    "main-force-mirror-v2",
    "main-force-mirror-diagnostic",
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

    jdj = commands.add_parser("jdj-1m")
    jdj.add_argument(
        "--candidate",
        choices=(
            "jdj_trend_follow_1m_candidate_v1",
            "jdj_trend_reentry_6_1m_candidate_v1",
            "jdj_key_level_breakout_1m_candidate_v1",
        ),
        required=True,
    )
    jdj.add_argument("--symbol", required=True)
    jdj.add_argument("--since", required=True)
    jdj.add_argument("--through", required=True)

    candidate = commands.add_parser("candidate-validation")
    candidate.add_argument(
        "--candidate",
        choices=(
            "subing_lifecycle_v2_candidate_v1",
            "n_structure_5m_candidate_v1",
            "jdj_trend_follow_1m_candidate_v1",
            "jdj_trend_reentry_6_1m_candidate_v1",
            "jdj_key_level_breakout_1m_candidate_v1",
        ),
        required=True,
    )
    candidate.add_argument(
        "--protocol",
        choices=(
            "candidate_validation_v1",
            "n_structure_validation_v1",
            "jdj_candidate_validation_v1",
        ),
        required=True,
    )
    candidate.add_argument("--symbol", required=True)
    candidate.add_argument("--through", required=True)

    robustness = commands.add_parser("candidate-robustness")
    robustness.add_argument(
        "--protocol",
        choices=(
            "multi_candidate_robustness_v1",
            "jdj_active60_robustness_v1",
        ),
        required=True,
    )

    dossier = commands.add_parser("candidate-dossier")
    dossier.add_argument(
        "--protocol",
        choices=("five_candidate_research_dossier_v1",),
        required=True,
    )

    relationships = commands.add_parser("candidate-relationships")
    relationships.add_argument(
        "--protocol",
        choices=("five_candidate_relationship_topology_v1",),
        required=True,
    )

    mirror = commands.add_parser("main-force-mirror-v2")
    mirror.add_argument("--symbol", required=True)
    mirror.add_argument(
        "--series-kind",
        choices=("actual_dominant", "contract"),
        required=True,
    )
    mirror.add_argument("--contract")
    mirror.add_argument("--frequency", choices=("60m",), required=True)
    mirror.add_argument("--since", required=True)
    mirror.add_argument("--through", required=True)
    mirror.add_argument("--forensic", action="store_true")

    diagnostic = commands.add_parser("main-force-mirror-diagnostic")
    diagnostic.add_argument(
        "--protocol",
        choices=("main_force_mirror_diagnostic_phase_a_v1",),
        required=True,
    )

    if tuple(commands.choices) != RESEARCH_COMMAND_NAMES:
        raise RuntimeError("CLI_RESEARCH_COMMAND_REGISTRY_INVALID")
