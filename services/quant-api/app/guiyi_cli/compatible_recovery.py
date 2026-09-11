"""Read-only proof that a candidate can retain an exact schema-v5 Runtime binding."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.market_data.closeout_binding import RuntimeDataBinding


def run_compatible_recovery_proof(args: argparse.Namespace) -> dict[str, object]:
    """Bind the supervised Runtime once and emit only a bounded public proof."""
    binding = RuntimeDataBinding(
        Path(args.runtime_root),
        args.runtime_commit,
        args.expected_status_sha256,
    )
    return binding.compatible_recovery_proof(
        candidate_root=Path(args.candidate_root),
        candidate_commit=args.candidate_commit,
        expected_operational_products_sha256=(
            args.expected_operational_products_sha256
        ),
    )
