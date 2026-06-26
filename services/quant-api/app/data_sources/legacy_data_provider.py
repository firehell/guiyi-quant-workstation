from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.data_sources.errors import DataSourceAccessError
from app.data_sources.local_parquet_provider import ReaderBackedMarketDataProvider
from app.data_sources.roles import LEGACY_REFERENCE_PROVIDERS, VALIDATION_PROVIDERS, DataRole
from app.db.session import PROJECT_ROOT
from app.services.market_data_reader import MarketDataReader


class LegacyDataProvider(ReaderBackedMarketDataProvider):
    """Explicit-only access to validation or legacy reference data."""

    def __init__(
        self,
        session: Session,
        *,
        data_role: DataRole,
        explicit: bool = False,
        reader: MarketDataReader | None = None,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        if data_role not in {DataRole.VALIDATION, DataRole.LEGACY_REFERENCE}:
            raise DataSourceAccessError("LegacyDataProvider only supports validation or legacy_reference roles")
        if not explicit:
            raise DataSourceAccessError(f"{data_role.value} data must be explicitly selected")
        self.data_role = data_role
        self.provider_names = self._providers_for_role(data_role)
        super().__init__(session=session, reader=reader, project_root=project_root)

    @classmethod
    def validation(cls, session: Session, *, explicit: bool, reader: MarketDataReader | None = None) -> LegacyDataProvider:
        return cls(session=session, data_role=DataRole.VALIDATION, explicit=explicit, reader=reader)

    @classmethod
    def legacy_reference(cls, session: Session, *, explicit: bool, reader: MarketDataReader | None = None) -> LegacyDataProvider:
        return cls(session=session, data_role=DataRole.LEGACY_REFERENCE, explicit=explicit, reader=reader)

    @staticmethod
    def _providers_for_role(data_role: DataRole) -> frozenset[str]:
        if data_role is DataRole.VALIDATION:
            return VALIDATION_PROVIDERS
        if data_role is DataRole.LEGACY_REFERENCE:
            return LEGACY_REFERENCE_PROVIDERS
        raise DataSourceAccessError(f"Unsupported legacy role: {data_role.value}")
