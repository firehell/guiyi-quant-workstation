"""Concrete, Gate-bound data side of the fixed product-retirement run.

This class deliberately owns only the destructive retirement transaction.  It
does not select products, discover arbitrary roots, or start services.  Those
decisions belong to :mod:`product_retirement_runtime_gate`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Connection

from app.data_core.product_retirement import (
    apply_retirement_packet,
    build_inventory_packet,
    build_runtime_gate_attestation,
    finalize_retirement_files,
    inventory_database,
    inventory_files,
    packet_digest,
    verify_retirement_scope,
)
from app.services.product_retirement_runtime_gate import append_journal


class RetainedUniverseRefresher:
    """The narrow post-retirement data update boundary."""

    def sync_direct(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None: ...

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None: ...


class ProductRetirementDataOperator:
    """Run exact retirement DML only after the Runtime Gate precommit phase."""

    def __init__(
        self,
        *,
        connection_factory: Callable[[], Connection],
        roots: Mapping[str, Path],
        protected_root: Path,
        database_revision: str,
        now: Callable[[], str] | None = None,
        refresher: RetainedUniverseRefresher | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._roots = dict(roots)
        self._protected_root = protected_root
        self._database_revision = database_revision
        self._now = now or _now_iso
        self._refresher = refresher

    def inventory(self, *, runtime_sha: str) -> dict[str, Any]:
        """Capture the exact data scope while the approved Runtime is stopped."""

        with self._connection_factory() as connection:
            files, file_blockers = inventory_files(self._roots)
            rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*file_blockers, *database_blockers),
            code_sha=runtime_sha,
            runtime_sha=runtime_sha,
            database_revision=self._database_revision,
            generated_at=self._now(),
            roots=self._roots,
        )
        return {
            "packet": packet,
            "packet_sha256": packet_digest(packet),
            "packet_root": str(self._protected_root.resolve(strict=True)),
        }

    def apply(
        self,
        inventory: Mapping[str, Any],
        precommit: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        packet, expected_digest = _inventory_packet(inventory)
        runtime_sha = _required_text(precommit, "runtime_sha")
        run_id = _required_text(precommit, "run_id")
        release_tag = _required_text(precommit, "release_tag")
        shutdown_digest = _required_sha(precommit, "shutdown_receipt_sha256")
        approval = build_runtime_gate_attestation(
            packet,
            shutdown_receipt_digest=shutdown_digest,
            run_id=run_id,
            release_tag=release_tag,
            expires_at=_expires_at(self._now()),
        )
        approval_digest = _json_sha256(approval)
        with self._connection_factory() as connection:
            receipt = apply_retirement_packet(
                connection,
                packet=packet,
                expected_packet_digest=expected_digest,
                approval=approval,
                roots=self._roots,
                code_sha=runtime_sha,
                runtime_sha=runtime_sha,
                database_revision=self._database_revision,
                shutdown_receipt_digest=shutdown_digest,
                now=self._now(),
                approval_digest=approval_digest,
                packet_root=Path(str(inventory["packet_root"])),
            )
        if receipt.get("status") == "db_committed_purge_pending":
            append_journal(
                self._protected_root,
                {
                    "schema_version": 1,
                    "status": "db_committed_purge_pending",
                    "run_id": run_id,
                    "release_tag": release_tag,
                    "runtime_sha": runtime_sha,
                    "shutdown_receipt_sha256": shutdown_digest,
                    "inventory": dict(inventory),
                    "receipt": dict(receipt),
                },
            )
        return receipt

    def finalize(
        self,
        inventory: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        packet, expected_digest = _inventory_packet(inventory)
        with self._connection_factory() as connection:
            return finalize_retirement_files(
                connection,
                packet=packet,
                expected_packet_digest=expected_digest,
                prior_receipt=receipt,
                roots=self._roots,
                packet_root=Path(str(inventory["packet_root"])),
            )

    def verify(self) -> Mapping[str, Any]:
        with self._connection_factory() as connection:
            return verify_retirement_scope(connection, roots=self._roots)

    def sync_direct(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None:
        _require_exact_periods(frequencies, ("1m", "1d", "1w"))
        _require_refresher(self._refresher).sync_direct(products, frequencies)

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None:
        _require_exact_periods(frequencies, ("5m", "15m", "30m", "60m"))
        _require_refresher(self._refresher).aggregate(products, frequencies)


def _inventory_packet(inventory: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    packet = inventory.get("packet")
    expected_digest = inventory.get("packet_sha256")
    if not isinstance(packet, Mapping) or not isinstance(expected_digest, str):
        raise ValueError("PRODUCT_RETIREMENT_EXECUTION_INVENTORY_INVALID")
    if packet_digest(packet) != expected_digest:
        raise ValueError("PRODUCT_RETIREMENT_EXECUTION_PACKET_DIGEST_MISMATCH")
    return packet, expected_digest


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"PRODUCT_RETIREMENT_EXECUTION_{key.upper()}_INVALID")
    return value.strip()


def _required_sha(payload: Mapping[str, Any], key: str) -> str:
    value = _required_text(payload, key)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"PRODUCT_RETIREMENT_EXECUTION_{key.upper()}_INVALID")
    return value


def _json_sha256(value: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _expires_at(now: str) -> str:
    try:
        value = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("PRODUCT_RETIREMENT_EXECUTION_NOW_INVALID") from exc
    if value.tzinfo is None:
        raise ValueError("PRODUCT_RETIREMENT_EXECUTION_NOW_INVALID")
    return (value.astimezone(UTC) + timedelta(hours=1)).isoformat()


def _require_refresher(
    refresher: RetainedUniverseRefresher | None,
) -> RetainedUniverseRefresher:
    if refresher is None:
        raise ValueError("PRODUCT_RETIREMENT_RETAINED_REFRESHER_NOT_CONFIGURED")
    return refresher


def _require_exact_periods(actual: tuple[str, ...], expected: tuple[str, ...]) -> None:
    if actual != expected:
        raise ValueError("PRODUCT_RETIREMENT_REFRESH_FREQUENCIES_INVALID")
