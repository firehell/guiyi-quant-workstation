"""Dependency composition for read-only Historical Research CLI services."""

from __future__ import annotations


from sqlalchemy.orm import Session

from app.research.subing.candidate_validation_policy import (
    load_candidate_manifest,
    load_candidate_validation_protocol,
)
from app.market_data.composition import build_market_data_service
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


def build_subing_candidate_validation_service(
    session: Session,
) -> SubingCandidateValidationService:
    """Compose Candidate validation around the single Lifecycle research path."""
    return SubingCandidateValidationService(
        build_subing_lifecycle_research_service(session),
        manifest=load_candidate_manifest(),
        protocol=load_candidate_validation_protocol(),
    )
