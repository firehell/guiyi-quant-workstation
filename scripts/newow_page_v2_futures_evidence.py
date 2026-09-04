#!/usr/bin/env python3
"""Owner-gated Newow page-v2 real-futures evidence discovery entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the bounded read-only Newow futures coverage discovery."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser(
        "discover",
        help="Owner-gated read-only Catalog and Canonical coverage discovery.",
    )
    discover.add_argument("--base-sha", required=True)
    discover.add_argument("--owner-approved-run-id", required=True)
    discover.add_argument("--frequencies", nargs=3, required=True)
    discover.add_argument("--minimum-rollovers", type=int, required=True)
    discover.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        from app.market_data.newow.futures_evidence_discovery import run_discovery

        return run_discovery(
            base_sha=args.base_sha,
            owner_approved_run_id=args.owner_approved_run_id,
            frequencies=tuple(args.frequencies),
            minimum_rollovers=args.minimum_rollovers,
            output_dir=args.output,
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
