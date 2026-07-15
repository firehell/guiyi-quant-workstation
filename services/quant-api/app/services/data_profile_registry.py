from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding

ACTIVE_BINDING_STATUS = "active"
SUPERSEDED_BINDING_STATUS = "superseded"
PROFILE_CONFIG_DIR = PROJECT_ROOT / "configs" / "data_profiles"


class DataProfileRegistry:
    def __init__(self, session: Session, project_root: Path = PROJECT_ROOT) -> None:
        self.session = session
        self.project_root = project_root

    def list_profiles(self) -> list[DataProfile]:
        return list(self.session.scalars(select(DataProfile).where(DataProfile.is_active.is_(True)).order_by(DataProfile.profile_id)))

    def get_profile(self, profile_id: str) -> DataProfile | None:
        return self.session.scalar(select(DataProfile).where(DataProfile.profile_id == profile_id, DataProfile.is_active.is_(True)))

    def list_active_bindings(self, profile_id: str) -> list[ProfileActiveBinding]:
        return list(
            self.session.scalars(
                select(ProfileActiveBinding)
                .where(ProfileActiveBinding.profile_id == profile_id, ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS)
                .order_by(ProfileActiveBinding.instrument_symbol, ProfileActiveBinding.contract_code, ProfileActiveBinding.period)
            )
        )

    def resolve_active_market_file(
        self,
        *,
        profile_id: str,
        instrument_symbol: str,
        contract_code: str,
        period: str,
    ) -> MarketDataFile | None:
        binding = self.session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == profile_id,
                ProfileActiveBinding.instrument_symbol == instrument_symbol,
                ProfileActiveBinding.contract_code == contract_code,
                ProfileActiveBinding.period == period,
                ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
            )
        )
        if binding is None:
            return None
        if binding.market_data_file_id is not None:
            market_file = self.session.get(MarketDataFile, binding.market_data_file_id)
            if market_file is not None:
                return market_file
        return self.session.scalar(
            select(MarketDataFile).where(
                MarketDataFile.instrument_symbol == instrument_symbol,
                MarketDataFile.contract_code == contract_code,
                MarketDataFile.period == period,
                MarketDataFile.data_version == binding.data_version,
                MarketDataFile.data_role == "primary",
            )
        )

    def active_bindings_by_file_id(self) -> dict[int, list[ProfileActiveBinding]]:
        bindings = list(
            self.session.scalars(
                select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS, ProfileActiveBinding.market_data_file_id.is_not(None))
            )
        )
        grouped: dict[int, list[ProfileActiveBinding]] = {}
        for binding in bindings:
            if binding.market_data_file_id is None:
                continue
            grouped.setdefault(binding.market_data_file_id, []).append(binding)
        return grouped

    def load_profile_config(self, profile_id: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        if profile is None or not profile.config_path:
            return {}
        path = Path(profile.config_path)
        if not path.is_absolute():
            path = self.project_root / path
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def switch_active_binding(
        self,
        *,
        profile_id: str,
        instrument_symbol: str,
        contract_code: str,
        period: str,
        data_version: str,
        market_data_file_id: int | None,
        contract_role: str = "dominant_main",
    ) -> ProfileActiveBinding:
        now = datetime.now(UTC)
        current = self.session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == profile_id,
                ProfileActiveBinding.instrument_symbol == instrument_symbol,
                ProfileActiveBinding.contract_code == contract_code,
                ProfileActiveBinding.period == period,
                ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
            )
        )
        if current is not None:
            current.binding_status = SUPERSEDED_BINDING_STATUS
            current.superseded_at = now
        binding = ProfileActiveBinding(
            profile_id=profile_id,
            instrument_symbol=instrument_symbol,
            contract_code=contract_code,
            contract_role=contract_role,
            period=period,
            data_version=data_version,
            market_data_file_id=market_data_file_id,
            binding_status=ACTIVE_BINDING_STATUS,
            activated_at=now,
        )
        self.session.add(binding)
        self.session.flush()
        return binding
