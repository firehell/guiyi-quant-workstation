#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
for root in (API_ROOT, CORE_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or verify a create-only HTDY realtime observation approval packet."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--s6-08-receipt", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--enable-wechat", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--packet", type=Path, required=True)
    verify.add_argument("--approval-hash", required=True)
    verify.add_argument("--alerts-enabled", action="store_true")
    verify.add_argument("--wechat-enabled", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from app.services.htdy_realtime_alert_gate import (
        build_approval_packet,
        collect_current_facts,
        load_packet,
        verify_approval_packet,
    )

    if args.command == "generate":
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            facts = collect_current_facts(
                project_root=PROJECT_ROOT,
                s6_08_receipt_path=args.s6_08_receipt,
                session=session,
            )
            session.rollback()
        packet = build_approval_packet(
            current_facts=facts,
            enable_wechat=args.enable_wechat,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(packet, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        print(
            json.dumps(
                {
                    "status": "created",
                    "output": str(args.output.resolve()),
                    "packet_hash": packet["packet_hash"],
                    "contains_secrets": False,
                },
                ensure_ascii=False,
            )
        )
        return 0

    packet = load_packet(args.packet)
    receipt_path = Path(str((packet.get("prerequisite") or {}).get("receipt_path") or ""))
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        facts = collect_current_facts(
            project_root=PROJECT_ROOT,
            s6_08_receipt_path=receipt_path,
            session=session,
        )
        verify_approval_packet(
            packet,
            approval_hash=args.approval_hash,
            current_facts=facts,
            alerts_enabled=args.alerts_enabled,
            wechat_enabled=args.wechat_enabled,
        )
        session.rollback()
    print(json.dumps({"status": "verified", "packet_hash": args.approval_hash}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
