"""Dependency composition for read-only Historical Research CLI services."""

from __future__ import annotations


from sqlalchemy.orm import Session

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentLoader,
)
from app.research.subing.candidate_validation_policy import (
    load_candidate_manifest,
    load_candidate_validation_protocol,
)
from app.market_data.composition import build_market_data_service
from app.research.robustness.multi_candidate_robustness_policy import (
    load_multi_candidate_robustness_protocol,
)
from app.research.robustness.multi_candidate_robustness_service import (
    MultiCandidateRobustnessService,
)
from app.research.n_structure.n_candidate_validation_policy import (
    load_n_candidate_manifest,
    load_n_candidate_validation_protocol,
)
from app.research.n_structure.n_candidate_validation_service import (
    NStructureCandidateValidationService,
)
from app.research.n_structure.n_structure_policy import (
    NStructurePolicy,
    load_n_structure_policy,
)
from app.research.n_structure.n_structure_research_service import NStructureResearchService
from app.market_data.operational_universe import load_active_products
from app.market_data.subing_calibration import load_accepted_subing_calibration
from app.research.subing.subing_calibration_service import SubingCalibrationResearchService
from app.research.subing.subing_candidate_validation_service import (
    SubingCandidateValidationService,
)
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.research.subing.subing_lifecycle_research_service import (
    SubingLifecycleResearchService,
)


def build_subing_calibration_research_service(
    session: Session,
) -> SubingCalibrationResearchService:
    """Construct historical-only SuBing Calibration over MarketDataService."""
    return SubingCalibrationResearchService(
        market_data=build_market_data_service(session),
        products=load_active_products(),
    )


def build_subing_lifecycle_research_service(
    session: Session,
) -> SubingLifecycleResearchService:
    """Construct historical-only lifecycle research over MarketDataService."""
    return SubingLifecycleResearchService(
        build_market_data_service(session),
        products=load_active_products(),
        calibration=load_accepted_subing_calibration(),
        policy=load_subing_lifecycle_policy(),
    )


def build_n_structure_research_service(
    session: Session,
    *,
    policy: NStructurePolicy | None = None,
) -> NStructureResearchService:
    """Compose read-only N research over the shared segment loader."""
    return NStructureResearchService(
        ActualDominantResearchSegmentLoader(build_market_data_service(session)),
        products=load_active_products(),
        policy=policy if policy is not None else load_n_structure_policy(),
    )


def build_subing_candidate_validation_service(
    session: Session,
) -> SubingCandidateValidationService:
    """Compose Candidate validation around the single Lifecycle research path."""
    return SubingCandidateValidationService(
        build_subing_lifecycle_research_service(session),
        manifest=load_candidate_manifest(),
        protocol=load_candidate_validation_protocol(),
    )


def build_n_candidate_validation_service(
    session: Session,
) -> NStructureCandidateValidationService:
    """Compose N Candidate validation over the MDS-only N research path."""
    return NStructureCandidateValidationService(
        build_n_structure_research_service(session),
        manifest=load_n_candidate_manifest(),
        protocol=load_n_candidate_validation_protocol(),
    )


def build_multi_candidate_robustness_service(
    session: Session,
) -> MultiCandidateRobustnessService:
    """Compose the exact read-only robustness dossier over one shared MDS."""
    protocol = load_multi_candidate_robustness_protocol()
    active_products = load_active_products()
    if active_products != protocol.cross_symbol_products:
        from app.research.robustness.multi_candidate_robustness_service import (
            MultiCandidateActiveUniverseDriftError,
        )

        raise MultiCandidateActiveUniverseDriftError()
    market_data = build_market_data_service(session)
    subing = SubingLifecycleResearchService(
        market_data,
        products=protocol.cross_symbol_products,
        calibration=load_accepted_subing_calibration(),
        policy=load_subing_lifecycle_policy(),
    )
    n_structure = NStructureResearchService(
        ActualDominantResearchSegmentLoader(market_data),
        products=protocol.cross_symbol_products,
        policy=load_n_structure_policy(),
    )
    return MultiCandidateRobustnessService(
        protocol,
        subing_research=subing,
        n_research=n_structure,
        subing_validation=SubingCandidateValidationService(
            subing,
            manifest=load_candidate_manifest(),
            protocol=load_candidate_validation_protocol(),
        ),
        n_validation=NStructureCandidateValidationService(
            n_structure,
            manifest=load_n_candidate_manifest(),
            protocol=load_n_candidate_validation_protocol(),
        ),
        current_active_products=active_products,
    )
