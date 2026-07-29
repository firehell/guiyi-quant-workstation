"""Pure contracts and create-only evidence for HTDY S6-10.

This module does not deploy code, mutate Runtime configuration, write market
data, create SignalEvent rows, or send notifications.  It freezes and verifies
the facts required by the separately approved five-trading-day observation
Gate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 4
TASK_ID = "JM-LIVE-STABILITY-S6-10"
PARENT_PACKET_TYPE = "htdy_s6_10_five_day_parent"
CHILD_PACKET_TYPE = "htdy_s6_10_daily_child"
STRATEGY_CODE = "htdy_original_realtime_first_seen"
STRATEGY_VERSION = "v1.0"
INDICATOR_CODE = "huotian_dayou_original_v0"
INDICATOR_VERSION = "original-v0"
SIGNAL_POLICY = "htdy_original_xma_15m_first_seen_v1"
SOURCE_MODE = "live_realtime_repainting"
PRODUCT = "jm"
PERIOD = "15m"
REPAINT_SCAN_BARS = 27
DAILY_BUCKET_LIMIT = 23
WINDOW_TRADING_DAYS = 5
THEORETICAL_OBSERVATION_BAR_LIMIT = (
    REPAINT_SCAN_BARS + DAILY_BUCKET_LIMIT * WINDOW_TRADING_DAYS
)
MAX_EVENT_COUNT = 160
NOTIFICATION_BASELINE = 2
REQUIRED_DB_REVISION = "20260721_0025"
APPROVAL_C_SIGNER_FINGERPRINT = (
    "SHA256:nfzIHbQn/kmFXMFnQ54jUA/zUHcP2bOBzo/UeBTG5bw"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")


class HtDyS610Error(RuntimeError):
    """Fail-closed S6-10 contract violation."""


@dataclass(frozen=True)
class HtDyS610ParentPacket:
    """Typed wrapper used by callers that prefer an explicit packet object."""

    payload: Mapping[str, Any]


@dataclass(frozen=True)
class HtDyS610DailyChild:
    """Typed wrapper used by callers that prefer an explicit child object."""

    payload: Mapping[str, Any]


def canonical_hash(payload: Mapping[str, Any]) -> str:
    normalized = {
        str(key): deepcopy(value)
        for key, value in payload.items()
        if key
        not in {
            "packet_hash",
            "sample_hash",
            "seal_hash",
            "receipt_hash",
            "bundle_hash",
            "instruction_hash",
        }
    }
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_parent_packet(
    *,
    trading_days: Sequence[date],
    generated_at: datetime,
    bindings: Mapping[str, Any],
    calendar_rows: Sequence[Mapping[str, Any]],
    fault_schedule: Mapping[str, Any],
) -> dict[str, Any]:
    rows = tuple(deepcopy(dict(row)) for row in calendar_rows)
    raw_days = tuple(trading_days)
    first_night = (
        date.fromisoformat(str(rows[0].get("night_session_date")))
        if rows
        else None
    )
    days = _validate_window(
        raw_days,
        generated_at=generated_at,
        first_night_session_date=first_night,
    )
    if tuple(row.get("trade_date") for row in rows) != tuple(
        day.isoformat() for day in days
    ) or any(
        row.get("is_trading_day") is not True
        or not isinstance(row.get("night_session_date"), str)
        or date.fromisoformat(str(row["night_session_date"])) >= day
        for row, day in zip(rows, days, strict=True)
    ):
        raise HtDyS610Error("calendar_window_invalid")
    frozen_bindings = _validate_bindings(bindings)
    _validate_fault_schedule(fault_schedule)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "packet_type": PARENT_PACKET_TYPE,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "trading_days": [day.isoformat() for day in days],
        "window_start": _night_session_start(
            days[0],
            first_night,
        ).isoformat(),
        "window_end_trading_day": days[-1].isoformat(),
        "strategy_identity": {
            "product": PRODUCT,
            "period": PERIOD,
            "strategy_code": STRATEGY_CODE,
            "strategy_version": STRATEGY_VERSION,
            "indicator_code": INDICATOR_CODE,
            "indicator_version": INDICATOR_VERSION,
            "signal_policy": SIGNAL_POLICY,
            "source_mode": SOURCE_MODE,
            "purpose": "observation_only",
            "future_looking": True,
            "repainting_accepted": True,
            "first_seen_no_retraction": True,
            "historical_backtest_allowed": False,
            "auto_order": False,
        },
        "calendar_rows": list(rows),
        "bindings": frozen_bindings,
        "fault_schedule": deepcopy(dict(fault_schedule)),
        "repaint_scan_bars": REPAINT_SCAN_BARS,
        "daily_bucket_limit": DAILY_BUCKET_LIMIT,
        "theoretical_observation_bar_limit": (
            THEORETICAL_OBSERVATION_BAR_LIMIT
        ),
        "max_event_count": MAX_EVENT_COUNT,
        "notification_baseline": NOTIFICATION_BASELINE,
        "allowed_writes": [
            "confirmed_passed_jm_actual_contract_live_1m",
            "existing_live_aggregation",
            "exact_htdy_first_seen_signal_created",
            "s6_07_eod_archive_checkpoint_receipt",
            "external_create_only_s6_10_evidence",
        ],
        "forbidden_writes": [
            "signal_changed",
            "non_exact_signal_event",
            "signal_notification",
            "review_note",
            "order",
            "trade",
            "migration",
            "live_to_historical_direct_promotion",
        ],
        "approval_required": "Approval C",
        "authorization_consumed": False,
        "long_running_ready": False,
        "trading_ready": False,
        "notification_ready": False,
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def verify_parent_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_bindings: Mapping[str, Any],
    now: datetime,
    allow_started: bool = False,
) -> None:
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise HtDyS610Error("schema_version_invalid")
    if packet.get("packet_type") != PARENT_PACKET_TYPE:
        raise HtDyS610Error("packet_type_invalid")
    expected_hash = canonical_hash(packet)
    if not _sha256(approval_hash) or packet.get("packet_hash") != approval_hash:
        raise HtDyS610Error("approval_hash_invalid")
    if expected_hash != approval_hash:
        raise HtDyS610Error("packet_hash_invalid")
    days = tuple(date.fromisoformat(str(item)) for item in packet["trading_days"])
    rows = tuple(packet.get("calendar_rows") or ())
    first_night = (
        date.fromisoformat(str(rows[0].get("night_session_date")))
        if rows and isinstance(rows[0], Mapping)
        else None
    )
    _validate_window(
        days,
        generated_at=_parse_datetime(packet["generated_at"]),
        first_night_session_date=first_night,
    )
    if now.tzinfo is None:
        raise HtDyS610Error("now_timezone_required")
    if (
        not allow_started
        and now.astimezone(SHANGHAI)
        >= _night_session_start(days[0], first_night)
    ):
        raise HtDyS610Error("window_already_started")
    if deepcopy(dict(current_bindings)) != packet.get("bindings"):
        raise HtDyS610Error("parent_bindings_drift")
    _validate_bindings(current_bindings)
    if packet.get("authorization_consumed") is not False:
        raise HtDyS610Error("authorization_consumed")


def verify_approval_c_bundle(
    bundle_path: Path,
    *,
    approval_c_hash: str,
    parent_packet: Mapping[str, Any],
    parent_packet_path: Path,
    approval_receipt_path: Path,
    approval_signature_path: Path,
    approved_signers_path: Path,
    signature_verifier: Callable[[bytes, Path, Path], bool] | None = None,
    trust_root_verifier: Callable[[Path], bool] | None = None,
) -> None:
    """Verify the separately approved aggregate authorization and its artifacts."""

    bundle = _load_json(bundle_path)
    if bundle.get("schema_version") != 1 or bundle.get("task_id") != TASK_ID:
        raise HtDyS610Error("approval_c_bundle_invalid")
    if not _sha256(approval_c_hash) or bundle.get("bundle_hash") != approval_c_hash:
        raise HtDyS610Error("approval_c_hash_invalid")
    if canonical_hash(bundle) != approval_c_hash:
        raise HtDyS610Error("approval_c_bundle_hash_invalid")
    parent_hash = str(parent_packet.get("packet_hash") or "")
    if (
        bundle.get("parent_packet_hash") != parent_hash
        or Path(str(bundle.get("parent_packet_path") or "")).resolve(strict=False)
        != parent_packet_path.resolve(strict=True)
    ):
        raise HtDyS610Error("approval_c_parent_binding_invalid")
    paths = dict((parent_packet.get("bindings") or {}).get("artifact_paths") or {})
    for bundle_key, path_key in (
        ("deployment_packet", "deployment_packet"),
        ("s6_07_rebind_packet", "s6_07_rebind_packet"),
        ("s6_07_enable_packet", "s6_07_enable_packet"),
    ):
        identity = bundle.get(bundle_key)
        if not isinstance(identity, Mapping):
            raise HtDyS610Error("approval_c_artifact_binding_invalid")
        path = Path(str(paths.get(path_key) or "")).resolve(strict=True)
        payload = _load_json(path)
        if (
            Path(str(identity.get("path") or "")).resolve(strict=False) != path
            or identity.get("file_sha256") != _file_sha256(path)
            or identity.get("packet_hash") != payload.get("packet_hash")
        ):
            raise HtDyS610Error("approval_c_artifact_drift")
    receipt_bytes = approval_receipt_path.resolve(strict=True).read_bytes()
    receipt = _load_json(approval_receipt_path)
    authorizations = dict(receipt.get("authorizations") or {})
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "approved"
        or receipt.get("task_id") != TASK_ID
        or receipt.get("bundle_hash") != approval_c_hash
        or receipt.get("parent_packet_hash") != parent_hash
        or receipt.get("approval_challenge") != bundle.get("approval_challenge")
        or authorizations
        != {
            "deployment": True,
            "s6_07_rebind_and_enable": True,
            "calendar_window": True,
            "five_day_runtime": True,
            "fault_matrix": True,
        }
    ):
        raise HtDyS610Error("approval_c_receipt_invalid")
    approved_at = _parse_datetime(receipt.get("approved_at"))
    if approved_at >= _parse_datetime(parent_packet.get("window_start")):
        raise HtDyS610Error("approval_c_receipt_too_late")
    expected_signers = Path(
        str(
            (parent_packet.get("bindings") or {})
            .get("artifact_paths", {})
            .get("approval_c_approved_signers")
            or ""
        )
    ).resolve(strict=True)
    if (
        approved_signers_path.resolve(strict=True) != expected_signers
        or _file_sha256(expected_signers)
        != (parent_packet.get("bindings") or {}).get(
            "approval_c_approved_signers_sha256"
        )
    ):
        raise HtDyS610Error("approval_c_signer_binding_drift")
    if not (trust_root_verifier or _verify_approved_signers_trust_root)(
        expected_signers
    ):
        raise HtDyS610Error("approval_c_trust_root_invalid")
    verifier = signature_verifier or _verify_ssh_signature
    if not verifier(
        receipt_bytes,
        approval_signature_path.resolve(strict=True),
        expected_signers,
    ):
        raise HtDyS610Error("approval_c_signature_invalid")
    for bundle_key, path_key in (
        ("observer_launchd", "observer_launchd"),
        ("fault_schedule", "fault_schedule_json"),
    ):
        identity = bundle.get(bundle_key)
        if not isinstance(identity, Mapping):
            raise HtDyS610Error("approval_c_artifact_binding_invalid")
        path = Path(str(paths.get(path_key) or "")).resolve(strict=True)
        if (
            Path(str(identity.get("path") or "")).resolve(strict=False) != path
            or identity.get("sha256") != _file_sha256(path)
        ):
            raise HtDyS610Error("approval_c_artifact_drift")


def build_daily_child(
    *,
    parent_packet: Mapping[str, Any],
    parent_approval_hash: str,
    trading_day: date,
    actual_contract: str,
    mapping_sha256: str,
    session_geometry_sha256: str,
    source_facts_sha256: str,
    beginning_state: Mapping[str, Any],
    previous_daily_seal_sha256: str | None,
) -> dict[str, Any]:
    if canonical_hash(parent_packet) != parent_approval_hash:
        raise HtDyS610Error("parent_hash_invalid")
    days = tuple(
        date.fromisoformat(str(item))
        for item in parent_packet.get("trading_days", ())
    )
    if trading_day not in days:
        raise HtDyS610Error("daily_child_outside_window")
    day_index = days.index(trading_day)
    if day_index == 0:
        if previous_daily_seal_sha256 is not None:
            raise HtDyS610Error("first_day_previous_seal_invalid")
    elif not _sha256(previous_daily_seal_sha256):
        raise HtDyS610Error("previous_daily_seal_invalid")
    if not _actual_contract(actual_contract):
        raise HtDyS610Error("actual_contract_invalid")
    for value in (
        mapping_sha256,
        session_geometry_sha256,
        source_facts_sha256,
    ):
        if not _sha256(value):
            raise HtDyS610Error("daily_child_hash_binding_invalid")
    child: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "packet_type": CHILD_PACKET_TYPE,
        "parent_packet_hash": parent_approval_hash,
        "day_index": day_index + 1,
        "trading_day": trading_day.isoformat(),
        "actual_contract": actual_contract,
        "mapping_sha256": mapping_sha256,
        "session_geometry_sha256": session_geometry_sha256,
        "source_facts_sha256": source_facts_sha256,
        "beginning_state": deepcopy(dict(beginning_state)),
        "previous_daily_seal_sha256": previous_daily_seal_sha256,
        "notification_baseline": NOTIFICATION_BASELINE,
        "max_event_count": MAX_EVENT_COUNT,
        "create_only": True,
    }
    child["packet_hash"] = canonical_hash(child)
    return child


def verify_daily_child(
    child: Mapping[str, Any],
    *,
    approval_hash: str,
    parent_packet: Mapping[str, Any],
    current_actual_contract: str,
    current_mapping_sha256: str,
    current_session_geometry_sha256: str,
    current_source_facts_sha256: str,
    current_beginning_state: Mapping[str, Any],
    current_previous_daily_seal_sha256: str | None,
) -> None:
    if child.get("schema_version") != SCHEMA_VERSION:
        raise HtDyS610Error("schema_version_invalid")
    if child.get("packet_type") != CHILD_PACKET_TYPE:
        raise HtDyS610Error("packet_type_invalid")
    if child.get("packet_hash") != approval_hash:
        raise HtDyS610Error("approval_hash_invalid")
    if canonical_hash(child) != approval_hash:
        raise HtDyS610Error("packet_hash_invalid")
    if child.get("parent_packet_hash") != parent_packet.get("packet_hash"):
        raise HtDyS610Error("daily_child_parent_drift")
    current = {
        "actual_contract": current_actual_contract,
        "mapping_sha256": current_mapping_sha256,
        "session_geometry_sha256": current_session_geometry_sha256,
        "source_facts_sha256": current_source_facts_sha256,
        "beginning_state": deepcopy(dict(current_beginning_state)),
        "previous_daily_seal_sha256": current_previous_daily_seal_sha256,
    }
    frozen = {key: child.get(key) for key in current}
    if frozen != current:
        raise HtDyS610Error("daily_child_drift")


class HtDyS610Ledger:
    """Append-only sample chain and create-only daily seals."""

    def __init__(
        self,
        *,
        root: Path,
        parent_packet_hash: str,
        night_session_dates: Mapping[date, date] | None = None,
    ) -> None:
        if not _sha256(parent_packet_hash):
            raise HtDyS610Error("parent_packet_hash_invalid")
        self.root = root.resolve(strict=False)
        self.parent_packet_hash = parent_packet_hash
        self.night_session_dates = dict(night_session_dates or {})

    def append_sample(
        self,
        *,
        trading_day: date,
        sampled_at: datetime,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if sampled_at.tzinfo is None:
            raise HtDyS610Error("sampled_at_timezone_required")
        day_root = self.root / "daily" / trading_day.isoformat()
        if (day_root / "daily_seal.json").exists():
            raise HtDyS610Error("daily_ledger_already_sealed")
        samples_root = day_root / "samples"
        existing = sorted(samples_root.glob("*.json"))
        _verify_existing_ledger_prefix(
            self.root,
            parent_packet_hash=self.parent_packet_hash,
            through_day=trading_day,
        )
        previous_hash: str | None = None
        previous_daily_seal = _latest_previous_daily_seal(
            self.root,
            trading_day=trading_day,
        )
        if existing:
            previous = _load_json(existing[-1])
            previous_hash = str(previous["sample_hash"])
        sequence = len(existing) + 1
        sample: dict[str, Any] = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "record_type": "htdy_s6_10_sample",
            "parent_packet_hash": self.parent_packet_hash,
            "trading_day": trading_day.isoformat(),
            "sequence": sequence,
            "sampled_at": sampled_at.astimezone(UTC).isoformat(),
            "previous_sample_sha256": previous_hash,
            "previous_daily_seal_sha256": (
                previous_daily_seal if sequence == 1 else None
            ),
            "payload": deepcopy(dict(payload)),
        }
        sample["sample_hash"] = canonical_hash(sample)
        path = samples_root / (
            f"{sequence:06d}-{sample['sample_hash'][:12]}.json"
        )
        _write_json_create_only(path, sample)
        return sample

    def seal_day(
        self,
        *,
        trading_day: date,
        status: str,
        summary: Mapping[str, Any],
        sealed_at: datetime | None = None,
    ) -> dict[str, Any]:
        if status not in {"passed", "failed"}:
            raise HtDyS610Error("daily_seal_status_invalid")
        day_root = self.root / "daily" / trading_day.isoformat()
        samples = sorted((day_root / "samples").glob("*.json"))
        if not samples:
            raise HtDyS610Error("daily_samples_missing")
        _verify_existing_ledger_prefix(
            self.root,
            parent_packet_hash=self.parent_packet_hash,
            through_day=trading_day,
        )
        last = _load_json(samples[-1])
        sealed_at = sealed_at or datetime.now(UTC)
        if sealed_at.tzinfo is None:
            raise HtDyS610Error("sealed_at_timezone_required")
        if status == "passed":
            _verify_session_coverage(
                samples,
                trading_day=trading_day,
                max_sample_gap_seconds=150,
                night_session_date=self.night_session_dates.get(trading_day),
            )
            if sealed_at.astimezone(SHANGHAI) < datetime.combine(
                trading_day,
                time(15),
                tzinfo=SHANGHAI,
            ):
                raise HtDyS610Error("daily_seal_before_session_end")
        seal: dict[str, Any] = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "record_type": "htdy_s6_10_daily_seal",
            "parent_packet_hash": self.parent_packet_hash,
            "trading_day": trading_day.isoformat(),
            "status": status,
            "sealed_at": sealed_at.isoformat(),
            "sample_count": len(samples),
            "last_sample_sha256": last.get("sample_hash"),
            "summary": deepcopy(dict(summary)),
        }
        seal["seal_hash"] = canonical_hash(seal)
        _write_json_create_only(day_root / "daily_seal.json", seal)
        return seal


def verify_ledger(
    root: Path,
    *,
    parent_packet_hash: str,
    max_sample_gap_seconds: int = 150,
    expected_trading_days: Sequence[date] | None = None,
    require_passed_seals: bool = False,
    night_session_dates: Mapping[date, date] | None = None,
) -> None:
    if not _sha256(parent_packet_hash):
        raise HtDyS610Error("parent_packet_hash_invalid")
    previous_day_seal: str | None = None
    daily_roots = sorted(path for path in (root / "daily").glob("*") if path.is_dir())
    if expected_trading_days is not None:
        expected_names = [day.isoformat() for day in expected_trading_days]
        actual_names = [path.name for path in daily_roots]
        if actual_names != expected_names:
            raise HtDyS610Error("ledger_trading_days_mismatch")
    for day_root in daily_roots:
        try:
            trading_day = date.fromisoformat(day_root.name)
        except ValueError as exc:
            raise HtDyS610Error("ledger_trading_day_invalid") from exc
        previous_sample: str | None = None
        samples = sorted((day_root / "samples").glob("*.json"))
        for expected_sequence, path in enumerate(samples, start=1):
            sample = _load_json(path)
            _verify_sample(sample, expected_previous=previous_sample)
            if sample.get("parent_packet_hash") != parent_packet_hash:
                raise HtDyS610Error("ledger_parent_hash_drift")
            if sample.get("sequence") != expected_sequence:
                raise HtDyS610Error("ledger_sequence_invalid")
            if sample.get("trading_day") != trading_day.isoformat():
                raise HtDyS610Error("ledger_sample_trading_day_drift")
            _parse_datetime(sample.get("sampled_at"))
            previous_sample = str(sample["sample_hash"])
            if expected_sequence == 1 and sample.get(
                "previous_daily_seal_sha256"
            ) != previous_day_seal:
                raise HtDyS610Error("ledger_daily_chain_invalid")
        seal_path = day_root / "daily_seal.json"
        if not seal_path.exists():
            if require_passed_seals:
                raise HtDyS610Error("ledger_daily_seal_missing")
            continue
        seal = _load_json(seal_path)
        if canonical_hash(seal) != seal.get("seal_hash"):
            raise HtDyS610Error("ledger_seal_hash_invalid")
        if seal.get("parent_packet_hash") != parent_packet_hash:
            raise HtDyS610Error("ledger_parent_hash_drift")
        if seal.get("sample_count") != len(samples):
            raise HtDyS610Error("ledger_seal_sample_count_invalid")
        if seal.get("last_sample_sha256") != previous_sample:
            raise HtDyS610Error("ledger_seal_tail_invalid")
        if seal.get("trading_day") != trading_day.isoformat():
            raise HtDyS610Error("ledger_seal_trading_day_drift")
        if seal.get("status") == "passed":
            _verify_session_coverage(
                samples,
                trading_day=trading_day,
                max_sample_gap_seconds=max_sample_gap_seconds,
                night_session_date=(night_session_dates or {}).get(
                    trading_day
                ),
            )
            sealed_at = _parse_datetime(seal.get("sealed_at"))
            if sealed_at.astimezone(SHANGHAI) < datetime.combine(
                trading_day,
                time(15),
                tzinfo=SHANGHAI,
            ):
                raise HtDyS610Error("daily_seal_before_session_end")
        elif require_passed_seals:
            raise HtDyS610Error("ledger_daily_seal_not_passed")
        previous_day_seal = str(seal["seal_hash"])


class HtDyS610Observer:
    """Read-only sampler with invariant enforcement before evidence append."""

    def __init__(
        self,
        *,
        collector: Callable[[], Mapping[str, Any]],
        baseline_counts: Mapping[str, Any],
        baseline_hashes: Mapping[str, Any],
        max_event_count: int = MAX_EVENT_COUNT,
    ) -> None:
        self.collector = collector
        self.baseline_counts = deepcopy(dict(baseline_counts))
        self.baseline_hashes = deepcopy(dict(baseline_hashes))
        self.max_event_count = max_event_count

    def sample(self) -> dict[str, Any]:
        facts = deepcopy(dict(self.collector()))
        counts = dict(facts.get("counts") or {})
        hashes = dict(facts.get("hashes") or {})
        if counts.get("signal_notifications") != self.baseline_counts.get(
            "signal_notifications"
        ):
            raise HtDyS610Error("notification_count_drift")
        for key in ("review_notes", "orders", "trades"):
            if counts.get(key) != self.baseline_counts.get(key):
                raise HtDyS610Error(f"{key}_count_drift")
        event_count = counts.get("signal_events")
        baseline_events = self.baseline_counts.get("signal_events")
        if (
            type(event_count) is not int
            or type(baseline_events) is not int
            or event_count < baseline_events
            or event_count - baseline_events > self.max_event_count
        ):
            raise HtDyS610Error("signal_event_count_invalid")
        if hashes != self.baseline_hashes:
            raise HtDyS610Error("forbidden_hash_drift")
        htdy = dict(facts.get("htdy") or {})
        if htdy.get("changed") != 0:
            raise HtDyS610Error("signal_changed_forbidden")
        events = list(facts.get("new_events") or ())
        if len(events) != event_count - baseline_events:
            raise HtDyS610Error("new_event_lineage_incomplete")
        for event in events:
            lineage = (
                dict(event.get("formal_lineage") or {})
                if isinstance(event, Mapping)
                else {}
            )
            indicator = dict(lineage.get("indicator") or {})
            detection = dict(lineage.get("live_detection_snapshot") or {})
            if not isinstance(event, Mapping) or any(
                (
                    event.get("event_type") != "signal_created",
                    event.get("source_mode") != SOURCE_MODE,
                    event.get("strategy_name") != STRATEGY_CODE,
                    event.get("strategy_version") != STRATEGY_VERSION,
                    event.get("product") != PRODUCT,
                    event.get("period") != PERIOD,
                    event.get("direction") not in {"long", "short"},
                    not _actual_contract(event.get("actual_contract")),
                    event.get("dominant_mapping_date") is None,
                    event.get("dominant_mapping_date")
                    != facts.get("trading_day"),
                    event.get("actual_contract")
                    != dict(facts.get("mapping") or {}).get(
                        "actual_contract"
                    ),
                    lineage.get("schema_version")
                    != "signal_review_lineage_v2",
                    indicator.get("indicator_code") != INDICATOR_CODE,
                    indicator.get("indicator_version") != INDICATOR_VERSION,
                    indicator.get("signal_policy") != SIGNAL_POLICY,
                    indicator.get("future_looking") is not True,
                    indicator.get("repainting_accepted") is not True,
                    indicator.get("first_seen_no_retraction") is not True,
                    detection.get("source_sha256")
                    != facts.get("indicator_source_sha256"),
                    detection.get("policy_sha256")
                    != facts.get("policy_sha256"),
                )
            ):
                raise HtDyS610Error("non_exact_event_forbidden")
        return {
            "status": "ok",
            "readonly": True,
            "facts": facts,
        }


def publish_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    """Public create-only writer used by the CLI and fake harness."""

    _write_json_create_only(path, payload)


def _validate_window(
    trading_days: Sequence[date],
    *,
    generated_at: datetime,
    first_night_session_date: date | None = None,
) -> tuple[date, ...]:
    if generated_at.tzinfo is None:
        raise HtDyS610Error("generated_at_timezone_required")
    days = tuple(trading_days)
    if len(days) != WINDOW_TRADING_DAYS or any(
        type(day) is not date for day in days
    ):
        raise HtDyS610Error("window_not_five_days")
    if tuple(sorted(set(days))) != days:
        raise HtDyS610Error("window_invalid")
    if generated_at.astimezone(SHANGHAI) >= _night_session_start(
        days[0],
        first_night_session_date,
    ):
        raise HtDyS610Error("window_already_started")
    return days


def _night_session_start(
    trading_day: date,
    night_session_date: date | None = None,
) -> datetime:
    return datetime.combine(
        night_session_date or _previous_weekday(trading_day),
        time(21),
        tzinfo=SHANGHAI,
    )


def _validate_bindings(bindings: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(bindings))
    required_hashes = (
        "runtime_tree",
        "source_tree",
        "profile_sha256",
        "indicator_source_sha256",
        "policy_sha256",
        "s6_07_receipt_sha256",
        "s6_08_receipt_sha256",
        "s6_09_receipt_sha256",
        "backup_receipt_sha256",
        "restore_receipt_sha256",
        "restore_audit_receipt_sha256",
        "calendar_sha256",
        "launchd_sha256",
        "observer_launchd_sha256",
        "deployment_packet_sha256",
        "s6_07_rebind_packet_sha256",
        "s6_07_enable_packet_sha256",
        "fault_schedule_sha256",
        "approval_c_approved_signers_sha256",
    )
    if any(not _sha256(result.get(key)) for key in required_hashes):
        raise HtDyS610Error("parent_hash_binding_invalid")
    for key in ("runtime_commit", "source_commit"):
        value = result.get(key)
        if (
            not isinstance(value, str)
            or len(value) != 40
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise HtDyS610Error("parent_commit_binding_invalid")
    if result.get("runtime_tracked_clean") is not True:
        raise HtDyS610Error("runtime_not_clean")
    if result.get("database_revision") != REQUIRED_DB_REVISION:
        raise HtDyS610Error("database_revision_invalid")
    flags = dict(result.get("feature_flags") or {})
    if flags.get("wechat_autosend") is not False:
        raise HtDyS610Error("wechat_autosend_must_be_false")
    counts = dict(result.get("baseline_counts") or {})
    if counts.get("signal_notifications") != NOTIFICATION_BASELINE:
        raise HtDyS610Error("notification_baseline_invalid")
    if any(
        type(counts.get(key)) is not int
        for key in (
            "signal_events",
            "signal_notifications",
            "review_notes",
            "orders",
            "trades",
        )
    ):
        raise HtDyS610Error("baseline_counts_invalid")
    hashes = dict(result.get("baseline_hashes") or {})
    if any(
        not _sha256(hashes.get(key))
        for key in (
            "profile_bindings",
            "canonical_assets",
            "forbidden_tables",
        )
    ):
        raise HtDyS610Error("baseline_hashes_invalid")
    max_ids = dict(result.get("baseline_max_ids") or {})
    if any(
        type(max_ids.get(key)) is not int or max_ids[key] < 0
        for key in (
            "signal_events",
            "signal_notifications",
            "review_notes",
            "orders",
            "trades",
        )
    ):
        raise HtDyS610Error("baseline_max_ids_invalid")
    return result


def _validate_fault_schedule(schedule: Mapping[str, Any]) -> None:
    expected = {
        "D1": {"live_scheduler", "api", "web"},
        "D2": {"redis"},
        "D3": {"postgres"},
        "D4": {"rqdata", "eod_scheduler"},
        "D4_D5": {"mac_reboot"},
    }
    if set(schedule) != set(expected):
        raise HtDyS610Error("fault_schedule_invalid")
    for phase, required_faults in expected.items():
        rows = schedule.get(phase)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise HtDyS610Error("fault_schedule_invalid")
        faults: set[str] = set()
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise HtDyS610Error("fault_schedule_invalid")
            fault = raw.get("fault")
            if not isinstance(fault, str):
                raise HtDyS610Error("fault_schedule_invalid")
            faults.add(fault)
            start = _parse_datetime(raw.get("slot_start"))
            end = _parse_datetime(raw.get("slot_end"))
            if end <= start:
                raise HtDyS610Error("fault_slot_invalid")
            duration = raw.get("max_duration_seconds")
            if type(duration) is not int or not 1 <= duration <= 60:
                raise HtDyS610Error("fault_duration_invalid")
            if fault == "rqdata":
                try:
                    target = ipaddress.ip_address(str(raw.get("target_ip")))
                except ValueError as exc:
                    raise HtDyS610Error("rqdata_target_ip_invalid") from exc
                if target.is_unspecified or target.is_loopback:
                    raise HtDyS610Error("rqdata_target_ip_invalid")
        if faults != required_faults:
            raise HtDyS610Error("fault_matrix_invalid")


def _verify_sample(
    sample: Mapping[str, Any],
    *,
    expected_previous: str | None,
) -> None:
    if canonical_hash(sample) != sample.get("sample_hash"):
        raise HtDyS610Error("ledger_sample_hash_invalid")
    if expected_previous is not None and sample.get(
        "previous_sample_sha256"
    ) != expected_previous:
        raise HtDyS610Error("ledger_sample_chain_invalid")


def _latest_previous_daily_seal(
    root: Path,
    *,
    trading_day: date,
) -> str | None:
    candidates = sorted(
        path
        for path in (root / "daily").glob("*/daily_seal.json")
        if path.parent.name < trading_day.isoformat()
    )
    if not candidates:
        return None
    payload = _load_json(candidates[-1])
    value = payload.get("seal_hash")
    if not _sha256(value):
        raise HtDyS610Error("previous_daily_seal_invalid")
    return str(value)


def _verify_existing_ledger_prefix(
    root: Path,
    *,
    parent_packet_hash: str,
    through_day: date,
) -> None:
    """Verify every immutable record before extending the chain."""

    previous_day_seal: str | None = None
    for day_root in sorted(path for path in (root / "daily").glob("*") if path.is_dir()):
        if day_root.name > through_day.isoformat():
            break
        try:
            day = date.fromisoformat(day_root.name)
        except ValueError as exc:
            raise HtDyS610Error("ledger_trading_day_invalid") from exc
        previous_sample: str | None = None
        samples = sorted((day_root / "samples").glob("*.json"))
        for sequence, path in enumerate(samples, start=1):
            sample = _load_json(path)
            _verify_sample(sample, expected_previous=previous_sample)
            if sample.get("parent_packet_hash") != parent_packet_hash:
                raise HtDyS610Error("ledger_parent_hash_drift")
            if sample.get("trading_day") != day.isoformat():
                raise HtDyS610Error("ledger_sample_trading_day_drift")
            if sample.get("sequence") != sequence:
                raise HtDyS610Error("ledger_sequence_invalid")
            if sequence == 1 and sample.get("previous_daily_seal_sha256") != previous_day_seal:
                raise HtDyS610Error("ledger_daily_chain_invalid")
            previous_sample = str(sample["sample_hash"])
        seal_path = day_root / "daily_seal.json"
        if seal_path.exists():
            seal = _load_json(seal_path)
            if canonical_hash(seal) != seal.get("seal_hash"):
                raise HtDyS610Error("ledger_seal_hash_invalid")
            if seal.get("last_sample_sha256") != previous_sample:
                raise HtDyS610Error("ledger_seal_tail_invalid")
            if seal.get("parent_packet_hash") != parent_packet_hash:
                raise HtDyS610Error("ledger_parent_hash_drift")
            previous_day_seal = str(seal["seal_hash"])


def _session_windows(
    trading_day: date,
    *,
    night_session_date: date | None = None,
) -> tuple[tuple[datetime, datetime], ...]:
    night_date = night_session_date or _previous_weekday(trading_day)
    return (
        (
            datetime.combine(night_date, time(21), tzinfo=SHANGHAI),
            datetime.combine(night_date, time(23), tzinfo=SHANGHAI),
        ),
        (
            datetime.combine(trading_day, time(9), tzinfo=SHANGHAI),
            datetime.combine(trading_day, time(10, 15), tzinfo=SHANGHAI),
        ),
        (
            datetime.combine(trading_day, time(10, 30), tzinfo=SHANGHAI),
            datetime.combine(trading_day, time(11, 30), tzinfo=SHANGHAI),
        ),
        (
            datetime.combine(trading_day, time(13, 30), tzinfo=SHANGHAI),
            datetime.combine(trading_day, time(15), tzinfo=SHANGHAI),
        ),
    )


def _verify_session_coverage(
    sample_paths: Sequence[Path],
    *,
    trading_day: date,
    max_sample_gap_seconds: int,
    night_session_date: date | None = None,
) -> None:
    timestamps = sorted(
        _parse_datetime(_load_json(path).get("sampled_at")).astimezone(SHANGHAI)
        for path in sample_paths
    )
    for start, end in _session_windows(
        trading_day,
        night_session_date=night_session_date,
    ):
        covered = [stamp for stamp in timestamps if start <= stamp <= end]
        if not covered:
            raise HtDyS610Error("ledger_session_coverage_missing")
        if (covered[0] - start).total_seconds() > max_sample_gap_seconds:
            raise HtDyS610Error("ledger_session_start_gap")
        if (end - covered[-1]).total_seconds() > max_sample_gap_seconds:
            raise HtDyS610Error("ledger_session_end_gap")
        gaps = [
            (current - previous).total_seconds()
            for previous, current in zip(covered, covered[1:], strict=False)
        ]
        if any(gap > max_sample_gap_seconds for gap in gaps):
            raise HtDyS610Error("ledger_sample_gap")
        if sum(gap > 75 for gap in gaps) > 2:
            raise HtDyS610Error("ledger_sample_cadence_invalid")


def _previous_weekday(trading_day: date) -> date:
    candidate = trading_day - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _write_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise HtDyS610Error("create_only_path_exists") from exc
    created_identity: tuple[int, int] | None = None
    try:
        stat = os.fstat(descriptor)
        created_identity = (stat.st_dev, stat.st_ino)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            current = path.lstat()
            if created_identity == (current.st_dev, current.st_ino):
                path.unlink()
        except OSError:
            pass
        raise


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610Error("ledger_json_invalid") from exc
    if not isinstance(payload, dict):
        raise HtDyS610Error("ledger_json_invalid")
    return payload


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HtDyS610Error("bound_artifact_unavailable") from exc


def _verify_ssh_signature(
    payload: bytes,
    signature_path: Path,
    approved_signers_path: Path,
) -> bool:
    import subprocess

    try:
        result = subprocess.run(
            (
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(approved_signers_path),
                "-I",
                "guiyi-owner",
                "-n",
                "guiyi-htdy-s610",
                "-s",
                str(signature_path),
            ),
            input=payload,
            check=False,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def _verify_approved_signers_trust_root(path: Path) -> bool:
    import subprocess

    try:
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(lines) != 1 or lines[0].split(maxsplit=1)[0] != "guiyi-owner":
            return False
        result = subprocess.run(
            ("ssh-keygen", "-lf", str(path), "-E", "sha256"),
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, UnicodeError):
        return False
    fields = result.stdout.split()
    return (
        result.returncode == 0
        and len(fields) >= 2
        and fields[1] == APPROVAL_C_SIGNER_FINGERPRINT
    )


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _actual_contract(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("JM")
        and value[2:].isdigit()
        and not value.endswith(".MAIN")
    )


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise HtDyS610Error("datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HtDyS610Error("datetime_invalid") from exc
    if parsed.tzinfo is None:
        raise HtDyS610Error("datetime_invalid")
    return parsed


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported_json_type:{type(value).__name__}")
