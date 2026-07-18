from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataProfile, ProfileActiveBinding
from app.services.data_profile_registry import (
    ACTIVE_BINDING_STATUS,
    DataProfileRegistry,
    SUPERSEDED_BINDING_STATUS,
)
from app.services.profile_binding_validator import (
    ProfileBindingValidationError,
    validate_profile_binding_target,
)


def _resolve_current_active_binding(
    session: Session,
    *,
    profile_id: str,
    binding_id: int | None,
    instrument_symbol: str | None,
    contract_code: str | None,
    period: str | None,
    lock: bool = False,
) -> ProfileActiveBinding:
    if binding_id is not None:
        statement = select(ProfileActiveBinding).where(
            ProfileActiveBinding.profile_id == profile_id,
            ProfileActiveBinding.id == binding_id,
            ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
        )
        current = session.scalar(statement.with_for_update() if lock else statement)
        if current is None:
            raise ValueError(
                f"active binding not found: profile={profile_id} binding_id={binding_id}"
            )
    else:
        if instrument_symbol is None or contract_code is None or period is None:
            raise ValueError(
                "binding_id or instrument_symbol/contract_code/period is required for rollback"
            )

        statement = select(ProfileActiveBinding).where(
            ProfileActiveBinding.profile_id == profile_id,
            ProfileActiveBinding.instrument_symbol == instrument_symbol,
            ProfileActiveBinding.contract_code == contract_code,
            ProfileActiveBinding.period == period,
            ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
        )
        current = session.scalar(statement.with_for_update() if lock else statement)
        if current is None:
            raise ValueError(
                f"active binding not found: profile={profile_id} "
                f"symbol={instrument_symbol} contract={contract_code} period={period}"
            )

    identity_statement = select(ProfileActiveBinding).where(
        ProfileActiveBinding.profile_id == profile_id,
        ProfileActiveBinding.instrument_symbol == current.instrument_symbol,
        ProfileActiveBinding.contract_code == current.contract_code,
        ProfileActiveBinding.period == current.period,
        ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
    )
    active_for_identity = list(
        session.scalars(
            identity_statement.with_for_update() if lock else identity_statement
        )
    )
    if len(active_for_identity) != 1 or active_for_identity[0].id != current.id:
        raise ValueError(
            "active binding drift: expected exactly one current binding for "
            f"profile={profile_id} symbol={current.instrument_symbol} "
            f"contract={current.contract_code} period={current.period}"
        )
    return current


def _find_previous_binding(
    session: Session,
    *,
    profile_id: str,
    current: ProfileActiveBinding,
    lock: bool = False,
) -> ProfileActiveBinding | None:
    statement = (
        select(ProfileActiveBinding)
        .where(
            ProfileActiveBinding.profile_id == profile_id,
            ProfileActiveBinding.instrument_symbol == current.instrument_symbol,
            ProfileActiveBinding.contract_code == current.contract_code,
            ProfileActiveBinding.period == current.period,
            ProfileActiveBinding.binding_status == SUPERSEDED_BINDING_STATUS,
            ProfileActiveBinding.id < current.id,
        )
        .order_by(ProfileActiveBinding.id.desc())
    )
    return session.scalar(statement.with_for_update() if lock else statement)


