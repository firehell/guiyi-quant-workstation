#!/usr/bin/env python3
"""Build a deterministic, non-applying SuBing D1 quality publication plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.market_data.subing_d1_quality_plan import build_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--impact", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source-complete", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = build_plan(
        json.loads(args.impact.read_text()),
        json.loads(args.evidence.read_text()),
        json.loads(args.source_complete.read_text()),
        excluded_target_count=40,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "mode": plan["mode"], "plan_sha256": plan["plan_sha256"],
        "products": plan["product_count"],
        "target_partitions": plan["target_partition_count"],
        "provider_request_budget": plan["provider_request_budget"],
        "production_writes": plan["production_writes"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
