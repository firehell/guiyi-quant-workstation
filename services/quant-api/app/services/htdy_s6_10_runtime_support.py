"""Fresh production fact collectors for the S6-10 Runtime Gate."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from app.services.htdy_s6_10_stability import HtDyS610Error


_V5_CLOSED_BAR_CHECKPOINT: Any | None = None
_V6_CLOSED_BAR_CHECKPOINT: Any | None = None


def refresh_one_day_preapproval_bindings(
    session: Any,
    *,
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect volatile schema-v5 facts immediately before parent creation.

    The input is an operator-maintained *scaffold*: it supplies the intended
    code commits, artifact paths and fail-closed feature-flag contract.  It
    must never supply a copied database/profile baseline.  Those values are
    read here from the live database in the same pre-approval operation.

    This function is deliberately read-only.  The caller owns a read-only
    transaction and publishes the resulting JSON with create-only semantics.
    """

    from sqlalchemy import text

    from app.services.htdy_s6_08_runtime_gate import _database_state
    from guiyi_quant.indicators import (
        closed_bar_observation_policy_sha256,
        htdy_original_source_sha256,
    )

    refreshed = deepcopy(dict(bindings))
    paths = refreshed.get("artifact_paths")
    if not isinstance(paths, Mapping):
        raise HtDyS610Error("artifact_paths_missing")
    counts, hashes = _database_state(session)
    refreshed.update(
        {
            "database_revision": str(
                session.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            ),
            "profile_sha256": _profile_hash(session),
            "indicator_source_sha256": htdy_original_source_sha256(),
            "policy_sha256": closed_bar_observation_policy_sha256(),
            "s6_07_receipt_sha256": _file_hash(
                _required_file(paths, "s6_07_receipt")
            ),
            "s6_08_receipt_sha256": _file_hash(
                _required_file(paths, "s6_08_receipt")
            ),
            "s6_09_receipt_sha256": _file_hash(
                _required_file(paths, "s6_09_receipt")
            ),
            "launchd_sha256": _file_hash(
                _required_file(paths, "runtime_launchd")
            ),
            "approval_c2_approved_signers_sha256": _file_hash(
                _required_file(paths, "approval_c2_approved_signers")
            ),
            **collect_bound_s607_artifact_hashes(paths),
            "baseline_counts": _selected_counts(counts),
            "baseline_hashes": _selected_hashes(hashes),
            "baseline_max_ids": _baseline_max_ids(session),
        }
    )
    for forbidden in (
        "backup_receipt_sha256",
        "restore_receipt_sha256",
        "restore_audit_receipt_sha256",
    ):
        refreshed.pop(forbidden, None)
    return refreshed


