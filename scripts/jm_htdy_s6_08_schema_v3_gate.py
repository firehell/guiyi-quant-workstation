#!/usr/bin/env python3
"""Prepare/verify the HTDY schema-v3 service parent and Approval A bundle."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
for root in (API_ROOT, CORE_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

ALLOWED_SOURCE_BRANCHES = {
    "main",
    "codex/v1-htdy-step04-final-closure",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HTDY S6-08 schema-v3 service parent Gate"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--deployment-packet", type=Path, required=True)
    parser.add_argument("--s6-07-rebind-packet", type=Path, required=True)
    parser.add_argument("--s6-07-final-receipt", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--service-parent-packet", type=Path)
    parser.add_argument("--approval-bundle", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from sqlalchemy import select, text

        from app.db.session import SessionLocal
        from app.models.data_center import TradingCalendar
        from app.services.htdy_s6_08_approval_artifacts import (
            build_approval_bundle,
            verify_approval_bundle,
            verify_s6_07_code_rebind_packet,
            write_json_create_only,
        )
        from app.services.htdy_s6_08_schema_v3 import (
            FROZEN_TRADING_DAYS,
            build_parent_authorization,
            validate_frozen_parent_window,
            verify_parent_authorization,
        )

        _require_arguments(args)
        deployment = _read_json(args.deployment_packet)
        rebind = _read_json(args.s6_07_rebind_packet)
        receipt = {
            "path": str(args.s6_07_final_receipt.resolve(strict=False)),
            "sha256": _file_hash(args.s6_07_final_receipt),
        }
        verify_s6_07_code_rebind_packet(
            rebind,
            approval_hash=str(rebind.get("packet_hash") or ""),
            deployment_packet=deployment,
            current_s6_07_final_receipt=receipt,
        )
        with SessionLocal() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            calendar_days = tuple(
                session.scalars(
                    select(TradingCalendar.trade_date)
                    .where(
                        TradingCalendar.exchange_code == "DCE",
                        TradingCalendar.trade_date.in_(
                            FROZEN_TRADING_DAYS
                        ),
                        TradingCalendar.is_trading_day.is_(True),
                    )
                    .order_by(TradingCalendar.trade_date)
                )
            )
            validate_frozen_parent_window(
                generated_on=datetime.now(
                    ZoneInfo("Asia/Shanghai")
                ).date(),
                verified_trading_days=calendar_days,
            )
            bindings = collect_target_bindings(
                session,
                source_root=PROJECT_ROOT,
                runtime_root=args.runtime_root,
                output_root=args.output_dir,
                deployment_packet=args.deployment_packet,
                rebind_packet=args.s6_07_rebind_packet,
                s6_07_final_receipt=receipt,
            )
            session.rollback()
        if args.prepare:
            parent = build_parent_authorization(
                trading_days=FROZEN_TRADING_DAYS,
                bindings=bindings,
            )
            bundle = build_approval_bundle(
                deployment_packet_path=args.deployment_packet,
                deployment_packet=deployment,
                rebind_packet_path=args.s6_07_rebind_packet,
                rebind_packet=rebind,
                service_parent_packet_path=args.service_parent_packet,
                service_parent_packet=parent,
            )
            write_json_create_only(args.service_parent_packet, parent)
            write_json_create_only(args.approval_bundle, bundle)
            status = "approval_required"
        else:
            parent = _read_json(args.service_parent_packet)
            bundle = _read_json(args.approval_bundle)
            verify_parent_authorization(
                parent,
                approval_hash=str(parent.get("packet_hash") or ""),
                current_bindings=bindings,
            )
            verify_approval_bundle(
                bundle,
                deployment_packet=deployment,
                rebind_packet=rebind,
                service_parent_packet=parent,
            )
            status = "verified"
        print(
            json.dumps(
                {
                    "status": status,
                    "HTDY_DEPLOYMENT_PACKET_HASH": deployment[
                        "packet_hash"
                    ],
                    "S6_07_REBIND_PACKET_HASH": rebind["packet_hash"],
                    "HTDY_S6_08_SERVICE_PACKET_HASH": parent[
                        "packet_hash"
                    ],
                    "writes_authorized": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - emit bounded reason only.
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "reason": _safe_reason(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1


def collect_target_bindings(
    session: Any,
    *,
    source_root: Path,
    runtime_root: Path,
    output_root: Path,
    deployment_packet: Path,
    rebind_packet: Path,
    s6_07_final_receipt: dict[str, Any],
) -> dict[str, Any]:
    from sqlalchemy import select, text

    from app.models.data_center import (
        MainContractMap,
        MarketDataFile,
        ProfileActiveBinding,
    )
    from app.services.htdy_s6_08_runtime_gate import (
        _database_state,
        _mount_root,
        _paths_hash,
        _tree_hash,
    )
    from guiyi_quant.indicators import (
        htdy_original_source_sha256,
        realtime_observation_policy_sha256,
    )

    from app.services.htdy_s6_08_schema_v3 import FROZEN_TRADING_DAYS

    if not source_root.is_dir() or not runtime_root.is_dir():
        raise RuntimeError("source_or_runtime_root_unavailable")
    if not output_root.is_dir():
        raise RuntimeError("output_root_unavailable")
    git_identities = collect_source_runtime_git_identities(
        source_root=source_root,
        runtime_root=runtime_root,
    )
    mappings = list(
        session.scalars(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == "jm",
                MainContractMap.trade_date == FROZEN_TRADING_DAYS[0],
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
        )
    )
    if len(mappings) != 1:
        raise RuntimeError("frozen_window_mapping_missing_or_duplicate")
    mapping = mappings[0]
    binding = session.scalar(
        select(ProfileActiveBinding).where(
            ProfileActiveBinding.profile_id == "live_observation_v1",
            ProfileActiveBinding.instrument_symbol == "jm",
            ProfileActiveBinding.contract_code == mapping.contract_code,
            ProfileActiveBinding.period == "15m",
            ProfileActiveBinding.binding_status == "active",
        )
    )
    if binding is None or binding.market_data_file_id is None:
        raise RuntimeError("profile_binding_missing")
    market_file = session.get(MarketDataFile, binding.market_data_file_id)
    if (
        market_file is None
        or market_file.quality_status != "passed"
        or market_file.data_role != "primary"
        or not _sha256(str(market_file.checksum or ""))
    ):
        raise RuntimeError("profile_file_invalid")
    counts, hashes = _database_state(session)
    revision = str(
        session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    )
    source_files = [
        "services/quant-api/app/services/htdy_realtime_snapshot.py",
        "services/quant-api/app/services/htdy_realtime_evaluator.py",
        "services/quant-api/app/services/htdy_first_seen_events.py",
        "services/quant-api/app/services/htdy_s6_08_schema_v3.py",
        "services/quant-api/app/services/htdy_s6_08_runtime_gate.py",
        "services/quant-api/app/services/htdy_runtime_event_handler.py",
        "services/quant-api/app/services/live_runtime.py",
        "services/quant-api/app/runtime_scheduler.py",
    ]
    plist = (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / "com.guiyi.quant-runtime-scheduler.plist"
    )
    return {
        "deployment_packet_sha256": str(
            _read_json(deployment_packet).get("packet_hash") or ""
        ),
        "s6_07_rebind_packet_sha256": str(
            _read_json(rebind_packet).get("packet_hash") or ""
        ),
        "s6_07_final_receipt": s6_07_final_receipt,
        "service_bundle_sha256": _paths_hash(
            source_root,
            source_files,
        ),
        "runtime": {
            "root": str(runtime_root.resolve()),
            "commit": git_identities["runtime"]["commit"],
            "tree_sha256": hashlib.sha256(
                git_identities["runtime"]["tree"].encode()
            ).hexdigest(),
            "tracked_clean": True,
        },
        "database_revision": revision,
        "actual_contract_resolver_sha256": _file_hash(
            source_root
            / "services"
            / "quant-api"
            / "app"
            / "services"
            / "live_target_contracts.py"
        ),
        "profile": {
            "profile_id": binding.profile_id,
            "market_data_file_id": market_file.id,
            "data_version": market_file.data_version,
            "checksum": market_file.checksum,
        },
        "source_sha256": htdy_original_source_sha256(),
        "policy_sha256": realtime_observation_policy_sha256(),
        "writer_sha256": _file_hash(
            source_root
            / "services"
            / "quant-api"
            / "app"
            / "services"
            / "htdy_first_seen_events.py"
        ),
        "web": {
            "source_sha256": _tree_hash(
                source_root / "apps" / "quant-web" / "src"
            ),
            "bundle_sha256": _tree_hash(
                source_root / "apps" / "quant-web" / "dist"
            ),
        },
        "feature_flags": {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        },
        "baseline": {"counts": counts, "hashes": hashes},
        "output": {
            "root": str(output_root.resolve()),
            "device": output_root.stat().st_dev,
            "mount": str(_mount_root(output_root)),
        },
        "launchd": {
            "label": "com.guiyi.quant-runtime-scheduler",
            "plist_sha256": _file_hash(plist),
        },
        "no_migration": True,
    }


def collect_source_runtime_git_identities(
    *,
    source_root: Path,
    runtime_root: Path,
) -> dict[str, dict[str, Any]]:
    branch = _git(source_root, "branch", "--show-current")
    source_tracked = _git(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    runtime_tracked = _git(
        runtime_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if branch not in ALLOWED_SOURCE_BRANCHES or source_tracked:
        raise RuntimeError("source_identity_invalid")
    if runtime_tracked:
        raise RuntimeError("runtime_identity_invalid")
    return {
        "source": {
            "root": str(source_root.resolve()),
            "branch": branch,
            "commit": _git(source_root, "rev-parse", "HEAD"),
            "tree": _git(source_root, "rev-parse", "HEAD^{tree}"),
            "tracked_clean": True,
        },
        "runtime": {
            "root": str(runtime_root.resolve()),
            "commit": _git(runtime_root, "rev-parse", "HEAD"),
            "tree": _git(runtime_root, "rev-parse", "HEAD^{tree}"),
            "tracked_clean": True,
        },
    }


def _require_arguments(args: argparse.Namespace) -> None:
    required = (
        args.deployment_packet,
        args.s6_07_rebind_packet,
        args.s6_07_final_receipt,
        args.runtime_root,
        args.output_dir,
        args.service_parent_packet,
        args.approval_bundle,
    )
    if any(item is None for item in required):
        raise RuntimeError("required_argument_missing")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("approval_artifact_invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("approval_artifact_invalid")
    return value


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RuntimeError("bound_file_missing") from exc


def _git(root: Path, *arguments: str) -> str:
    import subprocess

    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(value: str) -> bool:
    if len(value) != 64 or value != value.lower():
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _safe_reason(exc: Exception) -> str:
    value = str(exc).split(":", 1)[0]
    if any(
        word in value.lower()
        for word in ("password", "secret", "token", "webhook", "cookie")
    ):
        return "redacted"
    return value[:120]


if __name__ == "__main__":
    raise SystemExit(main())
