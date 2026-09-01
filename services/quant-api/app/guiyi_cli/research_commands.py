"""Typed service dispatch for read-only ``guiyi research`` commands."""

from __future__ import annotations

from typing import Protocol, cast

from app.guiyi_cli.research_payloads import (
    _calibration_payload,
    _lifecycle_payload,
    _subing_watch_payload,
)
from app.guiyi_cli.research_requests import ResearchRequest
from app.research.subing.subing_calibration_service import (
    CalibrationResearchRequest,
    CalibrationResearchResult,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)
from app.research.subing.subing_watch_research_service import (
    SubingWatchResearchRequest,
    SubingWatchResearchResult,
)


class _CalibrationResearchService(Protocol):
    def run(self, request: CalibrationResearchRequest) -> CalibrationResearchResult: ...


class _LifecycleResearchService(Protocol):
    def run(
        self, request: LifecycleResearchRequest
    ) -> SubingLifecycleResearchResult: ...


class _SubingWatchResearchService(Protocol):
    def run(self, request: SubingWatchResearchRequest) -> SubingWatchResearchResult: ...


def run_research_command(
    request: ResearchRequest,
    service: object,
) -> dict[str, object]:
    """Run one Historical-only research command and render its JSON schema."""
    if isinstance(request, LifecycleResearchRequest):
        lifecycle_service = cast(_LifecycleResearchService, service)
        return _lifecycle_payload(request, lifecycle_service.run(request))
    if isinstance(request, SubingWatchResearchRequest):
        watch_service = cast(_SubingWatchResearchService, service)
        return _subing_watch_payload(request, watch_service.run(request))
    calibration_service = cast(_CalibrationResearchService, service)
    return _calibration_payload(request, calibration_service.run(request))
