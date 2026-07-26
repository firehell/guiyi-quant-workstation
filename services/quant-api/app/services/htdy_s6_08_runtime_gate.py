"""Create-only Runtime state machine for the HTDY schema-v3 exception."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

from app.services.htdy_s6_08_schema_v3 import (
    HtDySchemaV3GateError,
    build_daily_child_authorization,
    canonical_packet_hash,
    verify_daily_child_authorization,
    verify_parent_authorization,
    verify_runtime_first_event,
    verify_runtime_idempotency_probe,
)


class HtDySchemaV3RuntimeGate:
    """Authorize one first event and one same-event idempotency probe."""

    def __init__(
        self,
        *,
        parent_packet_path: Path,
        approval_hash: str,
        current_bindings: Callable[[Any], Mapping[str, Any]],
        current_daily_state: Callable[[Any, date], Mapping[str, Any]],
        handler_factory: Callable[[Any], Any],
        now: Callable[[], datetime] | None = None,
        trading_day_resolver: (
            Callable[[Any, datetime, Mapping[str, Any]], date] | None
        ) = None,
    ) -> None:
        self.parent_packet_path = parent_packet_path.resolve(strict=False)
        self.parent_packet = _load_json(self.parent_packet_path)
        if self.parent_packet.get("schema_version") != 3:
            raise HtDySchemaV3GateError("schema_version_invalid")
        if canonical_packet_hash(self.parent_packet) != approval_hash:
            raise HtDySchemaV3GateError("packet_hash_invalid")
        self.approval_hash = approval_hash
        self.current_bindings = current_bindings
        self.current_daily_state = current_daily_state
        self.handler_factory = handler_factory
        self.now = now or (lambda: datetime.now(UTC))
        self.trading_day_resolver = (
            trading_day_resolver or _default_trading_day
        )
        self._pending_write: tuple[Path, Mapping[str, Any]] | None = None
        self._active_child: dict[str, Any] | None = None
        self._active_child_path: Path | None = None
        self._active_state: Mapping[str, Any] | None = None
        self._mode: str | None = None

    def __call__(
        self,
        session: Any,
        *,
        phase: str,
        result: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if phase == "pre_write":
            return self._pre_write(session)
        if phase == "post_write":
            return self._post_write(session, result or {})
        if phase == "after_commit":
            return self._after_commit()
        raise HtDySchemaV3GateError("runtime_gate_phase_invalid")

    def _pre_write(self, session: Any) -> Mapping[str, Any]:
        current_bindings = dict(self.current_bindings(session))
        verify_parent_authorization(
            self.parent_packet,
            approval_hash=self.approval_hash,
            current_bindings=current_bindings,
        )
        trading_day = self.trading_day_resolver(
            session,
            self.now(),
            self.parent_packet,
        )
        directory = (
            self.parent_packet_path.parent
            / "daily"
            / trading_day.isoformat()
        )
        child_path = directory / "child_packet.json"
        accepted_path = directory / "accepted_event.json"
        consumed_path = directory / "authorization_consumed.json"
        if consumed_path.exists():
            raise HtDySchemaV3GateError("authorization_consumed")
        state = dict(self.current_daily_state(session, trading_day))
        if state.get("trading_day") != trading_day:
            raise HtDySchemaV3GateError("child_trading_day_drift")
        accepted = _load_json(accepted_path) if accepted_path.exists() else None
        normalized_counts = dict(state["counts"])
        if accepted is not None:
            normalized_counts["strategy_signals"] -= 1
            normalized_counts["signal_events"] -= 1
        if child_path.exists():
            child = _load_json(child_path)
        else:
            child = build_daily_child_authorization(
                parent_packet=self.parent_packet,
                parent_approval_hash=self.approval_hash,
                current_parent_bindings=current_bindings,
                trading_day=trading_day,
                actual_contract=str(state["actual_contract"]),
                mapping_sha256=str(state["mapping_sha256"]),
                source_facts=state["source_facts"],
                baseline_counts=normalized_counts,
                baseline_hashes=state["hashes"],
            )
            _write_create_only(child_path, child)
        verify_daily_child_authorization(
            child,
            approval_hash=str(child["packet_hash"]),
            parent_packet=self.parent_packet,
            parent_approval_hash=self.approval_hash,
            current_parent_bindings=current_bindings,
            current_trading_day=trading_day,
            current_actual_contract=str(state["actual_contract"]),
            current_mapping_sha256=str(state["mapping_sha256"]),
            current_source_facts=state["source_facts"],
            current_counts=normalized_counts,
            current_hashes=state["hashes"],
        )
        self._active_child = child
        self._active_child_path = child_path
        self._active_state = state
        self._mode = "idempotency_probe" if accepted is not None else "first_event"
        return {
            "gate_status": "authorized",
            "gate_mode": self._mode,
            "authorization_hash": self.approval_hash,
            "daily_child_hash": child["packet_hash"],
            "target_trading_day": trading_day.isoformat(),
            "signal_event_handler": self.handler_factory(session),
        }

    def _post_write(
        self,
        session: Any,
        result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if (
            self._active_child is None
            or self._active_child_path is None
            or self._active_state is None
            or self._mode is None
        ):
            raise HtDySchemaV3GateError("runtime_gate_pre_write_required")
        child = self._active_child
        day = date.fromisoformat(str(child["trading_day"]))
        if result.get("trading_day") not in {None, day.isoformat()}:
            raise HtDySchemaV3GateError("runtime_trading_day_mismatch")
        runtime_result = dict(result.get("signal_events") or {})
        if (
            runtime_result.get("changed") != 0
            or runtime_result.get("blocked") != 0
        ):
            raise HtDySchemaV3GateError("runtime_event_result_invalid")
        state = dict(self.current_daily_state(session, day))
        directory = self._active_child_path.parent
        if self._mode == "first_event":
            created = runtime_result.get("created")
            if created == 0:
                if runtime_result.get("unchanged") not in {0, None}:
                    raise HtDySchemaV3GateError(
                        "first_natural_event_result_invalid"
                    )
                return self._metadata()
            if created != 1:
                raise HtDySchemaV3GateError(
                    "first_natural_event_count_invalid"
                )
            accepted = verify_runtime_first_event(
                child,
                approval_hash=str(child["packet_hash"]),
                events=state["events"],
                final_counts=state["counts"],
                final_hashes=state["hashes"],
            )
            self._pending_write = (
                directory / "accepted_event.json",
                {
                    "schema_version": 1,
                    "status": "first_event_committed",
                    "trading_day": day.isoformat(),
                    "child_packet_hash": child["packet_hash"],
                    **accepted,
                },
            )
        else:
            accepted = _load_json(directory / "accepted_event.json")
            verify_runtime_idempotency_probe(
                child,
                approval_hash=str(child["packet_hash"]),
                accepted_event={
                    key: accepted[key]
                    for key in (
                        "event_id",
                        "event_key",
                        "observation_key",
                    )
                },
                events=state["events"],
                current_counts=state["counts"],
                current_hashes=state["hashes"],
                runtime_result=runtime_result,
            )
            self._pending_write = (
                directory / "authorization_consumed.json",
                {
                    "schema_version": 1,
                    "status": "authorization_consumed",
                    "trading_day": day.isoformat(),
                    "child_packet_hash": child["packet_hash"],
                    "event_id": accepted["event_id"],
                    "event_key": accepted["event_key"],
                    "observation_key": accepted["observation_key"],
                    "idempotency_result": runtime_result,
                },
            )
        return self._metadata()

    def _after_commit(self) -> Mapping[str, Any]:
        if self._pending_write is not None:
            path, payload = self._pending_write
            _write_create_only(path, payload)
            self._pending_write = None
        return self._metadata()

    def _metadata(self) -> dict[str, Any]:
        return {
            "gate_status": "authorized",
            "gate_mode": self._mode,
            "authorization_hash": self.approval_hash,
            "daily_child_hash": (
                self._active_child.get("packet_hash")
                if self._active_child
                else None
            ),
            "target_trading_day": (
                self._active_child.get("trading_day")
                if self._active_child
                else None
            ),
        }


def build_runtime_gate(
    *,
    parent_packet_path: Path,
    approval_hash: str,
    environ: Mapping[str, str],
) -> HtDySchemaV3RuntimeGate:
    """Build the production gate with fresh filesystem and DB collectors."""

    packet = _load_json(parent_packet_path)
    return HtDySchemaV3RuntimeGate(
        parent_packet_path=parent_packet_path,
        approval_hash=approval_hash,
        current_bindings=lambda session: collect_current_bindings(
            session,
            parent_packet=packet,
            parent_packet_path=parent_packet_path,
            environ=environ,
        ),
        current_daily_state=lambda session, trading_day: (
            collect_current_daily_state(
                session,
                parent_packet=packet,
                trading_day=trading_day,
                environ=environ,
            )
        ),
        handler_factory=_runtime_handler,
        trading_day_resolver=_runtime_trading_day,
    )


def collect_current_bindings(
    session: Any,
    *,
    parent_packet: Mapping[str, Any],
    parent_packet_path: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Re-collect every full parent binding; never trust packet values alone."""

    from sqlalchemy import select, text

    from app.models.data_center import (
        MainContractMap,
        MarketDataFile,
        ProfileActiveBinding,
    )
    from guiyi_quant.indicators import (
        htdy_original_source_sha256,
        realtime_observation_policy_sha256,
    )

    expected = parent_packet.get("bindings")
    if not isinstance(expected, Mapping):
        raise HtDySchemaV3GateError("bindings_invalid")
    root = Path(str((expected.get("runtime") or {}).get("root") or ""))
    if not root.is_dir():
        raise HtDySchemaV3GateError("runtime_root_unavailable")
    directory = parent_packet_path.resolve(strict=False).parent
    deployment_path = directory / "deployment_packet.json"
    rebind_path = directory / "s6_07_rebind_packet.json"
    receipt = expected.get("s6_07_final_receipt") or {}
    receipt_path = Path(str(receipt.get("path") or ""))
    recovery_receipt = expected.get("database_recovery_receipt") or {}
    recovery_receipt_path = Path(
        str(recovery_receipt.get("path") or "")
    )
    deployment_packet = _load_json(deployment_path)
    rebind_packet = _load_json(rebind_path)
    from app.services.htdy_s6_08_approval_artifacts import (
        verify_s6_07_code_rebind_packet,
    )

    verify_s6_07_code_rebind_packet(
        rebind_packet,
        approval_hash=str(rebind_packet.get("packet_hash") or ""),
        deployment_packet=deployment_packet,
        current_s6_07_final_receipt={
            "path": str(receipt_path),
            "sha256": _file_hash(receipt_path),
        },
        current_database_recovery_receipt={
            "path": str(recovery_receipt_path),
            "sha256": _file_hash(recovery_receipt_path),
            "receipt_hash": _recovery_receipt_hash(
                recovery_receipt_path
            ),
        },
    )
    parent_mapping_expected = expected.get("parent_mapping") or {}
    try:
        parent_mapping_day = date.fromisoformat(
            str(parent_mapping_expected.get("trade_date") or "")
        )
    except ValueError as exc:
        raise HtDySchemaV3GateError("parent_mapping_drift") from exc
    parent_mappings = list(
        session.scalars(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == "jm",
                MainContractMap.trade_date == parent_mapping_day,
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
        )
    )
    if len(parent_mappings) != 1:
        raise HtDySchemaV3GateError("parent_mapping_drift")
    parent_mapping = _parent_mapping_identity(parent_mappings[0])
    profile_expected = expected.get("profile") or {}
    market_file = session.get(
        MarketDataFile,
        profile_expected.get("market_data_file_id"),
    )
    binding = session.scalar(
        select(ProfileActiveBinding).where(
            ProfileActiveBinding.profile_id == "live_observation_v1",
            ProfileActiveBinding.market_data_file_id
            == profile_expected.get("market_data_file_id"),
            ProfileActiveBinding.binding_status == "active",
        )
    )
    if market_file is None or binding is None:
        raise HtDySchemaV3GateError("profile_binding_drift")
    counts, hashes = _database_state(session)
    accepted_files = list(directory.glob("daily/*/accepted_event.json"))
    if len(accepted_files) > 1:
        raise HtDySchemaV3GateError("multiple_first_events_forbidden")
    if accepted_files:
        counts = {
            **counts,
            "strategy_signals": counts["strategy_signals"] - 1,
            "signal_events": counts["signal_events"] - 1,
        }
    runtime_commit = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    tracked = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    output_root = Path(str((expected.get("output") or {}).get("root") or ""))
    if not output_root.is_dir():
        raise HtDySchemaV3GateError("output_root_unavailable")
    plist = (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / "com.guiyi.quant-runtime-scheduler.plist"
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
    web_source = _tree_hash(root / "apps" / "quant-web" / "src")
    web_bundle = _tree_hash(root / "apps" / "quant-web" / "dist")
    revision = session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    return {
        "deployment_packet_sha256": str(
            deployment_packet.get("packet_hash") or ""
        ),
        "s6_07_rebind_packet_sha256": str(
            rebind_packet.get("packet_hash") or ""
        ),
        "s6_07_final_receipt": {
            "path": str(receipt_path),
            "sha256": _file_hash(receipt_path),
        },
        "database_recovery_receipt": {
            "path": str(recovery_receipt_path),
            "sha256": _file_hash(recovery_receipt_path),
            "receipt_hash": _recovery_receipt_hash(
                recovery_receipt_path
            ),
        },
        "parent_mapping": parent_mapping,
        "service_bundle_sha256": _paths_hash(root, source_files),
        "runtime": {
            "root": str(root.resolve()),
            "commit": runtime_commit,
            "tree_sha256": hashlib.sha256(tree.encode()).hexdigest(),
            "tracked_clean": tracked == "",
        },
        "database_revision": str(revision),
        "actual_contract_resolver_sha256": _file_hash(
            root
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
            "checksum": str(market_file.checksum or ""),
        },
        "source_sha256": htdy_original_source_sha256(),
        "policy_sha256": realtime_observation_policy_sha256(),
        "writer_sha256": _file_hash(
            root
            / "services"
            / "quant-api"
            / "app"
            / "services"
            / "htdy_first_seen_events.py"
        ),
        "web": {
            "source_sha256": web_source,
            "bundle_sha256": web_bundle,
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


def collect_current_daily_state(
    session: Any,
    *,
    parent_packet: Mapping[str, Any],
    trading_day: date,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    from sqlalchemy import desc, select

    from app.models.data_center import MainContractMap
    from app.models.signal import SignalEvent
    from guiyi_quant.indicators import (
        htdy_original_source_sha256,
        realtime_observation_policy_sha256,
    )

    mappings = list(
        session.scalars(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == "jm",
                MainContractMap.trade_date == trading_day,
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
        )
    )
    if len(mappings) != 1:
        raise HtDySchemaV3GateError("mapping_duplicate_or_missing")
    mapping = mappings[0]
    counts, hashes = _database_state(session)
    baseline = (
        (parent_packet.get("bindings") or {})
        .get("baseline", {})
        .get("counts", {})
    )
    delta = counts["signal_events"] - int(
        baseline.get("signal_events", 0)
    )
    if delta not in {0, 1}:
        raise HtDySchemaV3GateError("new_observation_key_forbidden")
    rows = (
        list(
            session.scalars(
                select(SignalEvent)
                .order_by(desc(SignalEvent.id))
                .limit(delta)
            )
        )
        if delta
        else []
    )
    events = [_event_payload(row) for row in reversed(rows)]
    profile = (parent_packet.get("bindings") or {}).get("profile") or {}
    profile_sha = _canonical_hash(profile)
    heartbeat_identity = {
        "runtime_commit": (
            (parent_packet.get("bindings") or {})
            .get("runtime", {})
            .get("commit")
        ),
        "scheduler": "com.guiyi.quant-runtime-scheduler",
    }
    return {
        "trading_day": trading_day,
        "actual_contract": mapping.contract_code,
        "mapping_sha256": _canonical_hash(
            {
                "id": mapping.id,
                "trade_date": mapping.trade_date.isoformat(),
                "contract_code": mapping.contract_code,
                "rank": mapping.rank,
                "rule": mapping.rule,
                "provider": mapping.provider,
                "data_version": mapping.data_version,
            }
        ),
        "source_facts": {
            "profile_sha256": profile_sha,
            "source_sha256": htdy_original_source_sha256(),
            "policy_sha256": realtime_observation_policy_sha256(),
            "runtime_heartbeat_sha256": _canonical_hash(
                heartbeat_identity
            ),
            "autosend_enabled": _enabled(
                environ,
                "GUIYI_WECHAT_AUTOSEND_ENABLED",
            ),
        },
        "counts": counts,
        "hashes": hashes,
        "events": events,
    }


def _runtime_handler(session: Any) -> Any:
    from app.services.htdy_runtime_event_handler import HtDyRuntimeEventHandler

    return HtDyRuntimeEventHandler(session)


def _database_state(session: Any) -> tuple[dict[str, int], dict[str, str]]:
    from sqlalchemy import text

    tables = {
        "strategy_signals": "strategy_signals",
        "signal_events": "signal_events",
        "signal_notifications": "signal_notifications",
        "signal_scan_tasks": "signal_scan_tasks",
        "orders": "backtest_orders",
        "trades": "backtest_trades",
        "review_notes": "review_notes",
        "backtest_tasks": "backtest_tasks",
        "profile_bindings": "profile_active_bindings",
        "canonical_assets": "market_data_files",
    }
    summaries: dict[str, dict[str, int]] = {}
    for key, table in tables.items():
        count = int(
            session.execute(
                text(f"SELECT count(*) FROM {table}")  # noqa: S608
            ).scalar_one()
        )
        max_id = int(
            session.execute(
                text(f"SELECT coalesce(max(id), 0) FROM {table}")  # noqa: S608
            ).scalar_one()
        )
        summaries[key] = {"count": count, "max_id": max_id}
    counts = {key: value["count"] for key, value in summaries.items()}
    hashes = {
        "backtest_state_sha256": _canonical_hash(
            {
                key: summaries[key]
                for key in (
                    "backtest_tasks",
                    "orders",
                    "trades",
                )
            }
        ),
        "profile_bindings_sha256": _canonical_hash(
            summaries["profile_bindings"]
        ),
        "canonical_assets_sha256": _canonical_hash(
            summaries["canonical_assets"]
        ),
        "forbidden_tables_sha256": _canonical_hash(
            {
                key: summaries[key]
                for key in (
                    "signal_notifications",
                    "signal_scan_tasks",
                    "review_notes",
                    "backtest_tasks",
                    "profile_bindings",
                    "canonical_assets",
                    "orders",
                    "trades",
                )
            }
        ),
    }
    return counts, hashes


def _event_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_key": row.event_key,
        "event_type": row.event_type,
        "source_mode": row.source_mode,
        "strategy_name": row.strategy_name,
        "strategy_version": row.strategy_version,
        "product": row.product,
        "actual_contract": row.actual_contract,
        "dominant_mapping_date": (
            row.dominant_mapping_date.isoformat()
            if row.dominant_mapping_date
            else None
        ),
        "period": row.period,
        "direction": row.direction,
        "payload": row.payload,
    }


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HtDySchemaV3GateError("runtime_git_identity_invalid") from exc
    return result.stdout.strip()


def _recovery_receipt_hash(path: Path) -> str:
    from app.services.s607_database_recovery import (
        verify_semantic_recovery_receipt,
    )

    receipt = _load_json(path)
    verify_semantic_recovery_receipt(receipt)
    return str(receipt["receipt_hash"])


def _parent_mapping_identity(value: Any) -> dict[str, Any]:
    payload = {
        "mapping_id": value.id,
        "trade_date": value.trade_date.isoformat(),
        "contract_code": str(value.contract_code),
        "data_version": str(value.data_version),
        "created_at": value.created_at.isoformat(),
    }
    return {
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


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HtDySchemaV3GateError("bound_artifact_missing") from exc


def _paths_hash(root: Path, values: list[str]) -> str:
    return _canonical_hash(
        [
            {
                "path": value,
                "sha256": _file_hash(root / value),
            }
            for value in sorted(values)
        ]
    )


def _tree_hash(root: Path) -> str:
    if not root.is_dir():
        raise HtDySchemaV3GateError("bound_artifact_missing")
    return _canonical_hash(
        [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _file_hash(path),
            }
            for path in sorted(item for item in root.rglob("*") if item.is_file())
        ]
    )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _mount_root(path: Path) -> Path:
    current = path.resolve()
    device = current.stat().st_dev
    while current.parent != current:
        if current.parent.stat().st_dev != device:
            break
        current = current.parent
    return current


def _default_trading_day(
    session: Any,
    current: datetime,
    packet: Mapping[str, Any],
) -> date:
    del session
    if current.tzinfo is None:
        raise HtDySchemaV3GateError("detected_at_timezone_required")
    today = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
    days = [date.fromisoformat(str(item)) for item in packet["trading_days"]]
    if today not in days:
        raise HtDySchemaV3GateError("current_day_not_authorized")
    return today


def _runtime_trading_day(
    session: Any,
    current: datetime,
    packet: Mapping[str, Any],
) -> date:
    from app.services.trading_session_clock import TradingSessionClock

    if current.tzinfo is None:
        raise HtDySchemaV3GateError("detected_at_timezone_required")
    days = [date.fromisoformat(str(item)) for item in packet["trading_days"]]
    decision = TradingSessionClock(session).decision(
        product="jm",
        exchange="DCE",
        now=current,
    )
    if decision.trading_day in days:
        return decision.trading_day
    shanghai_day = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
    upcoming = [item for item in days if item >= shanghai_day]
    if upcoming:
        return upcoming[0]
    raise HtDySchemaV3GateError("current_day_not_authorized")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HtDySchemaV3GateError("approval_packet_invalid") from exc
    if not isinstance(value, dict):
        raise HtDySchemaV3GateError("approval_packet_invalid")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise HtDySchemaV3GateError("create_only_path_exists") from exc
    try:
        payload = json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
