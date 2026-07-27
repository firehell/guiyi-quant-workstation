#!/usr/bin/env python3
"""Prepare/verify the HTDY schema-v3 service parent and Approval A bundle."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
    "codex/v1-htdy-approval-a-rebind",
    "codex/v1-htdy-s608-real-acceptance",
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
    parser.add_argument(
        "--database-recovery-receipt",
        type=Path,
        required=True,
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--service-parent-packet", type=Path)
    parser.add_argument("--approval-bundle", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from sqlalchemy import func, select, text

        from app.db.session import SessionLocal
        from app.models.data_center import TradingCalendar
        from app.models.signal import SignalEvent
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
        from app.services.s607_code_rebind import (
            collect_after_market_health,
            collect_launchd_identity,
            launchd_binding,
        )

        _require_arguments(args)
        deployment = _read_json(args.deployment_packet)
        rebind = _read_json(args.s6_07_rebind_packet)
        receipt = {
            "path": str(args.s6_07_final_receipt.resolve(strict=False)),
            "sha256": _file_hash(args.s6_07_final_receipt),
        }
        recovery_receipt = _database_recovery_receipt_identity(
            args.database_recovery_receipt
        )
        verify_s6_07_code_rebind_packet(
            rebind,
            approval_hash=str(rebind.get("packet_hash") or ""),
            deployment_packet=deployment,
            current_s6_07_final_receipt=receipt,
            current_database_recovery_receipt=recovery_receipt,
            current_after_market_launchd=(
                launchd_binding(
                    collect_launchd_identity(args.runtime_root)
                )
            ),
            current_after_market_health=(
                collect_after_market_health()
            ),
            expected_rebind_receipt=rebind.get(
                "rebind_receipt"
            )
            or {},
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
            generated_at = datetime.now(
                ZoneInfo("Asia/Shanghai")
            )
            generated_on = generated_at.date()
            first_day_event_count = session.scalar(
                select(func.count(SignalEvent.id)).where(
                    SignalEvent.source_mode
                    == "live_realtime_repainting",
                    SignalEvent.strategy_name
                    == "htdy_original_realtime_first_seen",
                    SignalEvent.strategy_version == "v1.0",
                    SignalEvent.product == "jm",
                    SignalEvent.period == "15m",
                    SignalEvent.dominant_mapping_date
                    == FROZEN_TRADING_DAYS[0],
                )
            )
            validate_frozen_parent_window(
                generated_at=generated_at,
                verified_trading_days=calendar_days,
                first_day_htdy_event_count=int(
                    first_day_event_count or 0
                ),
                first_day_child_present=(
                    args.output_dir
                    / "daily"
                    / FROZEN_TRADING_DAYS[0].isoformat()
                    / "child_packet.json"
                ).exists(),
            )
            bindings = collect_target_bindings(
                session,
                source_root=PROJECT_ROOT,
                runtime_root=args.runtime_root,
                output_root=args.output_dir,
                deployment_packet=args.deployment_packet,
                rebind_packet=args.s6_07_rebind_packet,
                s6_07_final_receipt=receipt,
                database_recovery_receipt=recovery_receipt,
                as_of_date=generated_on,
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
    database_recovery_receipt: dict[str, Any],
    as_of_date: Any,
) -> dict[str, Any]:
    from sqlalchemy import select, text

    from app.models.data_center import (
        MainContractMap,
        MarketDataFile,
        ProfileActiveBinding,
    )
    from app.services.htdy_s6_08_runtime_gate import (
        SERVICE_BUNDLE_PATHS,
        _database_state,
        _mount_root,
        _paths_hash,
        _tree_hash,
    )
    from guiyi_quant.indicators import (
        htdy_original_source_sha256,
        realtime_observation_policy_sha256,
    )

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
            select(MainContractMap)
            .where(
                MainContractMap.instrument_symbol == "jm",
                MainContractMap.trade_date <= as_of_date,
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
            .order_by(
                MainContractMap.trade_date.desc(),
                MainContractMap.id.desc(),
            )
        )
    )
    parent_mapping = select_parent_mapping_identity(
        mappings,
        as_of_date=as_of_date,
    )
    mapping = next(
        item
        for item in mappings
        if item.id == parent_mapping["mapping_id"]
    )
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
        "database_recovery_receipt": database_recovery_receipt,
        "parent_mapping": {
            key: value
            for key, value in parent_mapping.items()
            if key != "mapping_id"
        },
        "service_bundle_sha256": _paths_hash(
            source_root,
            list(SERVICE_BUNDLE_PATHS),
        ),
        "runtime": target_runtime_binding(
            git_identities,
            runtime_root=runtime_root,
        ),
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


def select_parent_mapping_identity(
    rows: Any,
    *,
    as_of_date: Any,
) -> dict[str, Any]:
    eligible = [
        item
        for item in rows
        if item.trade_date <= as_of_date
    ]
    if not eligible:
        raise RuntimeError("parent_mapping_missing_or_duplicate")
    latest_day = max(item.trade_date for item in eligible)
    latest = [item for item in eligible if item.trade_date == latest_day]
    if len(latest) != 1:
        raise RuntimeError("parent_mapping_missing_or_duplicate")
    item = latest[0]
    payload = {
        "mapping_id": item.id,
        "trade_date": item.trade_date.isoformat(),
        "contract_code": str(item.contract_code),
        "data_version": str(item.data_version),
        "created_at": item.created_at.isoformat(),
    }
    return {
        "mapping_id": item.id,
        "trade_date": payload["trade_date"],
        "contract_code": payload["contract_code"],
        "sha256": hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
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


def target_runtime_binding(
    git_identities: Mapping[str, Mapping[str, Any]],
    *,
    runtime_root: Path,
) -> dict[str, Any]:
    source = git_identities.get("source")
    if not isinstance(source, Mapping):
        raise RuntimeError("source_identity_invalid")
    commit = str(source.get("commit") or "")
    tree = str(source.get("tree") or "")
    if (
        len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or len(tree) != 40
        or any(character not in "0123456789abcdef" for character in tree)
    ):
        raise RuntimeError("source_identity_invalid")
    return {
        "root": str(runtime_root.resolve()),
        "commit": commit,
        "tree_sha256": hashlib.sha256(tree.encode()).hexdigest(),
        "tracked_clean": True,
    }


def _require_arguments(args: argparse.Namespace) -> None:
    required = (
        args.deployment_packet,
        args.s6_07_rebind_packet,
        args.s6_07_final_receipt,
        args.database_recovery_receipt,
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


def _database_recovery_receipt_identity(
    path: Path,
) -> dict[str, Any]:
    if path.name == "recovery_lineage_rebind_receipt.json":
        from app.services.s607_recovery_lineage_rebind import (
            load_recovery_lineage_rebind_identity,
            sha256_file,
        )

        return load_recovery_lineage_rebind_identity(
            path,
            expected_sha256=sha256_file(path),
        )
    from app.services.s607_database_recovery import (
        verify_semantic_recovery_receipt,
    )

    receipt = _read_json(path)
    verify_semantic_recovery_receipt(receipt)
    return {
        "path": str(path.resolve(strict=True)),
        "sha256": _file_hash(path),
        "receipt_hash": receipt["receipt_hash"],
    }


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
