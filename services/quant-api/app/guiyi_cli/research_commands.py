"""Typed service dispatch for read-only ``guiyi research`` commands."""

from __future__ import annotations

from typing import Protocol, cast

from app.guiyi_cli.research_payloads import (
    _calibration_payload,
    _candidate_payload,
    _jdj_candidate_payload,
    _jdj_research_payload,
    _lifecycle_payload,
    _main_force_mirror_v2_payload,
    _multi_candidate_robustness_payload,
    _n_candidate_payload,
    _n_structure_payload,
)
from app.guiyi_cli.research_requests import ResearchRequest
from app.research.common.candidate_validation_schedule import (
    CandidateValidationRequest,
)
from app.research.jdj.jdj_candidate_validation import (
    JdjCandidateValidationReport,
)
from app.research.jdj.jdj_research import JdjResearchRequest, JdjResearchResult
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ResearchRequest,
    MainForceMirrorV2ResearchResult,
)
from app.research.n_structure.n_candidate_validation import (
    NStructureCandidateValidationReport,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureResearchResult,
)
from app.research.robustness.multi_candidate_robustness import (
    MultiCandidateRobustnessReport,
)
from app.research.robustness.multi_candidate_robustness_policy import (
    MultiCandidateRobustnessRequest,
)
from app.research.subing.candidate_validation import CandidateValidationReport
from app.research.subing.subing_calibration_service import (
    CalibrationResearchRequest,
    CalibrationResearchResult,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)


class _CalibrationResearchService(Protocol):
    def run(self, request: CalibrationResearchRequest) -> CalibrationResearchResult: ...


class _LifecycleResearchService(Protocol):
    def run(
        self, request: LifecycleResearchRequest
    ) -> SubingLifecycleResearchResult: ...


class _NStructureResearchService(Protocol):
    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult: ...


class _JdjResearchService(Protocol):
    def run(self, request: JdjResearchRequest) -> JdjResearchResult: ...


class _CandidateValidationService(Protocol):
    def run(
        self,
        request: CandidateValidationRequest,
    ) -> (
        CandidateValidationReport
        | NStructureCandidateValidationReport
        | JdjCandidateValidationReport
    ): ...


class _MainForceMirrorV2ResearchService(Protocol):
    def run(
        self,
        request: MainForceMirrorV2ResearchRequest,
    ) -> MainForceMirrorV2ResearchResult: ...


class _MultiCandidateRobustnessService(Protocol):
    def run(
        self, request: MultiCandidateRobustnessRequest
    ) -> MultiCandidateRobustnessReport: ...


def run_research_command(
    request: ResearchRequest,
    service: object,
) -> dict[str, object]:
    """Run one Historical-only research command and render its JSON schema."""
    if isinstance(request, MultiCandidateRobustnessRequest):
        robustness_service = cast(_MultiCandidateRobustnessService, service)
        return _multi_candidate_robustness_payload(robustness_service.run(request))
    if isinstance(request, MainForceMirrorV2ResearchRequest):
        mirror_service = cast(_MainForceMirrorV2ResearchService, service)
        return _main_force_mirror_v2_payload(request, mirror_service.run(request))
    if isinstance(request, JdjResearchRequest):
        jdj_service = cast(_JdjResearchService, service)
        return _jdj_research_payload(request, jdj_service.run(request))
    if isinstance(request, CandidateValidationRequest):
        candidate_service = cast(_CandidateValidationService, service)
        report = candidate_service.run(request)
        if isinstance(report, JdjCandidateValidationReport):
            return _jdj_candidate_payload(report)
        if isinstance(report, NStructureCandidateValidationReport):
            return _n_candidate_payload(report)
        return _candidate_payload(report)
    if isinstance(request, LifecycleResearchRequest):
        lifecycle_service = cast(_LifecycleResearchService, service)
        return _lifecycle_payload(request, lifecycle_service.run(request))
    if isinstance(request, NStructureResearchRequest):
        n_service = cast(_NStructureResearchService, service)
        return _n_structure_payload(request, n_service.run(request))
    calibration_service = cast(_CalibrationResearchService, service)
    return _calibration_payload(request, calibration_service.run(request))
