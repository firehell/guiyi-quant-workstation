from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a read-only hash-bound JM T3 approval packet")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.live_t3_gate import EXECUTION_FLAGS, build_approval_packet, collect_bound_facts

    with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        facts = collect_bound_facts(
            session,
            project_root=PROJECT_ROOT,
            execution_flags=EXECUTION_FLAGS,
        )
        session.rollback()
    packet = build_approval_packet(facts)
    output = args.output.resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite approval packet: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "approval_required", "packet": str(output), "packet_hash": packet["packet_hash"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
