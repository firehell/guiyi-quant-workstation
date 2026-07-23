from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from app.services.after_market_real_acceptance import (
    FINAL_GATE,
    RealAcceptanceError,
    build_real_acceptance_receipt,
    publish_real_acceptance_receipt,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify or publish the final S6-07 real acceptance receipt"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--publish", action="store_true")
    parser.add_argument("--confirm-final-gate", action="store_true")
    parser.add_argument("--deployment-receipt", type=Path, required=True)
    parser.add_argument("--enable-packet", type=Path, required=True)
    parser.add_argument("--d1-enable-packet", type=Path, required=True)
    parser.add_argument("--d1-snapshot", type=Path, required=True)
    parser.add_argument("--d2-outage-snapshot", type=Path, required=True)
    parser.add_argument("--d2-completion-snapshot", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    git_identity_provider: Callable[[], dict[str, str]] | None = None,
    ancestry_checker: Callable[[str, str], bool] | None = None,
) -> int:
    args = parse_args(argv)
    if args.publish and not args.confirm_final_gate:
        print(
            json.dumps(
                {"status": "blocked", "error_type": "final_gate_confirmation_required"}
            )
        )
        return 2
    if args.publish and args.receipt_out is None:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": "real_acceptance_receipt_out_required",
                }
            )
        )
        return 2
    try:
        deployment = _read_object(args.deployment_receipt)
        enable = _read_object(args.enable_packet)
        d1_enable = _read_object(args.d1_enable_packet)
        deployment_commit = str(deployment.get("runtime_commit") or "")
        runtime_commit = str(
            ((enable.get("bound_facts") or {}).get("git") or {}).get("commit") or ""
        )
        d1_runtime_commit = str(
            ((d1_enable.get("bound_facts") or {}).get("git") or {}).get("commit")
            or ""
        )
        receipt = build_real_acceptance_receipt(
            deployment_receipt_path=args.deployment_receipt,
            enable_packet_path=args.enable_packet,
            d1_enable_packet_path=args.d1_enable_packet,
            d1_snapshot_path=args.d1_snapshot,
            d2_outage_snapshot_path=args.d2_outage_snapshot,
            d2_completion_snapshot_path=args.d2_completion_snapshot,
            verifier_git=(git_identity_provider or _git_identity)(),
            deployment_is_ancestor=(ancestry_checker or _git_is_ancestor)(
                deployment_commit, runtime_commit
            ),
            d1_runtime_is_ancestor=(ancestry_checker or _git_is_ancestor)(
                d1_runtime_commit, runtime_commit
            ),
        )
        if args.publish:
            publish_real_acceptance_receipt(args.receipt_out, receipt)
            status = "published"
        else:
            status = "verified"
    except RealAcceptanceError as exc:
        print(
            json.dumps({"status": "blocked", "error_type": str(exc).split(":", 1)[0]})
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits only a redacted exception type.
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__}))
        return 1
    print(
        json.dumps(
            {
                "status": status,
                "gate": FINAL_GATE,
                "runtime_commit": receipt["runtime_commit"],
                "d1_trading_day": receipt["d1"]["trading_day"],
                "d2_trading_day": receipt["d2"]["trading_day"],
                "receipt_preview_sha256": _canonical_sha256(receipt),
                "receipt_out": str(args.receipt_out.resolve(strict=False))
                if args.publish
                else None,
                "writes_authorized": bool(args.publish),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _git_identity() -> dict[str, str]:
    status = _git_value("status", "--porcelain=v1", "--untracked-files=no")
    return {
        "commit": _git_value("rev-parse", "HEAD"),
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _git_value(*arguments: str) -> str:
    return subprocess.run(
        ("git", "-c", "core.fsmonitor=false", *arguments),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealAcceptanceError("real_acceptance_artifact_invalid") from exc
    if not isinstance(payload, dict):
        raise RealAcceptanceError("real_acceptance_artifact_invalid")
    return payload


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
