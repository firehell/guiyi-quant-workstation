"""M1 metadata prerequisites are delegated to their scoped ingest operations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.data_operations.contracts import MetadataSyncRequest, MetadataSyncScope
from app.services.data_operations.metadata_sync import (
    MetadataSyncApplicationService,
    default_rqdata_ingest_service_map,
)


def test_calendar_session_and_main_map_use_distinct_scoped_ingestors() -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Catalog:
        def run_calendar(self, *args: object) -> object:
            calls.append(("calendar", args))
            return SimpleNamespace(rows=2, files=0)

        def run_sessions(self, *args: object, **kwargs: object) -> object:
            calls.append(("sessions", args + (kwargs.get("products"),)))
            return SimpleNamespace(rows=3, files=0)

    class Mapping:
        def run(self, *args: object) -> object:
            calls.append(("main-map", args))
            return SimpleNamespace(rows=4, files=1)

    service = MetadataSyncApplicationService(
        services=default_rqdata_ingest_service_map(
            catalog_ingestor_factory=Catalog,
            contract_ingestor_factory=lambda: object(),
            main_mapping_ingestor_factory=Mapping,
            start=None,
            end=None,
        )
    )
    request = MetadataSyncRequest(
        scope=MetadataSyncScope.CALENDAR,
        apply=True,
        symbols=("jm",),
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    assert service.run(request).effects.writes_provider_raw is False
    assert service.run(
        replace(request, scope=MetadataSyncScope.SESSIONS)
    ).effects.writes_postgresql is True
    assert service.run(
        replace(request, scope=MetadataSyncScope.MAIN_CONTRACT_MAP)
    ).effects.writes_provider_raw is True
    assert [item[0] for item in calls] == ["calendar", "sessions", "main-map"]
