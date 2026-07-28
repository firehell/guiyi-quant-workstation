"""Runtime adapter for an exact schema-v5 Approval C2."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any

from app.services.htdy_s6_10_one_day import (
    HtDyS610OneDayError,
    canonical_hash,
    verify_one_day_parent_packet,
)


class HtDyS610OneDayRuntimeGate:
    def __init__(
        self,
        *,
        parent_packet_path: Path,
        approval_hash: str,
        current_bindings: Callable[[Any], Mapping[str, Any]],
        handler_factory: Callable[[Any], Any],
        trading_day_resolver: Callable[[Any, datetime, Mapping[str, Any]], date],
        approval_c2_verifier: Callable[[], None],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.parent_packet_path = parent_packet_path.resolve(strict=True)
        self.parent_packet = _load_json(self.parent_packet_path)
        self.approval_hash = approval_hash
        self.current_bindings = current_bindings
        self.handler_factory = handler_factory
        self.trading_day_resolver = trading_day_resolver
        self.approval_c2_verifier = approval_c2_verifier
        self.now = now or (lambda: datetime.now(UTC))

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
            self._verify(session)
            current = self.now()
            start = datetime.fromisoformat(self.parent_packet["window_start"])
            if current.astimezone(UTC) < start.astimezone(UTC):
                return {**self._metadata(), "gate_status": "waiting"}
            resolved = self.trading_day_resolver(
                session, current, self.parent_packet
            )
            target = date.fromisoformat(self.parent_packet["trading_days"][0])
            if resolved != target:
                raise HtDyS610OneDayError(
                    "runtime_trading_day_outside_window"
                )
            return {
                **self._metadata(),
                "signal_event_handler": self.handler_factory(session),
            }
        if phase == "post_write":
            event_result = dict((result or {}).get("signal_events") or {})
            if event_result.get("changed") != 0:
                raise HtDyS610OneDayError("signal_changed_forbidden")
            return self._metadata()
        if phase == "after_commit":
            return self._metadata()
        raise HtDyS610OneDayError("runtime_gate_phase_invalid")

    def _verify(self, session: Any) -> Mapping[str, Any]:
        self.approval_c2_verifier()
        verify_one_day_parent_packet(
            self.parent_packet,
            approval_hash=self.approval_hash,
            current_bindings=self.current_bindings(session),
            now=self.now(),
            allow_started=True,
        )
        return {**self._metadata(), "gate_status": "verified"}

    def _metadata(self) -> dict[str, Any]:
        return {
            "gate_status": "authorized",
            "gate_schema": "s6_10_schema_v5",
            "authorization_hash": self.approval_hash,
            "target_trading_day": self.parent_packet["trading_days"][0],
        }


def build_runtime_gate(
    *,
    parent_packet_path: Path,
    approval_hash: str,
    environ: Mapping[str, str],
) -> HtDyS610OneDayRuntimeGate:
    from app.services.htdy_s6_10_runtime_support import (
        collect_current_one_day_bindings,
        resolve_runtime_trading_day,
        runtime_handler_v5,
    )

    receipt_value = str(
        environ.get("GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT") or ""
    )
    receipt_hash = str(
        environ.get("GUIYI_HTDY_S610_APPROVAL_C2_HASH") or ""
    )
    signature_value = str(
        environ.get("GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE") or ""
    )
    signers_value = str(
        environ.get("GUIYI_HTDY_S610_APPROVED_SIGNERS") or ""
    )
    if not all(
        (receipt_value, receipt_hash, signature_value, signers_value)
    ):
        raise HtDyS610OneDayError("approval_c2_signed_receipt_required")
    receipt_path = Path(receipt_value)
    signature_path = Path(signature_value)
    signers_path = Path(signers_value)
    parent = _load_json(parent_packet_path)

    def verify_receipt() -> None:
        from app.services.htdy_s6_10_stability import (
            _file_sha256,
            _verify_approved_signers_trust_root,
            _verify_ssh_signature,
        )

        receipt = _load_json(receipt_path)
        receipt_bytes = receipt_path.read_bytes()
        expected_signer_hash = (parent.get("bindings") or {}).get(
            "approval_c2_approved_signers_sha256"
        )
        try:
            approved_at = datetime.fromisoformat(
                str(receipt.get("approved_at") or "")
            )
        except ValueError as exc:
            raise HtDyS610OneDayError(
                "approval_c2_receipt_invalid"
            ) from exc
        if (
            receipt.get("schema_version") != 1
            or receipt.get("approval") != "Approval C2"
            or receipt.get("decision") != "approved"
            or receipt.get("parent_packet_hash") != approval_hash
            or receipt.get("trading_day")
            != parent["trading_days"][0]
            or receipt.get("max_wecom_notifications") != 23
            or receipt.get("max_attempts_per_event") != 3
            or receipt.get("global_wechat_autosend") is not False
            or receipt.get("receipt_hash") != receipt_hash
            or canonical_hash(receipt) != receipt_hash
            or approved_at >= datetime.fromisoformat(parent["window_start"])
            or _file_sha256(signers_path) != expected_signer_hash
            or not _verify_approved_signers_trust_root(signers_path)
            or not _verify_ssh_signature(
                receipt_bytes, signature_path, signers_path
            )
        ):
            raise HtDyS610OneDayError("approval_c2_receipt_invalid")

    return HtDyS610OneDayRuntimeGate(
        parent_packet_path=parent_packet_path,
        approval_hash=approval_hash,
        current_bindings=lambda session: collect_current_one_day_bindings(
            session,
            parent_packet=parent,
            parent_packet_path=parent_packet_path,
            environ=environ,
        ),
        handler_factory=runtime_handler_v5,
        trading_day_resolver=resolve_runtime_trading_day,
        approval_c2_verifier=verify_receipt,
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610OneDayError("artifact_invalid") from exc
    if not isinstance(value, dict):
        raise HtDyS610OneDayError("artifact_invalid")
    return value
