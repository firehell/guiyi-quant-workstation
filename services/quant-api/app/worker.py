from __future__ import annotations

import sys

# Signal scan and live notification RQ workers are retired with the Market-only Web slim.
# DB models and package code may remain for a later rebuild; do not start these queues.


def main() -> None:
    queue_name = sys.argv[1] if len(sys.argv) > 1 else "signals"
    raise SystemExit(
        f"retired worker queue '{queue_name}': "
        "signal/notification RQ entrypoints are unmounted in slim-web-to-market"
    )


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "signals"
    print(f"Refusing RQ worker for retired queue: {selected}")
    main()
