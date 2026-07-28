#!/usr/bin/env python3
"""Approval-C2-bound, one-day WeCom dispatcher (never global autosend)."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "quant-api"))
sys.path.insert(0, str(ROOT / "packages" / "quant-core"))

from app.core.env import load_project_env  # noqa: E402
from app.services.htdy_s6_10_one_day_notifications import (  # noqa: E402
    dispatch_bounded_one_day,
)
from app.services.htdy_s6_10_one_day_runtime_gate import (  # noqa: E402
    build_runtime_gate,
)
from app.signal.stage9_wechat_delivery import (  # noqa: E402
    Stage9WechatDeliveryService,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--approval-hash", required=True)
    parser.add_argument("--confirm-send", action="store_true")
    args = parser.parse_args()
    if not args.confirm_send:
        print(json.dumps({"status": "blocked", "reason": "--confirm-send required"}))
        return 2
    load_project_env()
    from app.db.session import SessionLocal
    from app.queue import get_redis_connection

    if _enabled("GUIYI_WECHAT_AUTOSEND_ENABLED"):
        print(json.dumps({"status": "blocked", "reason": "global autosend must remain false"}))
        return 2
    if not _enabled("GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED"):
        print(json.dumps({"status": "blocked", "reason": "bounded dispatcher disabled"}))
        return 2
    parent = json.loads(args.parent.read_text(encoding="utf-8"))
    trading_day = date.fromisoformat(parent["trading_days"][0])
    window_end = datetime.combine(trading_day, time(16, 0), tzinfo=SHANGHAI)
    if datetime.now(SHANGHAI) >= window_end:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": "one_day_window_ended",
                    "trading_day": trading_day.isoformat(),
                }
            )
        )
        return 0
    gate = build_runtime_gate(
        parent_packet_path=args.parent,
        approval_hash=args.approval_hash,
        environ=os.environ,
    )
    redis = get_redis_connection()
    redis_ready = bool(redis.ping())
    with SessionLocal() as session:
        gate(session, phase="verify")
        service = Stage9WechatDeliveryService(session, environ=os.environ)
        result = dispatch_bounded_one_day(
            session,
            delivery_service=service,
            trading_day=trading_day,
            window_end=window_end,
            parent_hash=args.approval_hash,
            global_autosend_enabled=False,
            redis_ready=redis_ready,
        )
        session.commit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


if __name__ == "__main__":
    raise SystemExit(main())
