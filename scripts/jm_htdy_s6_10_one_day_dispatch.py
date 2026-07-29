#!/usr/bin/env python3
"""Approval-C2-bound, one-day WeCom dispatcher (never global autosend)."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "quant-api"))
sys.path.insert(0, str(ROOT / "packages" / "quant-core"))

from app.core.env import load_project_env  # noqa: E402
from app.services.htdy_s6_10_one_day_notifications import (  # noqa: E402
    dispatch_bounded_one_day,
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
    is_long_running = (
        parent.get("schema_version") == 1
        and parent.get("request_type")
        == "htdy_s6_10_approval_d_no_code_promotion"
    )
    trading_day = None
    allowed_bucket_ends = None
    if is_long_running:
        from app.services.htdy_s6_10_long_running_runtime_gate import (
            build_runtime_gate,
        )
    elif parent.get("schema_version") in {6, 7}:
        trading_day = date.fromisoformat(parent["trading_days"][0])
        from app.services.htdy_s6_10_remaining_window_runtime_gate import (
            build_runtime_gate,
        )

        activation_path = Path(
            str(os.environ.get("GUIYI_HTDY_S610_ACTIVATION_RECEIPT") or "")
        )
        activation = json.loads(
            activation_path.read_text(encoding="utf-8")
        )
        allowed_bucket_ends = {
            datetime.fromisoformat(value)
            for value in activation["expected_bucket_ends"]
        }
        window_end = datetime.fromisoformat(parent["window_end"])
        stopped_reason = "remaining_window_ended"
    else:
        trading_day = date.fromisoformat(parent["trading_days"][0])
        from app.services.htdy_s6_10_one_day_runtime_gate import (
            build_runtime_gate,
        )

        window_end = datetime.combine(
            trading_day,
            time(16, 0),
            tzinfo=SHANGHAI,
        )
        stopped_reason = "one_day_window_ended"
    if (
        not is_long_running
        and datetime.now(SHANGHAI) >= window_end
    ):
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": stopped_reason,
                    "trading_day": trading_day.isoformat(),
                }
            )
        )
        return 0
    gate = _build_gate(
        builder=build_runtime_gate,
        is_long_running=is_long_running,
        packet_path=args.parent,
        approval_hash=args.approval_hash,
        environ=os.environ,
    )
    with SessionLocal() as session:
        if is_long_running:
            metadata = dict(gate(session, phase="daily_metadata"))
            if metadata.get("gate_status") == "waiting":
                print(
                    json.dumps(
                        {
                            "status": "waiting",
                            "reason": "outside_confirmed_dce_session",
                        }
                    )
                )
                return 0
            trading_day = date.fromisoformat(
                str(metadata["target_trading_day"])
            )
            allowed_bucket_ends = {
                datetime.fromisoformat(value)
                for value in metadata["expected_bucket_ends"]
            }
            window_end = datetime.fromisoformat(
                str(metadata["window_end"])
            )
            authorization_hash = str(metadata["authorization_hash"])
        else:
            gate(session, phase="verify")
            authorization_hash = args.approval_hash
        redis = get_redis_connection()
        redis_ready = bool(redis.ping())
        service = Stage9WechatDeliveryService(session, environ=os.environ)
        result = dispatch_bounded_one_day(
            session,
            delivery_service=service,
            trading_day=trading_day,
            window_end=window_end,
            parent_hash=authorization_hash,
            global_autosend_enabled=False,
            redis_ready=redis_ready,
            allowed_bucket_ends=allowed_bucket_ends,
        )
        session.commit()
    from app.services.htdy_s6_10_service_heartbeat import (
        publish_s610_service_heartbeat,
    )

    publish_s610_service_heartbeat(
        redis,
        service="dispatcher",
        authorization_hash=authorization_hash,
        target_trading_day=trading_day,
        details={
            "selected_count": len(result["selected_event_ids"]),
            "capped_count": len(result["capped_event_ids"]),
            "blocked_count": len(result["blocked_event_ids"]),
        },
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _build_gate(
    *,
    builder: Any,
    is_long_running: bool,
    packet_path: Path,
    approval_hash: str,
    environ: Any,
) -> Any:
    packet_argument = (
        "approval_packet_path"
        if is_long_running
        else "parent_packet_path"
    )
    return builder(
        **{
            packet_argument: packet_path,
            "approval_hash": approval_hash,
            "environ": environ,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
