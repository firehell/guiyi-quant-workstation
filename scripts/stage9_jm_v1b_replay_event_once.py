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
from app.signal.stage9_jm_v1b_replay import Stage9JmV1bReplayService  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 9-B2 guarded JM V1-B historical replay event materializer")
    parser.add_argument("--period", choices=["auto", "15m", "5m"], default="auto")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--run-write", action="store_true", help="write one StrategySignal and SignalEvent")
    parser.add_argument("--confirm-historical-replay", action="store_true", help="required with --run-write")
    parser.add_argument("--confirm-observation-only", action="store_true", help="required with --run-write")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        print(_json({"ok": False, "error": "limit must be positive"}))
        return 2
    if args.run_write and (not args.confirm_historical_replay or not args.confirm_observation_only):
        print(
            _json(
                {
                    "ok": False,
                    "error": "--run-write requires --confirm-historical-replay and --confirm-observation-only",
                    "would_read_webhook": False,
                    "would_send_wechat": False,
                }
            )
        )
        return 2

    with SessionLocal() as session:
        try:
            result = Stage9JmV1bReplayService(session).run(
                period=args.period,
                limit=args.limit,
                run_write=args.run_write,
                confirm_historical_replay=args.confirm_historical_replay,
                confirm_observation_only=args.confirm_observation_only,
            )
        except Exception as exc:
            print(_json({"ok": False, "error": str(exc), "would_read_webhook": False, "would_send_wechat": False}))
            return 1
    result["would_read_webhook"] = False
    result["would_send_wechat"] = False
    print(_json(result))
    return 0 if result.get("ok") else 1


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
