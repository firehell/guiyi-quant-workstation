"""Dependency composition for read-only Historical Research CLI services."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentLoader,
)
from app.market_data.domain import CanonicalBar
from app.market_data.session_clock import (
    SessionClockError,
    resolved_session_windows_for_trading_day,
)
from app.models import Contract, Instrument
from app.research.subing.candidate_validation_policy import (
    load_candidate_manifest,
    load_candidate_validation_protocol,
)
from app.market_data.composition import (
    build_main_force_mirror_v2_service,
    build_market_data_service,
)
from app.research.jdj.jdj_candidate_validation_calendar import (
    assert_jdj_prospective_calendar,
)
from app.research.jdj.jdj_candidate_validation_policy import (
    load_jdj_candidate_manifest,
    load_jdj_candidate_validation_protocol,
)
from app.research.jdj.jdj_candidate_validation_service import (
    JdjCandidateValidationService,
)
from app.research.jdj.jdj_policy import JdjPolicyError, load_jdj_policy
from app.research.jdj.jdj_research_service import JdjResearchService
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyReplayService,
    JdjStrategySessionIdentityError,
)
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ResearchService,
)
from app.research.main_force.main_force_mirror_diagnostic_service import (
    MainForceMirrorDiagnosticService,
)
from app.research.robustness.multi_candidate_robustness_policy import (
    load_multi_candidate_robustness_protocol,
)
from app.research.robustness.multi_candidate_robustness_service import (
    MultiCandidateRobustnessService,
)
from app.research.robustness.jdj_robustness import (
    load_jdj_active60_robustness_protocol,
)
from app.research.robustness.jdj_robustness_service import (
    JdjActive60RobustnessService,
)
from app.research.n_structure.n_candidate_validation_policy import (
    load_n_candidate_manifest,
    load_n_candidate_validation_protocol,
)
from app.research.n_structure.n_candidate_validation_service import (
    NStructureCandidateValidationService,
)
from app.research.n_structure.n_structure_policy import (
    NStructurePolicyError,
    load_n_structure_policy,
)
from app.research.n_structure.n_structure_research_service import NStructureResearchService
from app.market_data.operational_universe import ActiveUniverseError, load_active_products
from app.market_data.subing_calibration import load_accepted_subing_calibration
from app.research.subing.subing_calibration_service import SubingCalibrationResearchService
from app.research.subing.subing_candidate_validation_service import (
    SubingCandidateValidationService,
)
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.research.subing.subing_lifecycle_research_service import (
    SubingLifecycleResearchService,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    load_five_candidate_dossier_protocol,
)
from app.research.candidate_convergence.five_candidate_dossier_service import (
    FiveCandidateResearchDossierService,
)
from app.research.candidate_convergence.artifact_source import (
    verify_json_artifact,
)
from app.research.candidate_convergence.five_candidate_relationships import (
    FiveCandidateRelationshipProtocolError,
    FiveCandidateRelationshipSourceError,
    load_five_candidate_relationship_protocol,
)
from app.research.candidate_convergence.five_candidate_relationships_service import (
    FiveCandidateRelationshipService,
)
from app.core.env import PROJECT_ROOT


def build_subing_calibration_research_service(
    session: Session,
) -> SubingCalibrationResearchService:
    """Construct historical-only SuBing Calibration over MarketDataService."""
    return SubingCalibrationResearchService(
        market_data=build_market_data_service(session),
        products=load_active_products(),
    )


def build_five_candidate_dossier_service() -> FiveCandidateResearchDossierService:
    """Compose the artifact-only five-candidate dossier without Runtime state."""
    return FiveCandidateResearchDossierService(
        load_five_candidate_dossier_protocol()
    )


def build_five_candidate_relationship_service(
    session: Session,
) -> FiveCandidateRelationshipService:
    """Compose exact Phase 8B source verification and one JDJ service."""
    protocol = load_five_candidate_relationship_protocol()
    try:
        active_products = load_active_products()
    except ActiveUniverseError:
        raise FiveCandidateRelationshipProtocolError() from None
    if active_products != protocol.cross_symbol_products:
        raise FiveCandidateRelationshipProtocolError()
    dossier_source = verify_json_artifact(
        protocol.dossier_source,
        PROJECT_ROOT,
        FiveCandidateRelationshipSourceError,
    )
    subing_n_source = verify_json_artifact(
        protocol.subing_n_source,
        PROJECT_ROOT,
        FiveCandidateRelationshipSourceError,
    )
    jdj_research = build_jdj_research_service(session)
    return FiveCandidateRelationshipService(
        protocol,
        jdj_research=jdj_research,
        dossier_source=dossier_source,
        subing_n_source=subing_n_source,
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
) -> NStructureResearchService:
    """Compose read-only N research over the shared segment loader."""
    return NStructureResearchService(
        ActualDominantResearchSegmentLoader(build_market_data_service(session)),
        products=load_active_products(),
        policy=load_n_structure_policy(),
    )


def build_jdj_research_service(session: Session) -> JdjResearchService:
    """Compose exact read-only JDJ research over one shared MDS."""
    market_data = build_market_data_service(session)
    return JdjResearchService(
        ActualDominantResearchSegmentLoader(market_data),
        products=load_active_products(),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
    )


def build_jdj_strategy_replay_service(
    session: Session,
) -> JdjStrategyReplayService:
    """Compose active-product replay with exact Catalog and Session facts."""

    def exchange_for_symbol(symbol: str) -> str:
        rows = tuple(
            session.scalars(
                select(Instrument.exchange_code).where(
                    Instrument.symbol == symbol,
                    Instrument.is_active.is_(True),
                )
            )
        )
        if len(rows) != 1 or not isinstance(rows[0], str) or not rows[0]:
            raise JdjStrategyContextInvalidError()
        return rows[0]

    def contract_multiplier_for_contract(
        *,
        symbol: str,
        contract: str,
    ) -> Decimal:
        exchange = exchange_for_symbol(symbol)
        rows = tuple(
            session.execute(
                select(
                    Contract.instrument_symbol,
                    Contract.exchange_code,
                    Contract.contract_multiplier,
                ).where(Contract.contract_code == contract)
            )
        )
        if len(rows) != 1:
            raise JdjStrategyContextInvalidError()
        owner, contract_exchange, multiplier = rows[0]
        if (
            owner != symbol
            or contract_exchange != exchange
            or isinstance(multiplier, bool)
            or not isinstance(multiplier, int)
            or multiplier <= 0
        ):
            raise JdjStrategyContextInvalidError()
        return Decimal(multiplier)

    def terminal_bar_ends_for_segment(
        *,
        symbol: str,
        bars_1m: Sequence[CanonicalBar],
    ) -> dict[date, datetime]:
        if not bars_1m:
            raise JdjStrategySessionIdentityError()
        exchange = exchange_for_symbol(symbol)
        terminals: dict[date, datetime] = {}
        for trading_day in sorted({bar.trading_day for bar in bars_1m}):
            try:
                windows = resolved_session_windows_for_trading_day(
                    session,
                    exchange=exchange,
                    symbol=symbol,
                    trading_day=trading_day,
                )
            except SessionClockError:
                raise JdjStrategySessionIdentityError() from None
            if not windows:
                raise JdjStrategySessionIdentityError()
            terminal = max(item.window.end for item in windows)
            bar_ends = {
                bar.bar_end
                for bar in bars_1m
                if bar.trading_day == trading_day
            }
            if (
                terminal.tzinfo is None
                or terminal.astimezone(UTC) not in bar_ends
            ):
                raise JdjStrategySessionIdentityError()
            terminals[trading_day] = terminal
        return terminals

    try:
        jdj_policy = load_jdj_policy()
        n_policy = load_n_structure_policy()
    except (JdjPolicyError, NStructurePolicyError):
        raise JdjStrategyContextInvalidError() from None
    market_data = build_market_data_service(session)
    return JdjStrategyReplayService(
        ActualDominantResearchSegmentLoader(market_data),
        products=load_active_products(),
        jdj_policy=jdj_policy,
        n_policy=n_policy,
        contract_multiplier_for_contract=contract_multiplier_for_contract,
        terminal_bar_ends_for_segment=terminal_bar_ends_for_segment,
    )


def build_jdj_candidate_validation_service(
    session: Session,
    candidate_id: str,
) -> JdjCandidateValidationService:
    """Compose exact JDJ validation only after the frozen calendar gate."""
    assert_jdj_prospective_calendar(session)
    return JdjCandidateValidationService(
        build_jdj_research_service(session),
        manifest=load_jdj_candidate_manifest(candidate_id),
        protocol=load_jdj_candidate_validation_protocol(),
    )


def build_jdj_active60_robustness_service(
    session: Session,
) -> JdjActive60RobustnessService:
    """Compose exact Phase 7 robustness over the existing JDJ research path."""
    return JdjActive60RobustnessService(
        load_jdj_active60_robustness_protocol(),
        jdj_research=build_jdj_research_service(session),
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


def build_main_force_mirror_v2_research_service(
    session: Session,
) -> MainForceMirrorV2ResearchService:
    """Compose retrospective V2 around the exact API service identities."""
    mirror_service = build_main_force_mirror_v2_service(session)
    return MainForceMirrorV2ResearchService(
        market_data=mirror_service.market_data,
        mirror_service=mirror_service,
    )


def build_main_force_mirror_diagnostic_service(
    session: Session,
) -> MainForceMirrorDiagnosticService:
    """Compose frozen Phase A over the existing V2/MDS historical readers."""
    mirror_service = build_main_force_mirror_v2_service(session)
    return MainForceMirrorDiagnosticService(
        market_data=mirror_service.market_data,
        mirror_service=mirror_service,
        previous_trading_day=mirror_service.coverage.previous_trading_day,
    )
