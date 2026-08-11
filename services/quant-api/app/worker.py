"""RQ Worker 入口（已退役 stub）。

Signal/通知相关 RQ worker 与队列在表面退役后已全部移除；本模块保留入口以便
误启动时立即失败并给出明确提示，而非静默挂起或连接 Redis。
"""

from __future__ import annotations

import sys

# Signal/notification RQ workers and queues are fully retired.


def main() -> None:
    """拒绝启动已退役的 RQ worker，并以非零状态退出。"""
    queue_name = sys.argv[1] if len(sys.argv) > 1 else "retired"
    raise SystemExit(
        f"retired worker queue '{queue_name}': "
        "no RQ worker entrypoints remain after surface retirement"
    )


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "retired"
    print(f"Refusing RQ worker for retired queue: {selected}")
    main()
