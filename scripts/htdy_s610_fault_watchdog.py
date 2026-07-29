#!/usr/bin/env python3
"""Detached cleanup watchdog for one bounded S6-10 fault."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fault",
        required=True,
        choices=("redis", "postgres", "rqdata"),
    )
    parser.add_argument(
        "--delay-seconds",
        type=int,
        required=True,
    )
    parser.add_argument("--target-ip")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--parent-packet-hash", required=True)
    args = parser.parse_args()
    if not 1 <= args.delay_seconds <= 65:
        return 2
    if (
        len(args.parent_packet_hash) != 64
        or any(char not in "0123456789abcdef" for char in args.parent_packet_hash)
    ):
        return 2
    fault_root = args.evidence_root.resolve(strict=False) / "faults"
    fault_root.mkdir(parents=True, exist_ok=True)
    ack = {
        "status": "armed",
        "fault": args.fault,
        "parent_packet_hash": args.parent_packet_hash,
        "pid": os.getpid(),
        "armed_at": datetime.now(UTC).isoformat(),
    }
    ack_path = fault_root / f"{args.fault}-watchdog-{os.getpid()}.armed.json"
    _write_create_only(ack_path, ack)
    time.sleep(args.delay_seconds)
    if args.fault in {"redis", "postgres"}:
        container = (
            "guiyi-redis" if args.fault == "redis" else "guiyi-postgres"
        )
        command = ["docker", "start", container]
    else:
        if args.target_ip is None:
            return 2
        try:
            target = ipaddress.ip_address(args.target_ip)
        except ValueError:
            return 2
        if target.is_unspecified or target.is_loopback:
            return 2
        command = [
            "sudo",
            "-n",
            "pfctl",
            "-a",
            "com.guiyi.htdy-s610",
            "-F",
            "all",
        ]
    try:
        subprocess.run(  # noqa: S603 - fixed bounded command vectors.
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        status = "cleanup_failed"
        exit_code = 1
    else:
        status = "cleanup_completed"
        exit_code = 0
    receipt = {
        "status": status,
        "fault": args.fault,
        "parent_packet_hash": args.parent_packet_hash,
        "pid": os.getpid(),
        "ack_sha256": hashlib.sha256(ack_path.read_bytes()).hexdigest(),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    receipt["receipt_hash"] = hashlib.sha256(
        json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _write_create_only(
        fault_root / f"{args.fault}-watchdog-{os.getpid()}.receipt.json",
        receipt,
    )
    return exit_code


def _write_create_only(path: Path, payload: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    raise SystemExit(main())
