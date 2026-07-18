from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataProfile, MarketDataFile
from app.services.profile_target_resolver import ProfileTargetRange

ACTIVE_DATA_ROLE = "primary"
PASSED_ONLY_POLICY = "passed_only"
ACTIVE_ENTRY_POLICY = "active_entry"


class ProfileBindingValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _quality_allows_binding(*, quality_policy: str, quality_status: str) -> bool:
    if quality_policy == PASSED_ONLY_POLICY:
        return quality_status == "passed"
    if quality_policy == ACTIVE_ENTRY_POLICY:
        return quality_status != "failed"
    return quality_status != "failed"


def validate_profile_binding_target(
    session: Session,
    *,
    profile_id: str,
    instrument_symbol: str,
    contract_code: str,
    period: str,
    contract_role: str,
    data_version: str,
    market_data_file_id: int | None,
    project_root: Path = PROJECT_ROOT,
    target_ranges: tuple[ProfileTargetRange, ...] = (),
    require_target_coverage: bool = False,
    require_checksum: bool = False,
) -> MarketDataFile:
    if market_data_file_id is None:
        raise ProfileBindingValidationError(
            "market_data_file_required",
            "market_data_file_id is required for profile binding switch",
            {"profile_id": profile_id, "instrument_symbol": instrument_symbol, "period": period},
        )

    profile = session.scalar(
        select(DataProfile).where(DataProfile.profile_id == profile_id, DataProfile.is_active.is_(True))
    )
    if profile is None:
        raise ProfileBindingValidationError(
            "profile_not_found",
            f"active profile not found: {profile_id}",
            {"profile_id": profile_id},
        )

    allowed_periods = list(profile.periods or [])
    if period not in allowed_periods:
        raise ProfileBindingValidationError(
            "period_not_allowed",
            f"period not allowed for profile: {period}",
            {"profile_id": profile_id, "period": period, "allowed_periods": allowed_periods},
        )

    allowed_roles = list(profile.contract_roles or [])
    if contract_role not in allowed_roles:
        raise ProfileBindingValidationError(
            "contract_role_not_allowed",
            f"contract_role not allowed for profile: {contract_role}",
            {"profile_id": profile_id, "contract_role": contract_role, "allowed_roles": allowed_roles},
        )

    market_file = session.get(MarketDataFile, market_data_file_id)
    if market_file is None:
        raise ProfileBindingValidationError(
            "market_data_file_not_found",
            f"market_data_file not found: {market_data_file_id}",
            {"market_data_file_id": market_data_file_id},
        )

    identity_fields = {
        "instrument_symbol": (market_file.instrument_symbol, instrument_symbol),
        "contract_code": (market_file.contract_code, contract_code),
        "period": (market_file.period, period),
        "data_version": (market_file.data_version, data_version),
    }
    mismatches = {
        field: {"expected": expected, "actual": actual}
        for field, (actual, expected) in identity_fields.items()
        if actual != expected
    }
    if mismatches:
        raise ProfileBindingValidationError(
            "file_identity_mismatch",
            "market_data_file identity does not match switch target",
            {"market_data_file_id": market_data_file_id, "mismatches": mismatches},
        )

    if market_file.provider != profile.provider:
        raise ProfileBindingValidationError(
            "provider_mismatch",
            "market_data_file provider does not match profile provider",
            {
                "market_data_file_id": market_data_file_id,
                "file_provider": market_file.provider,
                "profile_provider": profile.provider,
            },
        )

    if market_file.data_role != ACTIVE_DATA_ROLE:
        raise ProfileBindingValidationError(
            "data_role_not_primary",
            "market_data_file data_role must be primary",
            {"market_data_file_id": market_data_file_id, "data_role": market_file.data_role},
        )

    if not _quality_allows_binding(quality_policy=profile.quality_policy, quality_status=market_file.quality_status):
        raise ProfileBindingValidationError(
            "quality_policy_violation",
            "market_data_file quality_status violates profile quality_policy",
            {
                "market_data_file_id": market_data_file_id,
                "quality_policy": profile.quality_policy,
                "quality_status": market_file.quality_status,
            },
        )

    file_path = Path(market_file.file_path)
    resolved_path = file_path if file_path.is_absolute() else project_root / file_path
    if not resolved_path.is_file():
        raise ProfileBindingValidationError(
            "file_missing",
            "market_data_file physical path does not exist",
            {"market_data_file_id": market_data_file_id, "resolved_path": str(resolved_path)},
        )

    if require_checksum:
        declared_checksum = (market_file.checksum or "").strip().lower()
        if not declared_checksum:
            raise ProfileBindingValidationError(
                "checksum_missing",
                "market_data_file checksum is required",
                {"market_data_file_id": market_data_file_id},
            )
        digest = hashlib.sha256()
        with resolved_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_checksum = digest.hexdigest()
        if actual_checksum != declared_checksum:
            raise ProfileBindingValidationError(
                "checksum_mismatch",
                "physical checksum does not match market_data_file metadata",
                {"market_data_file_id": market_data_file_id, "actual_checksum": actual_checksum},
            )

    if require_target_coverage:
        if not target_ranges:
            raise ProfileBindingValidationError(
                "missing_target_boundary",
                "target ranges are required for target-aware profile binding",
                {"market_data_file_id": market_data_file_id},
            )
        if market_file.start_time is None or market_file.end_time is None:
            raise ProfileBindingValidationError(
                "target_coverage_unresolved",
                "market_data_file coverage boundaries are required",
                {"market_data_file_id": market_data_file_id},
            )
        coverage_start = market_file.start_time.date()
        coverage_end = market_file.end_time.date()
        uncovered = [
            {"start": item.start.isoformat(), "end": item.end.isoformat()}
            for item in target_ranges
            if coverage_start > item.start or coverage_end < item.end
        ]
        if uncovered:
            raise ProfileBindingValidationError(
                "target_coverage_incomplete",
                "market_data_file does not cover every profile target range",
                {
                    "market_data_file_id": market_data_file_id,
                    "coverage_start": coverage_start.isoformat(),
                    "coverage_end": coverage_end.isoformat(),
                    "uncovered_ranges": uncovered,
                },
            )

    return market_file
