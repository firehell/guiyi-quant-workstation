"""Build and verify JM S6-03 plans and approval packets without external writes."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
QUANT_CORE_ROOT = REPO_ROOT / "packages/quant-core"
for import_root in (SERVICE_ROOT, QUANT_CORE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.services.rqdata_ingest.jm_historical_catchup import (  # noqa: E402
    CatchupBlockedError,
    build_gap_plan,
    build_s6_03_approval_packet,
    plan_payload,
    verify_approval_packet,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Build a JM-only gap plan from a frozen metadata snapshot.")
    plan.add_argument("--snapshot", type=Path, required=True)

    packet = subparsers.add_parser("packet", help="Build an approval-required S6-03 packet from a frozen snapshot.")
    packet.add_argument("--snapshot", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="Verify packet integrity and bound facts immediately before apply.")
    verify.add_argument("--packet", type=Path, required=True)
    verify.add_argument("--current-facts", type=Path, required=True)
    return parser


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatchupBlockedError(f"json_object_required:{path.name}")
    return payload


def _day(value: Any) -> date:
    return date.fromisoformat(str(value))


def _gap_from_snapshot(snapshot: Mapping[str, Any]):
    active_ends = {
        (str(row["contract"]), str(row["period"]), str(row["source_role"])): _day(row["end"])
        for row in snapshot.get("active_ends", [])
    }
    rank1_mapping = {_day(day): str(contract) for day, contract in dict(snapshot["rank1_mapping"]).items()}
    return build_gap_plan(
        product=str(snapshot.get("product", "jm")),
        trading_days=[_day(day) for day in snapshot["trading_days"]],
        target=_day(snapshot["latest_completed_trading_day"]),
        weekly_target=_day(snapshot["latest_completed_week_end"]),
        active_ends=active_ends,
        rank1_mapping=rank1_mapping,
    )


def _validate_redacted_database_target(value: str) -> None:
    credential = urlsplit(value).password
    if credential and credential != "***":
        raise CatchupBlockedError("database_target_must_be_redacted")


def _packet_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    database_target = str(snapshot["database_target"])
    _validate_redacted_database_target(database_target)
    return build_s6_03_approval_packet(
        plan=_gap_from_snapshot(snapshot),
        batch_id=str(snapshot["batch_id"]),
        git_commit=str(snapshot["git_commit"]),
        git_branch=str(snapshot["git_branch"]),
        git_status_sha256=str(snapshot["git_status_sha256"]),
        output_root=Path(str(snapshot["output_root"])),
        output_root_identity=dict(snapshot["output_root_identity"]),
        database_target=database_target,
        database_identity=dict(snapshot["database_identity"]),
        binding_snapshot_sha256=str(snapshot["binding_snapshot_sha256"]),
        metadata_snapshot_sha256=str(snapshot["metadata_snapshot_sha256"]),
        calendar_start=_day(snapshot["calendar_start"]),
        calendar_end=_day(snapshot["calendar_end"]),
    )


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "plan":
        payload = plan_payload(_gap_from_snapshot(_read_object(args.snapshot)))
    elif args.command == "packet":
        payload = _packet_from_snapshot(_read_object(args.snapshot))
    else:
        packet = _read_object(args.packet)
        verify_approval_packet(packet, current_facts=_read_object(args.current_facts))
        payload = {
            "status": "verified",
            "writes_performed": False,
            "packet_hash": packet["packet_hash"],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