def collect_current_bindings(
    session: Any,
    *,
    parent_packet: Mapping[str, Any],
    parent_packet_path: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Recollect every binding from its bound source, never from a packet hash."""

    from sqlalchemy import text
    from app.services.htdy_s6_08_runtime_gate import _database_state
    from guiyi_quant.indicators import (
        htdy_original_source_sha256,
        realtime_observation_policy_sha256,
    )

    expected = parent_packet.get("bindings")
    if not isinstance(expected, Mapping):
        raise HtDyS610Error("parent_bindings_invalid")
    paths = expected.get("artifact_paths")
    if not isinstance(paths, Mapping):
        raise HtDyS610Error("artifact_paths_missing")
    runtime_root = _required_directory(paths, "runtime_root")
    source_root = _required_directory(paths, "source_root")
    revision = str(
        session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    )
    counts, hashes = _database_state(session)
    expected_max_ids = dict(expected.get("baseline_max_ids") or {})
    current_max_ids = _baseline_max_ids(session)
    if expected_max_ids:
        for key in (
            "signal_notifications",
            "review_notes",
            "orders",
            "trades",
        ):
            if current_max_ids.get(key) != expected_max_ids.get(key):
                raise HtDyS610Error(f"{key}_max_id_drift")
        allowed_events = _events_after(
            session,
            int(expected_max_ids.get("signal_events", -1)),
        )
        if allowed_events:
            authorized_days = {
                date.fromisoformat(str(item))
                for item in parent_packet.get("trading_days", ())
            }
            if any(
                event.dominant_mapping_date not in authorized_days
                for event in allowed_events
            ):
                raise HtDyS610Error("event_outside_authorized_window")
            _verify_exact_events(
                allowed_events,
                allowed_mappings=_mapping_contracts(
                    session,
                    tuple(
                        sorted(
                            {
                                event.dominant_mapping_date
                                for event in allowed_events
                                if event.dominant_mapping_date is not None
                            }
                        )
                    ),
                ),
                indicator_source_sha256=str(
                    expected.get("indicator_source_sha256") or ""
                ),
                policy_sha256=str(expected.get("policy_sha256") or ""),
            )
        counts["signal_events"] -= len(allowed_events)
    else:
        expected_max_ids = current_max_ids
    flags = {
        "live_runtime": _enabled(environ, "GUIYI_LIVE_RUNTIME_ENABLED"),
        "signal_events": _enabled(
            environ,
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
        ),
        "wechat_autosend": _enabled(
            environ,
            "GUIYI_WECHAT_AUTOSEND_ENABLED",
        ),
        "after_market_automation": _enabled(
            environ,
            "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED",
        ),
    }
    days = tuple(
        date.fromisoformat(str(item))
        for item in parent_packet.get("trading_days", ())
    )
    return {
        "runtime_commit": _git(runtime_root, "rev-parse", "HEAD"),
        "runtime_tree": _git_tree_hash(runtime_root),
        "runtime_tracked_clean": (
            _git(
                runtime_root,
                "status",
                "--porcelain=v1",
            )
            == ""
        ),
        "source_commit": _git(source_root, "rev-parse", "HEAD"),
        "source_tree": _git_tree_hash(source_root),
        "database_revision": revision,
        "profile_sha256": _profile_hash(session),
        "indicator_source_sha256": htdy_original_source_sha256(),
        "policy_sha256": realtime_observation_policy_sha256(),
        "s6_07_receipt_sha256": _file_hash(
            _required_file(paths, "s6_07_receipt")
        ),
        "s6_08_receipt_sha256": _file_hash(
            _required_file(paths, "s6_08_receipt")
        ),
        "s6_09_receipt_sha256": _file_hash(
            _required_file(paths, "s6_09_receipt")
        ),
        "backup_receipt_sha256": _file_hash(
            _required_file(paths, "backup_receipt")
        ),
        "restore_receipt_sha256": _file_hash(
            _required_file(paths, "restore_receipt")
        ),
        "restore_audit_receipt_sha256": _file_hash(
            _required_file(paths, "restore_audit_receipt")
        ),
        "calendar_sha256": (
            _canonical_hash(parent_packet["calendar_rows"])
            if parent_packet.get("_prepare_allow_missing_calendar") is True
            else _calendar_hash(session, days)
        ),
        "launchd_sha256": _file_hash(
            _required_file(paths, "runtime_launchd")
        ),
        "observer_launchd_sha256": _file_hash(
            _required_file(paths, "observer_launchd")
        ),
        "deployment_packet_sha256": _file_hash(
            _required_file(paths, "deployment_packet")
        ),
        "s6_07_rebind_packet_sha256": _file_hash(
            _required_file(paths, "s6_07_rebind_packet")
        ),
        "s6_07_enable_packet_sha256": _file_hash(
            _required_file(paths, "s6_07_enable_packet")
        ),
        "fault_schedule_sha256": _file_hash(
            _required_file(paths, "fault_schedule_json")
        ),
        "approval_c_approved_signers_sha256": _file_hash(
            _required_file(paths, "approval_c_approved_signers")
        ),
        "feature_flags": flags,
        "baseline_counts": _selected_counts(counts),
        "baseline_hashes": _selected_hashes(hashes),
        "baseline_max_ids": expected_max_ids,
        "artifact_paths": deepcopy(dict(paths)),
        "parent_packet_path": str(parent_packet_path.resolve(strict=False)),
    }


def collect_current_daily_state(
    session: Any,
    *,
    parent_packet: Mapping[str, Any],
    trading_day: date,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.data_center import MainContractMap, TradingSession
    from app.models.signal import SignalEvent
    from app.services.htdy_s6_08_runtime_gate import _database_state
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
        raise HtDyS610Error("mapping_duplicate_or_missing")
    mapping = mappings[0]
    sessions = list(
        session.scalars(
            select(TradingSession)
            .where(
                TradingSession.exchange_code == "DCE",
                TradingSession.instrument_symbol == "jm",
                TradingSession.is_active.is_(True),
            )
            .order_by(TradingSession.id)
        )
    )
    if not sessions:
        raise HtDyS610Error("session_geometry_missing")
    counts, hashes = _database_state(session)
    day_events = list(
        session.scalars(
            select(SignalEvent).where(
                SignalEvent.source_mode == "live_realtime_repainting",
                SignalEvent.strategy_name
                == "htdy_original_realtime_first_seen",
                SignalEvent.strategy_version == "v1.0",
                SignalEvent.product == "jm",
                SignalEvent.period == "15m",
                SignalEvent.dominant_mapping_date == trading_day,
            )
        )
    )
    if any(event.event_type != "signal_created" for event in day_events):
        raise HtDyS610Error("non_created_htdy_event_forbidden")
    expected = dict(parent_packet.get("bindings") or {})
    _verify_exact_events(
        day_events,
        allowed_mappings={trading_day: str(mapping.contract_code)},
        indicator_source_sha256=str(
            expected.get("indicator_source_sha256") or ""
        ),
        policy_sha256=str(expected.get("policy_sha256") or ""),
    )
    beginning_counts = _selected_counts(counts)
    beginning_counts["signal_events"] -= len(day_events)
    beginning_state = {
        "counts": beginning_counts,
        "hashes": _selected_hashes(hashes),
        "notification_count": counts["signal_notifications"],
    }
    source_facts = {
        "profile_sha256": _profile_hash(session),
        "indicator_source_sha256": htdy_original_source_sha256(),
        "policy_sha256": realtime_observation_policy_sha256(),
        "wechat_autosend": _enabled(
            environ,
            "GUIYI_WECHAT_AUTOSEND_ENABLED",
        ),
    }
    return {
        "trading_day": trading_day,
        "actual_contract": str(mapping.contract_code),
        "mapping_sha256": _canonical_hash(
            {
                "trade_date": mapping.trade_date.isoformat(),
                "contract_code": mapping.contract_code,
                "rank": mapping.rank,
                "rule": mapping.rule,
                "provider": mapping.provider,
                "data_version": mapping.data_version,
            }
        ),
        "session_geometry_sha256": _canonical_hash(
            [
                {
                    "session_id": item.id,
                    "session_name": item.session_name,
                    "start_time": item.start_time.isoformat(),
                    "end_time": item.end_time.isoformat(),
                    "crosses_midnight": item.crosses_midnight,
                }
                for item in sessions
            ]
        ),
        "source_facts_sha256": _canonical_hash(source_facts),
        "beginning_state": beginning_state,
        "counts": _selected_counts(counts),
        "hashes": _selected_hashes(hashes),
        "new_events": [_event_fact(event) for event in day_events],
        "event_ids": [int(event.id) for event in day_events],
    }


def resolve_runtime_trading_day(
    session: Any,
    current: datetime,
    packet: Mapping[str, Any],
) -> date:
    from app.services.htdy_s6_08_runtime_gate import _runtime_trading_day

    try:
        return _runtime_trading_day(session, current, packet)
    except Exception as exc:
        raise HtDyS610Error(str(exc) or "current_day_not_authorized") from exc


def runtime_handler(session: Any) -> Any:
    from app.services.htdy_runtime_event_handler import HtDyRuntimeEventHandler

    return HtDyRuntimeEventHandler(session)


def runtime_handler_v5(session: Any) -> Any:
    from app.services.htdy_runtime_event_handler import (
        ClosedBarEvaluationCheckpoint,
        HtDyClosedBarRuntimeEventHandler,
    )

    global _V5_CLOSED_BAR_CHECKPOINT
    if _V5_CLOSED_BAR_CHECKPOINT is None:
        _V5_CLOSED_BAR_CHECKPOINT = ClosedBarEvaluationCheckpoint()
    return HtDyClosedBarRuntimeEventHandler(
        session,
        checkpoint=_V5_CLOSED_BAR_CHECKPOINT,
    )


def runtime_handler_v6(
    session: Any,
    *,
    allowed_bucket_ends: set[datetime],
) -> Any:
    from app.services.htdy_runtime_event_handler import (
        ClosedBarEvaluationCheckpoint,
        HtDyClosedBarRuntimeEventHandler,
    )

    global _V6_CLOSED_BAR_CHECKPOINT
    if _V6_CLOSED_BAR_CHECKPOINT is None:
        _V6_CLOSED_BAR_CHECKPOINT = ClosedBarEvaluationCheckpoint()
    return HtDyClosedBarRuntimeEventHandler(
        session,
        checkpoint=_V6_CLOSED_BAR_CHECKPOINT,
        allowed_bucket_ends=allowed_bucket_ends,
    )


def collect_current_one_day_bindings(
    session: Any,
    *,
    parent_packet: Mapping[str, Any],
    parent_packet_path: Path,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Refresh schema-v5 bindings without backup or restore prerequisites."""

    from sqlalchemy import select, text

    from app.models.signal import SignalEvent, SignalNotification
    from app.services.htdy_s6_08_runtime_gate import _database_state
    from guiyi_quant.indicators import (
        closed_bar_observation_policy_sha256,
        htdy_original_source_sha256,
    )

    expected = parent_packet.get("bindings")
    if not isinstance(expected, Mapping):
        raise HtDyS610Error("parent_bindings_invalid")
    paths = expected.get("artifact_paths")
    if not isinstance(paths, Mapping):
        raise HtDyS610Error("artifact_paths_missing")
    runtime_root = _required_directory(paths, "runtime_root")
    source_root = _required_directory(paths, "source_root")
    counts, hashes = _database_state(session)
    target_day = date.fromisoformat(str(parent_packet["trading_days"][0]))
    actual_contract = _mapping_contracts(session, (target_day,))[target_day]
    allowed_bucket_ends: set[datetime] | None = None
    if parent_packet.get("schema_version") == 7:
        activation_path = Path(
            str(environ.get("GUIYI_HTDY_S610_ACTIVATION_RECEIPT") or "")
        )
        try:
            activation = json.loads(activation_path.read_text(encoding="utf-8"))
            allowed_bucket_ends = {
                datetime.fromisoformat(value)
                for value in activation["expected_bucket_ends"]
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HtDyS610Error("activation_allowlist_invalid") from exc
    day_events = list(
        session.scalars(
            select(SignalEvent).where(
                SignalEvent.strategy_name
                == "htdy_original_realtime_first_seen",
                SignalEvent.strategy_version == "v1.1",
                SignalEvent.product == "jm",
                SignalEvent.period == "15m",
                SignalEvent.dominant_mapping_date == target_day,
            )
        )
    )
    _verify_exact_closed_bar_events(
        day_events,
        target_day=target_day,
        actual_contract=actual_contract,
        allowed_bucket_ends=allowed_bucket_ends,
        indicator_source_sha256=str(expected["indicator_source_sha256"]),
        policy_sha256=str(expected["policy_sha256"]),
    )
    event_ids = {event.id for event in day_events}
    notifications = (
        list(
            session.scalars(
                select(SignalNotification).where(
                    SignalNotification.event_id.in_(event_ids)
                )
            )
        )
        if event_ids
        else []
    )
    if (
        len({item.event_id for item in notifications})
        != len(notifications)
        or any(
            not _exact_one_day_notification(
                item,
                events_by_id={event.id: event for event in day_events},
                parent_hash=str(parent_packet["packet_hash"]),
            )
            for item in notifications
        )
        or sum(
            ((item.payload or {}).get("s6_10_bounded") or {}).get("status")
            != "capped"
            for item in notifications
        )
        > 23
    ):
        raise HtDyS610Error("schema_v5_notification_bound_drift")
    counts["signal_events"] -= len(day_events)
    counts["signal_notifications"] -= len(notifications)
    refreshed = deepcopy(dict(expected))
    refreshed.update(
        {
            "runtime_commit": _git(runtime_root, "rev-parse", "HEAD"),
            "runtime_tree": _git_tree_hash(runtime_root),
            "runtime_tracked_clean": (
                _git(runtime_root, "status", "--porcelain=v1") == ""
            ),
            "source_commit": _git(source_root, "rev-parse", "HEAD"),
            "source_tree": _git_tree_hash(source_root),
            "database_revision": str(
                session.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            ),
            "profile_sha256": _profile_hash(session),
            "indicator_source_sha256": htdy_original_source_sha256(),
            "policy_sha256": closed_bar_observation_policy_sha256(),
            "s6_07_receipt_sha256": _file_hash(
                _required_file(paths, "s6_07_receipt")
            ),
            "s6_08_receipt_sha256": _file_hash(
                _required_file(paths, "s6_08_receipt")
            ),
            "s6_09_receipt_sha256": _file_hash(
                _required_file(paths, "s6_09_receipt")
            ),
            "calendar_sha256": _file_hash(
                _required_file(paths, "calendar_window")
            ),
            "launchd_sha256": _file_hash(
                _required_file(paths, "runtime_launchd")
            ),
            "observer_launchd_sha256": _file_hash(
                _required_file(paths, "observer_identity")
            ),
            "delivery_launchd_sha256": _file_hash(
                _required_file(paths, "delivery_identity")
            ),
            "deployment_packet_sha256": _file_hash(
                _required_file(paths, "deployment_packet")
            ),
            "approval_c2_approved_signers_sha256": _file_hash(
                _required_file(paths, "approval_c2_approved_signers")
            ),
            **collect_bound_s607_artifact_hashes(paths),
            "feature_flags": {
                "live_runtime": _enabled(
                    environ, "GUIYI_LIVE_RUNTIME_ENABLED"
                ),
                "signal_events": _enabled(
                    environ, "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"
                ),
                "wechat_autosend": _enabled(
                    environ, "GUIYI_WECHAT_AUTOSEND_ENABLED"
                ),
                "after_market_automation": _enabled(
                    environ, "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED"
                ),
                "bounded_wecom_delivery": _enabled(
                    environ, "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED"
                ),
            },
            "baseline_counts": _selected_counts(counts),
            "baseline_hashes": _selected_hashes(
                hashes,
                legacy=(
                    "forbidden_tables"
                    in dict(expected.get("baseline_hashes") or {})
                ),
            ),
            "parent_packet_path": str(
                parent_packet_path.resolve(strict=False)
            ),
        }
    )
    for forbidden in (
        "backup_receipt_sha256",
        "restore_receipt_sha256",
        "restore_audit_receipt_sha256",
    ):
        refreshed.pop(forbidden, None)
    return refreshed


def collect_bound_s607_artifact_hashes(
    paths: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "s6_07_rebind_packet_sha256": _file_hash(
            _required_file(paths, "s6_07_rebind_packet")
        ),
        "s6_07_enable_packet_sha256": _file_hash(
            _required_file(paths, "s6_07_enable_packet")
        ),
    }


def _selected_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return {
        key: int(counts[key])
        for key in (
            "signal_events",
            "signal_notifications",
            "review_notes",
            "orders",
            "trades",
        )
    }


def _selected_hashes(
    hashes: Mapping[str, str],
    *,
    legacy: bool = False,
) -> dict[str, str]:
    selected = {
        "profile_bindings": str(hashes["profile_bindings_sha256"]),
        "canonical_assets": str(hashes["canonical_assets_sha256"]),
    }
    if not legacy and "immutable_tables_sha256" in hashes:
        selected["immutable_tables"] = str(
            hashes["immutable_tables_sha256"]
        )
    else:
        selected["forbidden_tables"] = str(
            hashes["forbidden_tables_sha256"]
        )
    return selected


def _baseline_max_ids(session: Any) -> dict[str, int]:
    from sqlalchemy import text

    tables = {
        "signal_events": "signal_events",
        "signal_notifications": "signal_notifications",
        "review_notes": "review_notes",
        "orders": "backtest_orders",
        "trades": "backtest_trades",
    }
    return {
        key: int(
            session.execute(
                text(f"SELECT coalesce(max(id), 0) FROM {table}")  # noqa: S608
            ).scalar_one()
        )
        for key, table in tables.items()
    }


def _events_after(session: Any, baseline_id: int) -> list[Any]:
    from sqlalchemy import select

    from app.models.signal import SignalEvent

    if baseline_id < 0:
        raise HtDyS610Error("baseline_event_max_id_invalid")
    return list(
        session.scalars(
            select(SignalEvent)
            .where(SignalEvent.id > baseline_id)
            .order_by(SignalEvent.id)
        )
    )


def _verify_exact_events(
    events: list[Any],
    *,
    allowed_mappings: Mapping[date, str] | None = None,
    indicator_source_sha256: str | None = None,
    policy_sha256: str | None = None,
) -> None:
    if len(events) > 160:
        raise HtDyS610Error("signal_event_limit_exceeded")
    for event in events:
        lineage = dict(
            (getattr(event, "payload", None) or {}).get("formal_lineage") or {}
        )
        indicator = dict(lineage.get("indicator") or {})
        detection = dict(lineage.get("live_detection_snapshot") or {})
        if (
            event.event_type != "signal_created"
            or event.source_mode != "live_realtime_repainting"
            or event.strategy_name != "htdy_original_realtime_first_seen"
            or event.strategy_version != "v1.0"
            or event.product != "jm"
            or event.period != "15m"
            or event.direction not in {"long", "short"}
            or event.actual_contract is None
            or event.dominant_mapping_date is None
            or lineage.get("schema_version") != "signal_review_lineage_v2"
            or indicator.get("indicator_code")
            != "huotian_dayou_original_v0"
            or indicator.get("indicator_version") != "original-v0"
            or indicator.get("signal_policy")
            != "htdy_original_xma_15m_first_seen_v1"
            or indicator.get("future_looking") is not True
            or indicator.get("repainting_accepted") is not True
            or indicator.get("first_seen_no_retraction") is not True
            or indicator.get("historical_backtest_allowed") is not False
            or (
                indicator_source_sha256 is not None
                and detection.get("source_sha256")
                != indicator_source_sha256
            )
            or (
                policy_sha256 is not None
                and detection.get("policy_sha256") != policy_sha256
            )
            or (
                allowed_mappings is not None
                and allowed_mappings.get(event.dominant_mapping_date)
                != event.actual_contract
            )
        ):
            raise HtDyS610Error("non_exact_event_forbidden")


def _verify_exact_closed_bar_events(
    events: list[Any],
    *,
    target_day: date,
    actual_contract: str | None = None,
    allowed_bucket_ends: set[datetime] | None = None,
    indicator_source_sha256: str | None = None,
    policy_sha256: str | None = None,
) -> None:
    from app.services.htdy_s6_10_one_day_notifications import (
        event_decision_bucket_end,
    )

    if len(events) > 23:
        raise HtDyS610Error("closed_bar_event_delta_invalid")
    for event in events:
        lineage = dict(
            (getattr(event, "payload", None) or {}).get("formal_lineage")
            or {}
        )
        indicator = dict(lineage.get("indicator") or {})
        detection = dict(lineage.get("live_detection_snapshot") or {})
        decision_close = event_decision_bucket_end(event)
        try:
            detected_at = datetime.fromisoformat(
                str(detection.get("detected_at") or "")
            )
        except ValueError:
            detected_at = None
        if (
            event.event_type != "signal_created"
            or event.source_mode != "live_realtime_repainting"
            or event.strategy_name
            != "htdy_original_realtime_first_seen"
            or event.strategy_version != "v1.1"
            or event.product != "jm"
            or event.period != "15m"
            or event.direction not in {"long", "short"}
            or event.dominant_mapping_date != target_day
            or (
                actual_contract is not None
                and event.actual_contract != actual_contract
            )
            or lineage.get("schema_version") != "signal_review_lineage_v2"
            or decision_close is None
            or (
                allowed_bucket_ends is not None
                and decision_close not in allowed_bucket_ends
            )
            or getattr(event, "bar_end", None) is None
            or event.bar_end > decision_close
            or detected_at is None
            or detected_at.tzinfo is None
            or detected_at < decision_close
            or indicator.get("indicator_code")
            != "huotian_dayou_original_v0"
            or indicator.get("indicator_version") != "original-v0"
            or indicator.get("signal_policy")
            != "htdy_original_xma_15m_close_first_seen_v1"
            or indicator.get("partial_allowed") is not False
            or indicator.get("live_confirmed_required") is not True
            or indicator.get("decision_trigger")
            != "confirmed_15m_close"
            or indicator.get("historical_backtest_allowed") is not False
            or indicator.get("auto_order") is not False
            or (
                indicator_source_sha256 is not None
                and detection.get("source_sha256")
                != indicator_source_sha256
            )
            or (
                policy_sha256 is not None
                and detection.get("policy_sha256") != policy_sha256
            )
        ):
            raise HtDyS610Error("closed_bar_event_delta_invalid")


def _exact_one_day_notification(
    notification: Any,
    *,
    events_by_id: Mapping[int, Any],
    parent_hash: str,
) -> bool:
    from app.signal.events import signal_event_payload
    from app.signal.stage9_gate import evaluate_stage9_signal_event_gate
    from app.signal.stage9_wechat import build_stage9_wechat_payload_from_basis
    from app.services.htdy_s6_09_wecom_gate import canonical_hash

    event = events_by_id.get(notification.event_id)
    payload = dict(notification.payload or {})
    capped = dict(payload.get("s6_10_bounded") or {})
    authorization = dict(payload.get("s6_10_authorization") or {})
    expected_dedupe = (
        f"enterprise_wechat:signal_event:{notification.event_id}"
    )
    gate = evaluate_stage9_signal_event_gate(event) if event is not None else {}
    message = (
        build_stage9_wechat_payload_from_basis(gate["payload_basis"])
        if gate.get("allowed")
        else None
    )
    parent_bound = (
        capped.get("status") == "capped"
        and capped.get("parent_hash") == parent_hash
    ) or (
        authorization.get("scope") == "s6_10_one_day_bounded"
        and authorization.get("parent_hash") == parent_hash
        and authorization.get("event_id") == notification.event_id
        and authorization.get("dedupe_key") == expected_dedupe
        and authorization.get("event_sha256")
        == canonical_hash(signal_event_payload(event))
        and message is not None
        and authorization.get("rendered_message_sha256")
        == canonical_hash(message)
    )
    return bool(
        event is not None
        and notification.signal_id == event.signal_id
        and notification.event_type == event.event_type
        and notification.channel == "enterprise_wechat"
        and notification.dedupe_key == expected_dedupe
        and notification.status
        in {"pending", "retry_pending", "sent", "failed", "skipped"}
        and notification.max_attempts == 3
        and 0 <= notification.attempt_count <= 3
        and parent_bound
    )


def _mapping_contracts(
    session: Any,
    days: tuple[date, ...],
) -> dict[date, str]:
    from sqlalchemy import select

    from app.models.data_center import MainContractMap

    rows = list(
        session.scalars(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == "jm",
                MainContractMap.trade_date.in_(days),
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
        )
    )
    result: dict[date, str] = {}
    for row in rows:
        if row.trade_date in result:
            raise HtDyS610Error("mapping_duplicate_or_missing")
        result[row.trade_date] = str(row.contract_code)
    if set(result) != set(days):
        raise HtDyS610Error("mapping_duplicate_or_missing")
    return result


def _event_fact(event: Any) -> dict[str, Any]:
    lineage = dict((event.payload or {}).get("formal_lineage") or {})
    return {
        "id": event.id,
        "event_type": event.event_type,
        "source_mode": event.source_mode,
        "strategy_name": event.strategy_name,
        "strategy_version": event.strategy_version,
        "product": event.product,
        "period": event.period,
        "direction": event.direction,
        "actual_contract": event.actual_contract,
        "dominant_mapping_date": (
            event.dominant_mapping_date.isoformat()
            if event.dominant_mapping_date
            else None
        ),
        "formal_lineage": deepcopy(lineage),
    }


def _profile_hash(session: Any) -> str:
    from sqlalchemy import select

    from app.models.data_center import MarketDataFile, ProfileActiveBinding

    bindings = list(
        session.scalars(
            select(ProfileActiveBinding)
            .where(ProfileActiveBinding.profile_id == "live_observation_v1")
            .order_by(ProfileActiveBinding.id)
        )
    )
    payload = []
    for binding in bindings:
        market_file = session.get(MarketDataFile, binding.market_data_file_id)
        if market_file is None:
            raise HtDyS610Error("profile_file_missing")
        payload.append(
            {
                "binding_id": binding.id,
                "market_data_file_id": market_file.id,
                "binding_status": binding.binding_status,
                "symbol": market_file.instrument_symbol,
                "contract": market_file.contract_code,
                "period": market_file.period,
                "data_version": market_file.data_version,
                "checksum": market_file.checksum,
                "quality_status": market_file.quality_status,
                "data_role": market_file.data_role,
            }
        )
    if not payload:
        raise HtDyS610Error("profile_binding_missing")
    return _canonical_hash(payload)


def _calendar_hash(session: Any, days: tuple[date, ...]) -> str:
    from sqlalchemy import func, select

    from app.models.data_center import TradingCalendar

    rows = list(
        session.scalars(
            select(TradingCalendar)
            .where(
                TradingCalendar.exchange_code == "DCE",
                TradingCalendar.trade_date.in_(days),
            )
            .order_by(TradingCalendar.trade_date)
        )
    )
    payload = []
    for row in rows:
        previous = session.scalar(
            select(func.max(TradingCalendar.trade_date)).where(
                TradingCalendar.exchange_code == "DCE",
                TradingCalendar.is_trading_day.is_(True),
                TradingCalendar.trade_date < row.trade_date,
            )
        )
        if previous is None:
            raise HtDyS610Error("calendar_previous_trading_day_missing")
        payload.append({
            "trade_date": row.trade_date.isoformat(),
            "is_trading_day": row.is_trading_day,
            "has_night_session": row.has_night_session,
            "provider": row.provider,
            "night_session_date": previous.isoformat(),
        })
    if tuple(item["trade_date"] for item in payload) != tuple(
        day.isoformat() for day in days
    ):
        raise HtDyS610Error("calendar_window_incomplete")
    return _canonical_hash(payload)


def _required_directory(paths: Mapping[str, Any], key: str) -> Path:
    path = Path(str(paths.get(key) or "")).expanduser().resolve(strict=False)
    if not path.is_dir():
        raise HtDyS610Error(f"{key}_unavailable")
    return path


def _required_file(paths: Mapping[str, Any], key: str) -> Path:
    path = Path(str(paths.get(key) or "")).expanduser().resolve(strict=False)
    if not path.is_file():
        raise HtDyS610Error(f"{key}_unavailable")
    return path


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HtDyS610Error("bound_artifact_unavailable") from exc


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
        raise HtDyS610Error("git_identity_invalid") from exc
    return result.stdout.strip()


def _git_tree_hash(root: Path) -> str:
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    return hashlib.sha256(tree.encode("utf-8")).hexdigest()


def _enabled(environ: Mapping[str, str], key: str) -> bool:
    return str(environ.get(key) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
