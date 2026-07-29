"""Runtime adapter for an activated schema-v7 remainder window."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any

from app.services.htdy_s6_10_remaining_window import (
    HtDyS610RemainingWindowError,
    canonical_hash,
    verify_activation_receipt,
    verify_remaining_window_approval_times,
    verify_remaining_window_parent_packet,
)


class HtDyS610RemainingWindowRuntimeGate:
    def __init__(
        self,
        *,
        parent_packet_path: Path,
        approval_hash: str,
        activation_receipt_path: Path,
        current_bindings: Callable[[Any, str], Mapping[str, Any]],
        handler_factory: Callable[..., Any],
        trading_day_resolver: Callable[
            [Any, datetime, Mapping[str, Any]], date
        ],
        approval_c2_verifier: Callable[[Mapping[str, Any]], None],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.parent_packet_path = parent_packet_path.resolve(strict=True)
        self.parent_packet = _load_json(self.parent_packet_path)
        self.activation_receipt = _load_json(
            activation_receipt_path.resolve(strict=True)
        )
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
            window_end = datetime.fromisoformat(
                str(self.parent_packet["window_end"])
            )
            if current.astimezone(UTC) >= window_end.astimezone(UTC):
                return {**self._metadata(), "gate_status": "closed"}
            target = date.fromisoformat(
                str(self.parent_packet["trading_days"][0])
            )
            if (
                self.trading_day_resolver(
                    session,
                    current,
                    self.parent_packet,
                )
                != target
            ):
                raise HtDyS610RemainingWindowError(
                    "runtime_trading_day_outside_window"
                )
            allowed = {
                datetime.fromisoformat(value)
                for value in self.activation_receipt[
                    "expected_bucket_ends"
                ]
            }
            handler = self.handler_factory(
                session,
                allowed_bucket_ends=allowed,
            )
            self._last_handler = handler
            return {
                **self._metadata(),
                "signal_event_handler": handler,
            }
        if phase == "post_write":
            event_result = dict((result or {}).get("signal_events") or {})
            if event_result and event_result.get("changed") != 0:
                raise HtDyS610RemainingWindowError(
                    "signal_changed_forbidden"
                )
            return self._metadata()
        if phase == "after_commit":
            return self._metadata()
        raise HtDyS610RemainingWindowError("runtime_gate_phase_invalid")

    def _verify(self, session: Any) -> Mapping[str, Any]:
        verify_activation_receipt(
            parent_packet=self.parent_packet,
            activation_receipt=self.activation_receipt,
        )
        self.approval_c2_verifier(self.activation_receipt)
        verify_remaining_window_parent_packet(
            self.parent_packet,
            approval_hash=self.approval_hash,
            current_bindings=self.current_bindings(session, "post_activation"),
        )
        return {**self._metadata(), "gate_status": "verified"}

    def _metadata(self) -> dict[str, Any]:
        last_handler = getattr(self, "_last_handler", None)
        last_decision = getattr(
            last_handler,
            "last_decision_bucket_end",
            None,
        )
        return {
            "gate_status": "authorized",
            "gate_schema": (
                f"s6_10_schema_v{self.parent_packet['schema_version']}"
            ),
            "authorization_hash": self.approval_hash,
            "activation_receipt_hash": self.activation_receipt[
                "receipt_hash"
            ],
            "target_trading_day": self.parent_packet["trading_days"][0],
            "expected_bucket_ends": list(
                self.activation_receipt["expected_bucket_ends"]
            ),
            "last_decision_bucket_end": (
                last_decision.isoformat()
                if isinstance(last_decision, datetime)
                else None
            ),
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610RemainingWindowError("artifact_invalid") from exc
    if not isinstance(value, dict):
        raise HtDyS610RemainingWindowError("artifact_invalid")
    return value


def build_runtime_gate(
    *,
    parent_packet_path: Path,
    approval_hash: str,
    environ: Mapping[str, str],
) -> HtDyS610RemainingWindowRuntimeGate:
    from app.services.htdy_s6_10_runtime_support import (
        collect_current_one_day_bindings,
        resolve_runtime_trading_day,
        runtime_handler_v6,
    )

    required = {
        "receipt": str(
            environ.get("GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT") or ""
        ),
        "receipt_hash": str(
            environ.get("GUIYI_HTDY_S610_APPROVAL_C2_HASH") or ""
        ),
        "signature": str(
            environ.get("GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE") or ""
        ),
        "signers": str(
            environ.get("GUIYI_HTDY_S610_APPROVED_SIGNERS") or ""
        ),
        "activation": str(
            environ.get("GUIYI_HTDY_S610_ACTIVATION_RECEIPT") or ""
        ),
    }
    if not all(required.values()):
        raise HtDyS610RemainingWindowError(
            "remaining_window_artifacts_required"
        )
    receipt_path = Path(required["receipt"])
    signature_path = Path(required["signature"])
    signers_path = Path(required["signers"])
    activation_path = Path(required["activation"])
    parent = _load_json(parent_packet_path)

    def verify_receipt(
        activation_receipt: Mapping[str, Any],
    ) -> None:
        from app.services.htdy_s6_10_stability import (
            _file_sha256,
            _verify_approved_signers_trust_root,
            _verify_ssh_signature,
        )

        receipt = _load_json(receipt_path)
        try:
            approved_at = datetime.fromisoformat(
                str(receipt.get("approved_at") or "")
            )
        except ValueError as exc:
            raise HtDyS610RemainingWindowError(
                "approval_c2_receipt_invalid"
            ) from exc
        verify_remaining_window_approval_times(
            parent_packet=parent,
            activation_receipt=activation_receipt,
            approved_at=approved_at,
        )
        expected_signer_hash = (parent.get("bindings") or {}).get(
            "approval_c2_approved_signers_sha256"
        )
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
            or receipt.get("receipt_hash") != required["receipt_hash"]
            or canonical_hash(receipt) != required["receipt_hash"]
            or _file_sha256(signers_path) != expected_signer_hash
            or not _verify_approved_signers_trust_root(signers_path)
            or not _verify_ssh_signature(
                receipt_path.read_bytes(),
                signature_path,
                signers_path,
            )
        ):
            raise HtDyS610RemainingWindowError(
                "approval_c2_receipt_invalid"
            )

    return HtDyS610RemainingWindowRuntimeGate(
        parent_packet_path=parent_packet_path,
        approval_hash=approval_hash,
        activation_receipt_path=activation_path,
        current_bindings=lambda session, _phase: (
            collect_current_one_day_bindings(
                session,
                parent_packet=parent,
                parent_packet_path=parent_packet_path,
                environ=environ,
            )
        ),
        handler_factory=runtime_handler_v6,
        trading_day_resolver=resolve_runtime_trading_day,
        approval_c2_verifier=verify_receipt,
    )