def switch_profile_active_binding(
    session: Session,
    *,
    profile_id: str,
    instrument_symbol: str,
    contract_code: str,
    period: str,
    data_version: str,
    market_data_file_id: int | None,
    contract_role: str = "dominant_main",
    dry_run: bool = True,
    commit: bool = False,
    project_root: Path = PROJECT_ROOT,
    expected_previous_binding_id: int | None = None,
    expected_previous_market_data_file_id: int | None = None,
    expected_previous_data_version: str = "",
    enforce_expected_previous: bool = False,
) -> dict[str, Any]:
    registry = DataProfileRegistry(session, project_root=project_root)
    if not dry_run:
        session.scalar(
            select(DataProfile.id)
            .where(DataProfile.profile_id == profile_id)
            .with_for_update()
        )
    current_statement = select(ProfileActiveBinding).where(
        ProfileActiveBinding.profile_id == profile_id,
        ProfileActiveBinding.instrument_symbol == instrument_symbol,
        ProfileActiveBinding.contract_code == contract_code,
        ProfileActiveBinding.period == period,
        ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
    )
    if not dry_run:
        current_statement = current_statement.with_for_update()
    current_rows = list(session.scalars(current_statement))
    if len(current_rows) > 1:
        raise ValueError("multiple active bindings found during compare-and-switch")
    current = current_rows[0] if current_rows else None
    if enforce_expected_previous:
        actual_previous = (
            current.id if current else None,
            current.market_data_file_id if current else None,
            current.data_version if current else "",
        )
        expected_previous = (
            expected_previous_binding_id,
            expected_previous_market_data_file_id,
            expected_previous_data_version,
        )
        if actual_previous != expected_previous:
            raise ValueError(
                f"active binding compare-and-switch drift: expected={expected_previous} actual={actual_previous}"
            )
    validated_file = validate_profile_binding_target(
        session,
        profile_id=profile_id,
        instrument_symbol=instrument_symbol,
        contract_code=contract_code,
        period=period,
        contract_role=contract_role,
        data_version=data_version,
        market_data_file_id=market_data_file_id,
        project_root=project_root,
    )
    result: dict[str, Any] = {
        "profile_id": profile_id,
        "instrument_symbol": instrument_symbol,
        "contract_code": contract_code,
        "period": period,
        "previous_data_version": current.data_version if current else "",
        "previous_binding_id": current.id if current else None,
        "next_data_version": data_version,
        "previous_market_data_file_id": current.market_data_file_id
        if current
        else None,
        "next_market_data_file_id": market_data_file_id,
        "validation": {
            "market_data_file_id": validated_file.id,
            "data_version": validated_file.data_version,
            "quality_status": validated_file.quality_status,
            "provider": validated_file.provider,
            "data_role": validated_file.data_role,
        },
        "dry_run": dry_run,
        "writes_database": not dry_run,
    }
    unchanged = (
        current is not None
        and current.data_version == data_version
        and current.market_data_file_id == market_data_file_id
    )
    if unchanged:
        result["status"] = "unchanged"
        result["binding_id"] = current.id
        result["writes_database"] = False
        return result
    if dry_run:
        return result

    binding = registry.switch_active_binding(
        profile_id=profile_id,
        instrument_symbol=instrument_symbol,
        contract_code=contract_code,
        period=period,
        data_version=data_version,
        market_data_file_id=market_data_file_id,
        contract_role=contract_role,
    )
    result["binding_id"] = binding.id
    result["activated_at"] = binding.activated_at.isoformat()
    if commit:
        session.commit()
    return result


def rollback_profile_active_binding(
    session: Session,
    *,
    profile_id: str,
    binding_id: int | None = None,
    instrument_symbol: str | None = None,
    contract_code: str | None = None,
    period: str | None = None,
    dry_run: bool = True,
    commit: bool = False,
    restore_absent: bool = False,
    expected_previous_binding_id: int | None = None,
    enforce_expected_previous: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        session.scalar(
            select(DataProfile.id)
            .where(DataProfile.profile_id == profile_id)
            .with_for_update()
        )
    current = _resolve_current_active_binding(
        session,
        profile_id=profile_id,
        binding_id=binding_id,
        instrument_symbol=instrument_symbol,
        contract_code=contract_code,
        period=period,
        lock=not dry_run,
    )
    previous = _find_previous_binding(
        session, profile_id=profile_id, current=current, lock=not dry_run
    )
    if (
        enforce_expected_previous
        and (previous.id if previous else None) != expected_previous_binding_id
    ):
        raise ValueError(
            "previous binding drift: "
            f"expected={expected_previous_binding_id} actual={previous.id if previous else None}"
        )
    if restore_absent and previous is not None:
        raise ValueError(
            "restore_absent is only valid when the ledger proves there was no previous binding"
        )
    result: dict[str, Any] = {
        "profile_id": profile_id,
        "current_binding_id": current.id,
        "rollback_to_binding_id": previous.id if previous else None,
        "status": "restore_absent_ready"
        if previous is None and restore_absent
        else ("no_previous_binding" if previous is None else "ready"),
        "dry_run": dry_run,
        "writes_database": False
        if dry_run or (previous is None and not restore_absent)
        else True,
    }
    if dry_run or (previous is None and not restore_absent):
        return result

    now = datetime.now(UTC)
    current.binding_status = SUPERSEDED_BINDING_STATUS
    current.superseded_at = now
    session.flush()
    if previous is None:
        if commit:
            session.commit()
        result["status"] = "restored_absent"
        return result
    previous.binding_status = ACTIVE_BINDING_STATUS
    previous.superseded_at = None
    previous.activated_at = now
    session.flush()
    if commit:
        session.commit()
    result["status"] = "rolled_back"
    return result


__all__ = [
    "ProfileBindingValidationError",
    "rollback_profile_active_binding",
    "switch_profile_active_binding",
]
