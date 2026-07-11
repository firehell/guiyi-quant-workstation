from __future__ import annotations

import sys

from rq import Worker

from app.queue import (
    BACKTEST_QUEUE_NAME,
    NOTIFICATION_QUEUE_NAME,
    SIGNAL_QUEUE_NAME,
    get_backtest_queue,
    get_notification_queue,
    get_redis_connection,
    get_signal_queue,
)


def main() -> None:
    queue_name = sys.argv[1] if len(sys.argv) > 1 else "backtests"
    if queue_name not in {"backtests", "signals", "notifications"}:
        raise SystemExit(f"unsupported worker queue: {queue_name}")
    connection = get_redis_connection()
    if queue_name == "signals":
        queue = get_signal_queue()
    elif queue_name == "notifications":
        queue = get_notification_queue()
    else:
        queue = get_backtest_queue()
    Worker([queue], connection=connection).work()


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "backtests"
    queue_labels = {
        "backtests": BACKTEST_QUEUE_NAME,
        "signals": SIGNAL_QUEUE_NAME,
        "notifications": NOTIFICATION_QUEUE_NAME,
    }
    queue_label = queue_labels.get(selected, selected)
    print(f"Starting RQ worker for queue: {queue_label}")
    main()
