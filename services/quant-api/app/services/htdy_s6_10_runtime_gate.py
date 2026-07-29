"""Runtime authorization adapter for the HTDY S6-10 five-day window."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any

from app.services.htdy_s6_10_stability import (
    HtDyS610Error,
    build_daily_child,
    publish_json_create_only,
    verify_daily_child,
    verify_approval_c_bundle,
    verify_parent_packet,
)


class HtDyS610RuntimeGate:
    """Keep the event writer inside one approved five-day observation window."""

    def __init__(
        self,
        *,
        parent_packet_path: Path,
        approval_hash: str,
        current_bindings: Callable[[Any], Mapping[str, Any]],
        current_daily_state: Callable[[Any, date], Mapping[str, Any]],
        handler_factory: Callable[[Any], Any],
        trading_day_resolver: Callable[
            [Any, datetime, Mapping[str, Any]], date
        ],
        now: Callable[[], datetime] | None = None,
        approval_c_verifier: Callable[[], None] | None = None,
    ) -> None:
        self.parent_packet_path = parent_packet_path.resolve(strict=False)
        self.parent_packet = _load_json(self.parent_packet_path)
        self.approval_hash = approval_hash
        self.current_bindings = current_bindings
        self.current_daily_state = current_daily_state
        self.handler_factory = handler_factory
        self.trading_day_resolver = trading_day_resolver
        self.now = now or (lambda: datetime.now(UTC))
        self.approval_c_verifier = approval_c_verifier or (lambda: None)
        self._active_child: dict[str, Any] | None = None
        self._active_state: dict[str, Any] | None = None

    def __call__(
        self,
        session: Any,
        *,
        phase: str,
        result: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if phase == "verify":
            return self._verify(session)
        if phase == "pre_write":
            return self._pre_write(session)
        if phase == "post_write":
            return self._post_write(session, result or {})
        if phase == "after_commit":
            return self._metadata()
        raise HtDyS610Error("runtime_gate_phase_invalid")

    def _verify(self, session: Any) -> Mapping[str, Any]:
        self.approval_c_verifier()
        verify_parent_packet(
            self.parent_packet,
            approval_hash=self.approval_hash,
            current_bindings=self.current_bindings(session),
            now=self.now(),
            allow_started=True,
        )
        return {
            "gate_status": "verified",
            "authorization_hash": self.approval_hash,
        }

    def _pre_write(self, session: Any) -> Mapping[str, Any]:
        self._verify(session)
        current = self.now()
        window_start = datetime.fromisoformat(
            str(self.parent_packet["window_start"])
        )
        if current.astimezone(UTC) < window_start.astimezone(UTC):
            return {
                **self._metadata(),
                "gate_status": "waiting",
            }
        trading_day = self.trading_day_resolver(
            session,
            current,
            self.parent_packet,
        )
        days = tuple(
            date.fromisoformat(str(item))
            for item in self.parent_packet.get("trading_days", ())
        )
        if trading_day not in days:
            raise HtDyS610Error("runtime_trading_day_outside_window")
        state = dict(self.current_daily_state(session, trading_day))
        if state.get("trading_day") != trading_day:
            raise HtDyS610Error("runtime_trading_day_drift")
        day_root = (
            self.parent_packet_path.parent
            / "daily"
            / trading_day.isoformat()
        )
        child_path = day_root / "child_packet.json"
        previous_seal = _previous_seal(
            parent_root=self.parent_packet_path.parent,
            days=days,
            trading_day=trading_day,
        )
        if child_path.exists():
            child = _load_json(child_path)
        else:
            child = build_daily_child(
                parent_packet=self.parent_packet,
                parent_approval_hash=self.approval_hash,
                trading_day=trading_day,
                actual_contract=str(state["actual_contract"]),
                mapping_sha256=str(state["mapping_sha256"]),
                session_geometry_sha256=str(
                    state["session_geometry_sha256"]
                ),
                source_facts_sha256=str(state["source_facts_sha256"]),
                beginning_state=state["beginning_state"],
                previous_daily_seal_sha256=previous_seal,
            )
            publish_json_create_only(child_path, child)
        verify_daily_child(
            child,
            approval_hash=str(child.get("packet_hash") or ""),
            parent_packet=self.parent_packet,
            current_actual_contract=str(state["actual_contract"]),
            current_mapping_sha256=str(state["mapping_sha256"]),
            current_session_geometry_sha256=str(
                state["session_geometry_sha256"]
            ),
            current_source_facts_sha256=str(state["source_facts_sha256"]),
            current_beginning_state=state["beginning_state"],
            current_previous_daily_seal_sha256=previous_seal,
        )
        self._active_child = child
        self._active_state = state
        return {
            **self._metadata(),
            "signal_event_handler": self.handler_factory(session),
        }

    def _post_write(
        self,
        session: Any,
        result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self._active_child is None or self._active_state is None:
            raise HtDyS610Error("runtime_gate_pre_write_required")
        event_result = dict(result.get("signal_events") or {})
        for key in ("created", "unchanged", "changed", "blocked"):
            if type(event_result.get(key)) is not int:
                raise HtDyS610Error("runtime_event_result_invalid")
        if event_result["changed"] != 0:
            raise HtDyS610Error("signal_changed_forbidden")
        if event_result["created"] < 0 or event_result["unchanged"] < 0:
            raise HtDyS610Error("runtime_event_result_invalid")
        if event_result["blocked"] > 0 and (
            event_result["created"] > 0 or event_result["unchanged"] > 0
        ):
            raise HtDyS610Error("blocked_round_mixed_write")
        trading_day = date.fromisoformat(
            str(self._active_child["trading_day"])
        )
        state = dict(self.current_daily_state(session, trading_day))
        _verify_post_state(
            initial=self._active_state,
            current=state,
            created=event_result["created"],
        )
        return self._metadata()

    def _metadata(self) -> dict[str, Any]:
        return {
            "gate_status": "authorized",
            "gate_schema": "s6_10",
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
) -> HtDyS610RuntimeGate:
    """Build from production collectors.

    The collector module is imported lazily so unit tests can use the pure
    state machine without opening DB, Redis, RQData, or launchd.
    """

    from app.services.htdy_s6_10_runtime_support import (
        collect_current_bindings,
        collect_current_daily_state,
        resolve_runtime_trading_day,
        runtime_handler,
    )

    packet = _load_json(parent_packet_path)
    bundle_value = str(environ.get("GUIYI_HTDY_S610_APPROVAL_C_BUNDLE") or "")
    bundle_hash = str(environ.get("GUIYI_HTDY_S610_APPROVAL_C_HASH") or "")
    receipt_value = str(
        environ.get("GUIYI_HTDY_S610_APPROVAL_C_RECEIPT") or ""
    )
    signature_value = str(
        environ.get("GUIYI_HTDY_S610_APPROVAL_C_SIGNATURE") or ""
    )
    signers_value = str(
        environ.get("GUIYI_HTDY_S610_APPROVED_SIGNERS") or ""
    )
    if not all(
        (
            bundle_value,
            bundle_hash,
            receipt_value,
            signature_value,
            signers_value,
        )
    ):
        raise HtDyS610Error("approval_c_signed_receipt_required")
    verify_approval_c_bundle(
        Path(bundle_value),
        approval_c_hash=bundle_hash,
        parent_packet=packet,
        parent_packet_path=parent_packet_path,
        approval_receipt_path=Path(receipt_value),
        approval_signature_path=Path(signature_value),
        approved_signers_path=Path(signers_value),
    )
    return HtDyS610RuntimeGate(
        parent_packet_path=parent_packet_path,
        approval_hash=approval_hash,
        current_bindings=lambda session: collect_current_bindings(
            session,
            parent_packet=packet,
            parent_packet_path=parent_packet_path,
            environ=environ,
        ),
        current_daily_state=lambda session, day: collect_current_daily_state(
            session,
            parent_packet=packet,
            trading_day=day,
            environ=environ,
        ),
        handler_factory=runtime_handler,
        trading_day_resolver=resolve_runtime_trading_day,
        approval_c_verifier=lambda: verify_approval_c_bundle(
            Path(bundle_value),
            approval_c_hash=bundle_hash,
            parent_packet=packet,
            parent_packet_path=parent_packet_path,
            approval_receipt_path=Path(receipt_value),
            approval_signature_path=Path(signature_value),
            approved_signers_path=Path(signers_value),
        ),
    )


def _verify_post_state(
    *,
    initial: Mapping[str, Any],
    current: Mapping[str, Any],
    created: int,
) -> None:
    before = dict(initial.get("counts") or {})
    after = dict(current.get("counts") or {})
    if after.get("signal_notifications") != before.get(
        "signal_notifications"
    ):
        raise HtDyS610Error("notification_count_drift")
    for key in ("review_notes", "orders", "trades"):
        if after.get(key) != before.get(key):
            raise HtDyS610Error(f"{key}_count_drift")
    if after.get("signal_events") != before.get("signal_events", 0) + created:
        raise HtDyS610Error("signal_event_count_drift")
    before_ids = initial.get("event_ids")
    after_ids = current.get("event_ids")
    events = current.get("new_events")
    if (
        not isinstance(before_ids, list)
        or not isinstance(after_ids, list)
        or not isinstance(events, list)
        or not set(before_ids).issubset(set(after_ids))
        or len(set(after_ids) - set(before_ids)) != created
        or {item.get("id") for item in events if isinstance(item, Mapping)}
        != set(after_ids)
    ):
        raise HtDyS610Error("signal_event_lineage_incomplete")
    if after.get("signal_events", 0) > before.get("signal_events", 0) + 160:
        raise HtDyS610Error("signal_event_limit_exceeded")
    if current.get("hashes") != initial.get("hashes"):
        raise HtDyS610Error("forbidden_hash_drift")


def _previous_seal(
    *,
    parent_root: Path,
    days: tuple[date, ...],
    trading_day: date,
) -> str | None:
    index = days.index(trading_day)
    if index == 0:
        return None
    path = (
        parent_root
        / "daily"
        / days[index - 1].isoformat()
        / "daily_seal.json"
    )
    if not path.exists():
        raise HtDyS610Error("previous_daily_seal_missing")
    payload = _load_json(path)
    value = payload.get("seal_hash")
    if not isinstance(value, str):
        raise HtDyS610Error("previous_daily_seal_invalid")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610Error("runtime_packet_invalid") from exc
    if not isinstance(payload, dict):
        raise HtDyS610Error("runtime_packet_invalid")
    return payload
