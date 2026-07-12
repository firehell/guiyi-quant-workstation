from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import ProfileActiveBinding
from app.services.data_profile_registry import ACTIVE_BINDING_STATUS, DataProfileRegistry, SUPERSEDED_BINDING_STATUS
from app.services.profile_binding_validator import ProfileBindingValidationError, validate_profile_binding_target


def _resolve_current_active_binding(
    session: Session,
    *,
    profile_id: str,
    binding_id: int | None,
    instrument_symbol: str | None,
    contract_code: str | None,
    period: str | None,
) -> ProfileActiveBinding:
    if binding_id is not None:
        current = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == profile_id,
                ProfileActiveBinding.id == binding_id,
                ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
            )
        )
        if current is None:
            raise ValueError(f"active binding not found: profile={profile_id} binding_id={binding_id}")
        return current

    if instrument_symbol is None or contract_code is None or period is None:
        raise ValueError("binding_id or instrument_symbol/contract_code/period is required for rollback")

    current = session.scalar(
        select(ProfileActiveBinding).where(
            ProfileActiveBinding.profile_id == profile_id,
            ProfileActiveBinding.instrument_symbol == instrument_symbol,
            ProfileActiveBinding.contract_code == contract_code,
            ProfileActiveBinding.period == period,
            ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
        )
    )
    if current is None:
        raise ValueError(
            f"active binding not found: profile={profile_id} "
            f"symbol={instrument_symbol} contract={contract_code} period={period}"
        )
    return current


def _find_previous_binding(session: Session, *, profile_id: str, current: ProfileActiveBinding) -> ProfileActiveBinding | None:
    return session.scalar(
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
) -> dict[str, Any]:
    registry = DataProfileRegistry(session, project_root=project_root)
    current_bindings = registry.list_active_bindings(profile_id)
    current = next(
        (
            item
            for item in current_bindings
            if item.instrument_symbol == instrument_symbol and item.contract_code == contract_code and item.period == period
        ),
        None,
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
        "next_data_version": data_version,
        "previous_market_data_file_id": current.market_data_file_id if current else None,
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
) -> dict[str, Any]:
    current = _resolve_current_active_binding(
        session,
        profile_id=profile_id,
        binding_id=binding_id,
        instrument_symbol=instrument_symbol,
        contract_code=contract_code,
        period=period,
    )
    previous = _find_previous_binding(session, profile_id=profile_id, current=current)
    result: dict[str, Any] = {
        "profile_id": profile_id,
        "current_binding_id": current.id,
        "rollback_to_binding_id": previous.id if previous else None,
        "status": "no_previous_binding" if previous is None else "ready",
        "dry_run": dry_run,
        "writes_database": False if dry_run or previous is None else True,
    }
    if dry_run or previous is None:
        return result

    now = datetime.now(UTC)
    current.binding_status = SUPERSEDED_BINDING_STATUS
    current.superseded_at = now
    session.flush()
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
