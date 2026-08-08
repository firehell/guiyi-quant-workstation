from __future__ import annotations

import sys

# Signal/notification RQ workers and queues are fully retired.


def main() -> None:
    queue_name = sys.argv[1] if len(sys.argv) > 1 else "retired"
    raise SystemExit(
        f"retired worker queue '{queue_name}': "
        "no RQ worker entrypoints remain after surface retirement"
    )


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "retired"
    print(f"Refusing RQ worker for retired queue: {selected}")
    main()
