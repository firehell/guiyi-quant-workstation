from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.signal import SignalEvent  # noqa: E402
from app.signal.stage9_wechat import build_stage9_wechat_preview  # noqa: E402
from app.signal.stage9_wechat_delivery import (  # noqa: E402
    Stage9WechatDeliveryService,
    retry_pending_notifications,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 9-B guarded Enterprise WeChat sender")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--event-id", type=int, help="single SignalEvent id to preview or send")
    target.add_argument("--retry-pending", action="store_true", help="send due retry_pending enterprise WeChat notifications")
    parser.add_argument("--limit", type=int, default=10, help="maximum retry_pending rows to process")
    parser.add_argument("--run-send", action="store_true", help="actually send through QYWX_WEBHOOK_URL")
    parser.add_argument("--confirm-observation-only", action="store_true", help="required with --run-send")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        print(_json({"ok": False, "error": "limit must be positive"}))
        return 2
    if args.run_send and not args.confirm_observation_only:
        print(_json({"ok": False, "error": "--run-send requires --confirm-observation-only"}))
        return 2

    with SessionLocal() as session:
        if args.retry_pending:
            if not args.run_send:
                print(
                    _json(
                        {
                            "ok": True,
                            "dry_run": True,
                            "would_read_webhook": False,
                            "would_send_wechat": False,
                            "message": "retry preview only; pass --run-send --confirm-observation-only to send due retries",
                        }
                    )
                )
                return 0
            results = retry_pending_notifications(session, limit=args.limit)
            print(_json({"ok": True, "dry_run": False, "results": [item.to_public_dict() for item in results]}))
            return 0

        event = session.get(SignalEvent, args.event_id)
        if event is None:
            print(_json({"ok": False, "error": "signal event not found", "event_id": args.event_id}))
            return 1

        if not args.run_send:
            preview = build_stage9_wechat_preview(event)
            print(
                _json(
                    {
                        "ok": True,
                        "dry_run": True,
                        "event_id": event.id,
                        "allowed": preview["allowed"],
                        "blocked_reasons": preview["blocked_reasons"],
                        "would_read_webhook": False,
                        "would_send_wechat": False,
                        "notification_recorded": False,
                    }
                )
            )
            return 0

        result = Stage9WechatDeliveryService(session).send_event(event.id)
        print(_json({"ok": True, "dry_run": False, **result.to_public_dict()}))
        return 0


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
