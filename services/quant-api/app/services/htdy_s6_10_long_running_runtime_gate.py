"""Runtime adapter for Approval-D-bound daily observation children."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from app.services.htdy_s6_10_long_running import (
    HtDyS610LongRunningError,
    _request_hash,
    build_long_running_daily_child,
    canonical_hash,
    verify_signed_approval_d_receipt,
)
from app.services.trading_session_clock import SHANGHAI


class HtDyS610LongRunningRuntimeGate:
    """Resolve, publish, and consume the exact child for each trading day."""

    def __init__(
        self,
        *,
        approval_d_request: Mapping[str, Any],
        approval_d_hash: str,
        approval_verifier: Callable[[], None],
        daily_facts_collector: Callable[
            [Any, datetime, bool], Mapping[str, Any]
        ],
        child_builder: Callable[..., Mapping[str, Any]],
        child_publisher: Callable[
            ..., Mapping[str, Any]
        ],
        mapping_receipt_publisher: Callable[
            ..., Mapping[str, Any]
        ],
        handler_factory: Callable[..., Any],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.approval_d_request = dict(approval_d_request)
        self.approval_d_hash = approval_d_hash
        self.approval_verifier = approval_verifier
        self.daily_facts_collector = daily_facts_collector
        self.child_builder = child_builder
        self.child_publisher = child_publisher
        self.mapping_receipt_publisher = mapping_receipt_publisher
        self.handler_factory = handler_factory
        self.now = now or (lambda: datetime.now(UTC))
        self._daily_child: dict[str, Any] | None = None
        self._pending_child: dict[str, Any] | None = None
        self._pending_mapping_receipt: dict[str, Any] | None = None
        self._pending_mapping_day: date | None = None
        self._last_handler: Any = None

    def __call__(
        self,
        session: Any,
        *,
        phase: str,
        result: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if phase == "verify":
            self.approval_verifier()
            return {
                "gate_status": "verified",
                "gate_schema": "s6_10_approval_d_daily_child_v1",
                "approval_d_hash": self.approval_d_hash,
            }
        if phase in {"pre_write", "daily_metadata"}:
            self.approval_verifier()
            if phase == "pre_write":
                self._pending_child = None
                self._pending_mapping_receipt = None
                self._pending_mapping_day = None
            facts = dict(
                self.daily_facts_collector(
                    session,
                    self.now(),
                    phase == "pre_write",
                )
            )
            if facts.get("gate_status") == "mapping_prepared":
                mapping_receipt = facts.get("mapping_receipt")
                trading_day = facts.get("trading_day")
                if (
                    phase != "pre_write"
                    or not isinstance(mapping_receipt, Mapping)
                    or not isinstance(trading_day, date)
                ):
                    raise HtDyS610LongRunningError(
                        "daily_mapping_receipt_missing"
                    )
                self._pending_mapping_receipt = dict(
                    mapping_receipt
                )
                self._pending_mapping_day = trading_day
                return self._preopen_metadata(
                    trading_day,
                    after_commit_required=True,
                )
            if facts.get("gate_status") in {"waiting", "closed"}:
                return {
                    "gate_schema": "s6_10_approval_d_daily_child_v1",
                    "approval_d_hash": self.approval_d_hash,
                    "gate_status": facts["gate_status"],
                }
            mapping_receipt = facts.pop("mapping_receipt", None)
            if not isinstance(mapping_receipt, Mapping):
                raise HtDyS610LongRunningError(
                    "daily_mapping_receipt_missing"
                )
            child = dict(
                self.child_builder(
                    approval_d_request=self.approval_d_request,
                    approval_d_hash=self.approval_d_hash,
                    **facts,
                )
            )
            if phase == "daily_metadata":
                trading_day = date.fromisoformat(
                    str(child["trading_day"])
                )
                verified_receipt = dict(
                    self.mapping_receipt_publisher(
                        mapping_receipt,
                        trading_day=trading_day,
                        create=False,
                    )
                )
                published = dict(
                    self.child_publisher(child, create=False)
                )
                if (
                    verified_receipt != dict(mapping_receipt)
                    or published != child
                ):
                    raise HtDyS610LongRunningError(
                        "daily_child_publication_conflict"
                    )
                self._daily_child = published
                return self._metadata()
            trading_day = date.fromisoformat(str(child["trading_day"]))
            verified_receipt = dict(
                self.mapping_receipt_publisher(
                    mapping_receipt,
                    trading_day=trading_day,
                    create=False,
                )
            )
            published = dict(
                self.child_publisher(child, create=True)
            )
            if (
                verified_receipt != dict(mapping_receipt)
                or published != child
            ):
                raise HtDyS610LongRunningError(
                    "daily_child_publication_conflict"
                )
            self._daily_child = published
            metadata = self._metadata()
            allowed = {
                datetime.fromisoformat(value)
                for value in child["expected_bucket_ends"]
            }
            self._last_handler = self.handler_factory(
                session,
                allowed_bucket_ends=allowed,
            )
            return {
                **metadata,
                "signal_event_handler": self._last_handler,
            }
        if phase == "post_write":
            event_result = dict((result or {}).get("signal_events") or {})
            if event_result and event_result.get("changed") != 0:
                raise HtDyS610LongRunningError(
                    "signal_changed_forbidden"
                )
            return self._metadata()
        if phase == "after_commit":
            if (
                self._pending_mapping_receipt is not None
                and self._pending_mapping_day is not None
                and self._pending_child is None
            ):
                published_receipt = dict(
                    self.mapping_receipt_publisher(
                        self._pending_mapping_receipt,
                        trading_day=self._pending_mapping_day,
                        create=True,
                    )
                )
                if published_receipt != self._pending_mapping_receipt:
                    raise HtDyS610LongRunningError(
                        "daily_mapping_receipt_publication_conflict"
                    )
                trading_day = self._pending_mapping_day
                self._pending_mapping_receipt = None
                self._pending_mapping_day = None
                return self._preopen_metadata(
                    trading_day,
                    after_commit_required=False,
                )
            if (
                self._daily_child is not None
                and self._pending_mapping_receipt is None
                and self._pending_child is None
            ):
                return self._metadata()
            raise HtDyS610LongRunningError(
                "runtime_gate_pre_write_required"
            )
        raise HtDyS610LongRunningError("runtime_gate_phase_invalid")

    def _metadata(self) -> dict[str, Any]:
        if self._daily_child is None:
            raise HtDyS610LongRunningError("daily_child_not_resolved")
        last_decision = getattr(
            self._last_handler,
            "last_decision_bucket_end",
            None,
        )
        return {
            "gate_status": "authorized",
            "gate_schema": "s6_10_approval_d_daily_child_v1",
            "approval_d_hash": self.approval_d_hash,
            "authorization_hash": self._daily_child["packet_hash"],
            "target_trading_day": self._daily_child["trading_day"],
            "expected_bucket_ends": list(
                self._daily_child["expected_bucket_ends"]
            ),
            "window_end": self._daily_child["window_end"],
            "last_decision_bucket_end": (
                last_decision.isoformat()
                if isinstance(last_decision, datetime)
                else None
            ),
        }

    def _preopen_metadata(
        self,
        trading_day: date,
        *,
        after_commit_required: bool,
    ) -> dict[str, Any]:
        return {
            "gate_schema": "s6_10_approval_d_daily_child_v1",
            "approval_d_hash": self.approval_d_hash,
            "gate_status": "waiting",
            "mapping_prepared": True,
            "target_trading_day": trading_day.isoformat(),
            "after_commit_required": after_commit_required,
        }


def publish_daily_child_create_only(
    child: Mapping[str, Any],
    *,
    root: Path,
    create: bool = True,
) -> dict[str, Any]:
    """Atomically publish once, or recover only an identical prior child."""

    payload = dict(child)
    if payload.get("packet_hash") != canonical_hash(payload):
        raise HtDyS610LongRunningError("daily_child_invalid")
    try:
        trading_day = date.fromisoformat(str(payload["trading_day"]))
    except (KeyError, ValueError) as exc:
        raise HtDyS610LongRunningError("daily_child_invalid") from exc
    return _publish_daily_payload_create_only(
        payload,
        root=root,
        trading_day=trading_day,
        filename="htdy-s6-10-daily-child.json",
        temporary_prefix=".daily-child-",
        create=create,
        missing_error="daily_child_missing",
        conflict_error="daily_child_publication_conflict",
    )


def publish_daily_mapping_receipt_create_only(
    receipt: Mapping[str, Any],
    *,
    root: Path,
    trading_day: date,
    create: bool,
) -> dict[str, Any]:
    payload = dict(receipt)
    receipt_hash = payload.get("receipt_hash")
    expected_hash = canonical_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "receipt_hash"
        }
    )
    if (
        payload.get("receipt_type") != "htdy_s6_10_daily_mapping"
        or payload.get("trading_day") != trading_day.isoformat()
        or receipt_hash != expected_hash
    ):
        raise HtDyS610LongRunningError(
            "daily_mapping_receipt_invalid"
        )
    return _publish_daily_payload_create_only(
        payload,
        root=root,
        trading_day=trading_day,
        filename="mapping_receipt.json",
        temporary_prefix=".mapping-receipt-",
        create=create,
        missing_error="daily_mapping_receipt_missing",
        conflict_error="daily_mapping_receipt_publication_conflict",
    )


def _publish_daily_payload_create_only(
    payload: Mapping[str, Any],
    *,
    root: Path,
    trading_day: date,
    filename: str,
    temporary_prefix: str,
    create: bool,
    missing_error: str,
    conflict_error: str,
) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    day_root = resolved_root / trading_day.isoformat()
    if not day_root.exists():
        if not create:
            raise HtDyS610LongRunningError(missing_error)
        day_root.mkdir(mode=0o700)
    if (
        not day_root.is_dir()
        or day_root.is_symlink()
        or day_root.resolve(strict=True).parent != resolved_root
    ):
        raise HtDyS610LongRunningError(conflict_error)
    target = day_root / filename
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise HtDyS610LongRunningError(conflict_error)
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HtDyS610LongRunningError(conflict_error) from exc
        if existing != dict(payload):
            raise HtDyS610LongRunningError(conflict_error)
        return dict(payload)
    if not create:
        raise HtDyS610LongRunningError(missing_error)
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=day_root,
            prefix=temporary_prefix,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink():
                raise HtDyS610LongRunningError(conflict_error)
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HtDyS610LongRunningError(conflict_error) from exc
            if existing != dict(payload):
                raise HtDyS610LongRunningError(conflict_error)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dict(payload)


def collect_long_running_daily_facts(
    session: Any,
    current: datetime,
    *,
    eod_authorization_hash: str,
    runtime_root: Path,
    clock_factory: Callable[[Any], Any] | None = None,
    mapping_collector: Callable[[Any, date, bool], Mapping[str, Any]]
    | None = None,
    checkpoint_collector: Callable[[Any], Mapping[str, Any]]
    | None = None,
    source_facts_collector: Callable[[Any, str, Path], str]
    | None = None,
    runtime_identity_collector: Callable[[Path], tuple[str, str]]
    | None = None,
    prepare_preopen_mapping: bool = False,
    next_open_trading_day_resolver: Callable[
        [Any, datetime], date | None
    ]
    | None = None,
    preopen_first_session_validator: Callable[
        [Any, date, datetime], bool
    ]
    | None = None,
) -> dict[str, Any]:
    """Collect the daily child only from current DCE, DB, code, and source facts."""

    if current.tzinfo is None:
        raise HtDyS610LongRunningError("current_timezone_required")
    if clock_factory is None:
        from app.services.trading_session_clock import TradingSessionClock

        clock_factory = TradingSessionClock
    clock = clock_factory(session)
    decision = clock.decision(product="jm", exchange="DCE", now=current)
    if not decision.should_poll:
        next_open = getattr(decision, "next_open_at", None)
        local_now = current.astimezone(SHANGHAI).replace(tzinfo=None)
        if (
            not prepare_preopen_mapping
            or mapping_collector is None
            or not isinstance(next_open, datetime)
            or not timedelta(0)
            < (next_open - local_now)
            <= timedelta(hours=4)
        ):
            return {"gate_status": "waiting"}
        resolver = (
            next_open_trading_day_resolver
            or _trading_day_for_next_open
        )
        target = resolver(clock, next_open)
        if not isinstance(target, date):
            raise HtDyS610LongRunningError(
                "preopen_trading_day_missing"
            )
        first_session_validator = (
            preopen_first_session_validator
            or _is_first_session_open
        )
        if not first_session_validator(clock, target, next_open):
            return {"gate_status": "waiting"}
        previous = clock._previous_trading_day(target, "DCE")
        if not isinstance(previous, date):
            raise HtDyS610LongRunningError(
                "previous_trading_day_missing"
            )
        prior_eod = dict(
            (checkpoint_collector or _collect_prior_eod)(session)
        )
        if (
            prior_eod.get("trading_day") != previous.isoformat()
            or prior_eod.get("status") != "passed"
            or prior_eod.get("authorization_hash")
            != eod_authorization_hash
        ):
            raise HtDyS610LongRunningError("prior_eod_not_passed")
        mapping = dict(mapping_collector(session, target, True))
        receipt = mapping.get("mapping_receipt")
        if not isinstance(receipt, Mapping):
            raise HtDyS610LongRunningError(
                "daily_mapping_receipt_missing"
            )
        return {
            "gate_status": "mapping_prepared",
            "trading_day": target,
            "actual_contract": mapping["actual_contract"],
            "mapping_sha256": mapping["mapping_sha256"],
            "mapping_receipt": dict(receipt),
        }
    target = decision.trading_day
    if not isinstance(target, date):
        raise HtDyS610LongRunningError("runtime_trading_day_missing")
    previous = clock._previous_trading_day(target, "DCE")
    if not isinstance(previous, date):
        raise HtDyS610LongRunningError("previous_trading_day_missing")

    mapping = dict(
        mapping_collector(session, target, False)
        if mapping_collector is not None
        else _collect_mapping_facts(session, target)
    )
    mapping_receipt = mapping.get("mapping_receipt")
    if mapping_collector is not None and not isinstance(
        mapping_receipt,
        Mapping,
    ):
        raise HtDyS610LongRunningError("daily_mapping_receipt_missing")
    prior_eod = dict(
        (checkpoint_collector or _collect_prior_eod)(session)
    )
    if (
        prior_eod.get("trading_day") != previous.isoformat()
        or prior_eod.get("status") != "passed"
        or prior_eod.get("authorization_hash")
        != eod_authorization_hash
    ):
        raise HtDyS610LongRunningError("prior_eod_not_passed")
    windows = clock.windows_for_trading_day(
        target,
        product="jm",
        exchange="DCE",
    )
    expected_bucket_ends, session_hash, window_end = (
        _derive_session_bindings(windows)
    )
    source_hash = (source_facts_collector or _collect_source_facts)(
        session,
        str(mapping["actual_contract"]),
        runtime_root,
    )
    runtime_commit, runtime_tree = (
        runtime_identity_collector or _collect_runtime_identity
    )(runtime_root)
    return {
        "trading_day": target,
        "previous_trading_day": previous,
        "actual_contract": mapping["actual_contract"],
        "mapping_sha256": mapping["mapping_sha256"],
        **(
            {"mapping_receipt": dict(mapping_receipt)}
            if isinstance(mapping_receipt, Mapping)
            else {}
        ),
        "session_geometry_sha256": session_hash,
        "source_facts_sha256": source_hash,
        "current_runtime_commit": runtime_commit,
        "current_runtime_tree": runtime_tree,
        "prior_eod": prior_eod,
        "expected_bucket_ends": expected_bucket_ends,
        "window_end": window_end,
    }


def _trading_day_for_next_open(
    clock: Any,
    next_open: datetime,
) -> date | None:
    rows = clock._calendar_rows(
        "DCE",
        next_open.date(),
        next_open.date() + timedelta(days=10),
    )
    for row in rows:
        if not row.is_trading_day:
            continue
        windows = clock.windows_for_trading_day(
            row.trade_date,
            product="jm",
            exchange="DCE",
        )
        if any(window.start == next_open for window in windows):
            return row.trade_date
    return None


def _is_first_session_open(
    clock: Any,
    trading_day: date,
    next_open: datetime,
) -> bool:
    windows = clock.windows_for_trading_day(
        trading_day,
        product="jm",
        exchange="DCE",
    )
    return bool(
        windows
        and min(window.start for window in windows) == next_open
    )


def _derive_session_bindings(
    windows: list[Any],
) -> tuple[list[str], str, str]:
    geometry: list[dict[str, Any]] = []
    ends: list[datetime] = []
    for window in windows:
        start = window.start
        end = window.end
        if start.tzinfo is None:
            start = start.replace(tzinfo=SHANGHAI)
        if end.tzinfo is None:
            end = end.replace(tzinfo=SHANGHAI)
        duration = int((end - start).total_seconds())
        if duration <= 0 or duration % 900:
            raise HtDyS610LongRunningError(
                "session_geometry_not_15m_aligned"
            )
        geometry.append(
            {
                "session_name": str(window.name),
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
        cursor = start + timedelta(minutes=15)
        while cursor <= end:
            ends.append(cursor)
            cursor += timedelta(minutes=15)
    if len(ends) != 23 or len(set(ends)) != 23:
        raise HtDyS610LongRunningError(
            "complete_day_bucket_coverage_invalid"
        )
    return (
        [value.isoformat() for value in ends],
        canonical_hash({"sessions": geometry}),
        max(value for value in ends).isoformat(),
    )


def _collect_mapping_facts(
    session: Any,
    trading_day: date,
) -> dict[str, str]:
    from app.services.actual_contract_semantics import (
        load_strict_main_contract_mapping,
    )

    try:
        row = load_strict_main_contract_mapping(
            session,
            instrument_symbol="jm",
            trade_date=trading_day,
            provider="rqdata",
            rule="volume_open_interest",
            rank=1,
        )
    except ValueError as exc:
        raise HtDyS610LongRunningError(
            "mapping_duplicate_or_missing"
        ) from exc
    if row is None:
        raise HtDyS610LongRunningError("mapping_duplicate_or_missing")
    actual_contract = str(row.contract_code or "").strip().upper()
    facts = {
        "trade_date": row.trade_date.isoformat(),
        "contract_code": row.contract_code,
        "normalized_contract_code": actual_contract,
        "rank": row.rank,
        "rule": row.rule,
        "provider": row.provider,
        "data_version": row.data_version,
    }
    return {
        "actual_contract": actual_contract,
        "mapping_sha256": canonical_hash(facts),
    }


def _runtime_daily_mapping(
    session: Any,
    *,
    trading_day: date,
    daily_root: Path,
    approval_d_hash: str,
    allow_create: bool,
    client_factory: Callable[[], Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    from app.services.htdy_s6_10_daily_mapping import (
        HtDyS610DailyMappingError,
        resolve_or_create_s610_daily_mapping,
        result_payload,
        verify_s610_daily_mapping_receipt,
    )

    resolved_root = daily_root.resolve(strict=True)
    day_root = resolved_root / trading_day.isoformat()
    if day_root.exists() and (
        day_root.is_symlink()
        or not day_root.is_dir()
        or day_root.resolve(strict=True).parent != resolved_root
    ):
        raise HtDyS610LongRunningError("daily_mapping_root_invalid")
    receipt_path = day_root / "mapping_receipt.json"
    try:
        if receipt_path.exists():
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise HtDyS610DailyMappingError(
                    "s610_daily_mapping_receipt_invalid"
                )
            receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
            if not isinstance(receipt, Mapping):
                raise HtDyS610DailyMappingError(
                    "s610_daily_mapping_receipt_invalid"
                )
            result = verify_s610_daily_mapping_receipt(
                session,
                receipt=receipt,
                trading_day=trading_day,
                approval_d_hash=approval_d_hash,
            )
        elif not allow_create:
            raise HtDyS610LongRunningError(
                "daily_mapping_receipt_missing"
            )
        else:
            if client_factory is None:
                from app.services.rqdata_ingest.client import RqDataClient

                def create_client() -> Any:
                    return RqDataClient(load_env_file=True)

                client_factory = create_client
            result = resolve_or_create_s610_daily_mapping(
                session,
                trading_day=trading_day,
                approval_d_hash=approval_d_hash,
                client=client_factory(),
                now=(now or (lambda: datetime.now(UTC)))(),
            )
    except HtDyS610LongRunningError:
        raise
    except (
        HtDyS610DailyMappingError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise HtDyS610LongRunningError(str(exc)) from exc
    payload = result_payload(result)
    return {
        "actual_contract": payload["actual_contract"],
        "mapping_sha256": payload["mapping_sha256"],
        "mapping_receipt": payload["receipt"],
    }


def _collect_prior_eod(session: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.data_center import AfterMarketSchedulerCheckpoint

    checkpoint = session.scalar(
        select(AfterMarketSchedulerCheckpoint).where(
            AfterMarketSchedulerCheckpoint.product == "jm"
        )
    )
    if (
        checkpoint is None
        or checkpoint.status not in {"idle", "success"}
        or checkpoint.current_trading_day is not None
        or checkpoint.retry_count != 0
        or checkpoint.last_successful_trading_day is None
    ):
        raise HtDyS610LongRunningError("prior_eod_not_passed")
    return {
        "trading_day": checkpoint.last_successful_trading_day.isoformat(),
        "status": "passed",
        "authorization_hash": checkpoint.authorization_hash,
        "checkpoint_status": checkpoint.status,
        "last_success_at": (
            checkpoint.last_success_at.isoformat()
            if checkpoint.last_success_at is not None
            else None
        ),
    }


def _collect_source_facts(
    session: Any,
    actual_contract: str,
    project_root: Path,
) -> str:
    from sqlalchemy import select

    from app.models.data_center import (
        MarketDataFile,
        DataProfile,
        ProfileActiveBinding,
    )
    from guiyi_quant.indicators import (
        closed_bar_observation_policy_sha256,
        htdy_original_source_sha256,
    )

    rows = list(
        session.execute(
            select(ProfileActiveBinding, MarketDataFile)
            .join(
                MarketDataFile,
                MarketDataFile.id
                == ProfileActiveBinding.market_data_file_id,
            )
            .where(
                ProfileActiveBinding.profile_id
                == "live_observation_v1",
                ProfileActiveBinding.binding_status == "active",
                ProfileActiveBinding.instrument_symbol == "jm",
                ProfileActiveBinding.contract_code == actual_contract,
                ProfileActiveBinding.period.in_(("1m", "15m")),
                MarketDataFile.provider == "rqdata",
                MarketDataFile.data_role == "primary",
                MarketDataFile.quality_status == "passed",
            )
            .order_by(ProfileActiveBinding.id)
        ).all()
    )
    profile = session.scalar(
        select(DataProfile).where(
            DataProfile.profile_id == "live_observation_v1",
            DataProfile.is_active.is_(True),
        )
    )
    profile_payload = _source_binding_payload(
        rows,
        actual_contract=actual_contract,
        profile=profile,
        project_root=project_root,
    )
    return canonical_hash(
        {
            "profile_sha256": canonical_hash(
                {
                    "profile": {
                        "profile_id": profile.profile_id,
                        "provider": profile.provider,
                        "quality_policy": profile.quality_policy,
                        "contract_roles": list(
                            profile.contract_roles or []
                        ),
                        "periods": list(profile.periods or []),
                        "is_active": profile.is_active,
                    },
                    "bindings": profile_payload,
                }
            ),
            "indicator_source_sha256": htdy_original_source_sha256(),
            "policy_sha256": closed_bar_observation_policy_sha256(),
            "global_wechat_autosend": False,
            "auto_order": False,
        }
    )


def _source_binding_payload(
    rows: list[tuple[Any, Any]],
    *,
    actual_contract: str,
    profile: Any,
    project_root: Path,
) -> list[dict[str, Any]]:
    if (
        profile is None
        or profile.provider != "rqdata"
        or profile.quality_policy != "active_entry"
        or "actual_contract" not in (profile.contract_roles or [])
        or not {"1m", "15m"}.issubset(set(profile.periods or []))
        or len(rows) != 2
        or {binding.period for binding, _market_file in rows}
        != {"1m", "15m"}
        or any(
            binding.binding_status != "active"
            or binding.instrument_symbol != "jm"
            or binding.contract_code != actual_contract
            or binding.contract_role != "actual_contract"
            or binding.instrument_symbol
            != market_file.instrument_symbol
            or binding.contract_code != market_file.contract_code
            or binding.period != market_file.period
            or binding.data_version != market_file.data_version
            or market_file.provider != "rqdata"
            or market_file.data_type != "bars"
            or market_file.data_role != "primary"
            or market_file.quality_status != "passed"
            or not market_file.checksum
            or not isinstance(market_file.row_count, int)
            or market_file.row_count <= 0
            for binding, market_file in rows
        )
    ):
        raise HtDyS610LongRunningError(
            "active_source_binding_invalid"
        )
    for _binding, market_file in rows:
        file_path = Path(str(market_file.file_path))
        resolved = (
            file_path
            if file_path.is_absolute()
            else project_root / file_path
        )
        if (
            not resolved.is_file()
            or _sha256_file(resolved) != market_file.checksum
        ):
            raise HtDyS610LongRunningError(
                "active_source_checksum_drift"
            )
    return [
        {
            "binding_id": binding.id,
            "market_data_file_id": market_file.id,
            "binding_status": binding.binding_status,
            "contract_role": binding.contract_role,
            "symbol": market_file.instrument_symbol,
            "contract": market_file.contract_code,
            "period": market_file.period,
            "provider": market_file.provider,
            "data_type": market_file.data_type,
            "data_version": market_file.data_version,
            "checksum": market_file.checksum,
            "start_time": market_file.start_time.isoformat(),
            "end_time": market_file.end_time.isoformat(),
            "row_count": market_file.row_count,
            "quality_status": market_file.quality_status,
            "data_role": market_file.data_role,
        }
        for binding, market_file in rows
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_runtime_identity(root: Path) -> tuple[str, str]:
    from app.services.htdy_s6_10_runtime_support import (
        _git,
        _git_tree_hash,
    )

    resolved = root.resolve(strict=True)
    if _git(resolved, "status", "--porcelain=v1") != "":
        raise HtDyS610LongRunningError("runtime_tracked_tree_dirty")
    return (
        _git(resolved, "rev-parse", "HEAD"),
        _git_tree_hash(resolved),
    )


def build_runtime_gate(
    *,
    approval_packet_path: Path,
    approval_hash: str,
    environ: Mapping[str, str],
) -> HtDyS610LongRunningRuntimeGate:
    """Build the production gate from the signed D root and local Runtime."""

    try:
        request = json.loads(
            approval_packet_path.resolve(strict=True).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610LongRunningError(
            "approval_d_request_invalid"
        ) from exc
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != 1
        or request.get("request_type")
        != "htdy_s6_10_approval_d_no_code_promotion"
        or request.get("request_hash") != _request_hash(request)
    ):
        raise HtDyS610LongRunningError("approval_d_request_invalid")
    if str(environ.get("GUIYI_WECHAT_AUTOSEND_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise HtDyS610LongRunningError(
            "global_wechat_autosend_must_remain_disabled"
        )
    required_values = {
        "receipt": str(
            environ.get("GUIYI_HTDY_S610_APPROVAL_D_RECEIPT") or ""
        ),
        "signature": str(
            environ.get("GUIYI_HTDY_S610_APPROVAL_D_SIGNATURE") or ""
        ),
        "signers": str(
            environ.get("GUIYI_HTDY_S610_APPROVED_SIGNERS") or ""
        ),
        "daily_root": str(
            environ.get("GUIYI_HTDY_S610_DAILY_CHILD_ROOT") or ""
        ),
        "runtime_root": str(environ.get("GUIYI_PROJECT_ROOT") or ""),
    }
    if not all(value.strip() for value in required_values.values()):
        raise HtDyS610LongRunningError(
            "approval_d_runtime_artifact_missing"
        )
    required = {
        key: Path(value) for key, value in required_values.items()
    }
    try:
        receipt_path = required["receipt"].resolve(strict=True)
        signature_path = required["signature"].resolve(strict=True)
        signers_path = required["signers"].resolve(strict=True)
        daily_root = required["daily_root"].resolve(strict=True)
        runtime_root = required["runtime_root"].resolve(strict=True)
    except OSError as exc:
        raise HtDyS610LongRunningError(
            "approval_d_runtime_artifact_missing"
        ) from exc

    def verify() -> None:
        verify_signed_approval_d_receipt(
            request=request,
            receipt_path=receipt_path,
            signature_path=signature_path,
            approved_signers_path=signers_path,
            approval_hash=approval_hash,
        )
        runtime_commit, runtime_tree = _collect_runtime_identity(
            runtime_root
        )
        if (
            runtime_commit != request.get("runtime_commit")
            or runtime_tree != request.get("runtime_tree")
        ):
            raise HtDyS610LongRunningError("no_code_binding_drift")

    def collect(
        session: Any,
        current: datetime,
        allow_mapping_create: bool,
    ) -> Mapping[str, Any]:
        def collect_mapping(
            active_session: Any,
            trading_day: date,
            create_requested: bool,
        ) -> Mapping[str, Any]:
            return _runtime_daily_mapping(
                active_session,
                trading_day=trading_day,
                daily_root=daily_root,
                approval_d_hash=approval_hash,
                allow_create=(
                    allow_mapping_create and create_requested
                ),
            )

        return collect_long_running_daily_facts(
            session,
            current,
            eod_authorization_hash=str(
                request["eod_authorization_hash"]
            ),
            runtime_root=runtime_root,
            mapping_collector=collect_mapping,
            prepare_preopen_mapping=allow_mapping_create,
        )

    def build_child(**facts: Any) -> Mapping[str, Any]:
        return build_long_running_daily_child(
            approval_d_receipt_path=receipt_path,
            approval_d_signature_path=signature_path,
            approved_signers_path=signers_path,
            **facts,
        )

    from app.services.htdy_s6_10_runtime_support import runtime_handler_v6

    return HtDyS610LongRunningRuntimeGate(
        approval_d_request=request,
        approval_d_hash=approval_hash,
        approval_verifier=verify,
        daily_facts_collector=collect,
        child_builder=build_child,
        mapping_receipt_publisher=lambda receipt, **kwargs: (
            publish_daily_mapping_receipt_create_only(
                receipt,
                root=daily_root,
                **kwargs,
            )
        ),
        child_publisher=lambda child, **kwargs: publish_daily_child_create_only(
            child,
            root=daily_root,
            **kwargs,
        ),
        handler_factory=runtime_handler_v6,
    )
