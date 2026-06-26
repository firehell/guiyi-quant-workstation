from __future__ import annotations

import sys

from rq import Worker

from app.queue import BACKTEST_QUEUE_NAME, SIGNAL_QUEUE_NAME, get_backtest_queue, get_redis_connection, get_signal_queue


def main() -> None:
    queue_name = sys.argv[1] if len(sys.argv) > 1 else "backtests"
    if queue_name not in {"backtests", "signals"}:
        raise SystemExit(f"unsupported worker queue: {queue_name}")
    connection = get_redis_connection()
    queue = get_signal_queue() if queue_name == "signals" else get_backtest_queue()
    Worker([queue], connection=connection).work()


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "backtests"
    queue_label = SIGNAL_QUEUE_NAME if selected == "signals" else BACKTEST_QUEUE_NAME
    print(f"Starting RQ worker for queue: {queue_label}")
    main()
