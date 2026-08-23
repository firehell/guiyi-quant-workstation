"""Build immutable requests for ``guiyi research`` commands."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TypeAlias

from app.market_data.domain import BarFrequency, SeriesKind
from app.research.common.candidate_validation_schedule import (
    CandidateValidationRequest,
)
from app.research.jdj.jdj_research import JdjResearchRequest
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ResearchRequest,
)
from app.research.main_force.main_force_mirror_diagnostic_policy import (
    MainForceMirrorDiagnosticRequest,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
)
from app.research.robustness.multi_candidate_robustness_policy import (
    MultiCandidateRobustnessRequest,
)
from app.research.robustness.jdj_robustness import (
    JdjActive60RobustnessRequest,
)
from app.research.subing.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    CalibrationResearchRequest,
    SlopeThresholds,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    FiveCandidateDossierRequest,
)
from app.research.candidate_convergence.five_candidate_relationships import (
    FiveCandidateRelationshipRequest,
)


ResearchRequest: TypeAlias = (
    CalibrationResearchRequest
    | LifecycleResearchRequest
    | JdjResearchRequest
    | CandidateValidationRequest
    | MainForceMirrorV2ResearchRequest
    | MainForceMirrorDiagnosticRequest
    | NStructureResearchRequest
    | MultiCandidateRobustnessRequest
    | JdjActive60RobustnessRequest
    | FiveCandidateDossierRequest
    | FiveCandidateRelationshipRequest
)


def build_research_request(args: argparse.Namespace) -> ResearchRequest:
    """Convert CLI strings into one immutable research request."""
    if args.research_command == "candidate-dossier":
        return FiveCandidateDossierRequest(protocol_id=args.protocol)
    if args.research_command == "candidate-relationships":
        return FiveCandidateRelationshipRequest(protocol_id=args.protocol)
    if args.research_command == "candidate-robustness":
        if args.protocol == "jdj_active60_robustness_v1":
            return JdjActive60RobustnessRequest(protocol_id=args.protocol)
        return MultiCandidateRobustnessRequest(protocol_id=args.protocol)
    if args.research_command == "main-force-mirror-v2":
        return MainForceMirrorV2ResearchRequest(
            symbol=args.symbol,
            series_kind=SeriesKind(args.series_kind),
            contract=args.contract,
            frequency=BarFrequency(args.frequency),
            since=_day(args.since),
            through=_day(args.through),
            forensic=args.forensic,
        )
    if args.research_command == "main-force-mirror-diagnostic":
        return MainForceMirrorDiagnosticRequest(protocol_id=args.protocol)
    if args.research_command == "candidate-validation":
        return CandidateValidationRequest(
            candidate_id=args.candidate,
            protocol_id=args.protocol,
            symbol=args.symbol,
            through=_day(args.through),
        )
    if args.research_command == "jdj-1m":
        return JdjResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbol=args.symbol,
            candidate_id=args.candidate,
        )
    if args.research_command == "subing-lifecycle":
        return LifecycleResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbol=args.symbol,
        )
    if args.research_command == "n-structure":
        return NStructureResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbol=args.symbol,
        )
    if args.research_command != "subing-calibration":
        raise ValueError("CLI_RESEARCH_COMMAND_INVALID")
    slope_5m = _decimal(args.slope_threshold_5m_bps)
    slope_15m = _decimal(args.slope_threshold_15m_bps)
    slope_thresholds: SlopeThresholds | None = None
    if slope_5m is not None or slope_15m is not None:
        if slope_5m is None or slope_15m is None:
            raise ValueError("CLI_SLOPE_THRESHOLD_PAIR_REQUIRED")
        slope_thresholds = SlopeThresholds(slope_5m, slope_15m)
    return CalibrationResearchRequest(
        phase=CalibrationPhase(args.phase),
        mode=CalibrationMode(args.mode),
        frequency=BarFrequency(args.frequency),
        since=_day(args.since),
        through=_day(args.through),
        symbol=args.symbol,
        slope_threshold_bps=_decimal(args.slope_threshold_bps),
        slope_thresholds=slope_thresholds,
        zero_band_bps=_decimal(args.zero_band_bps),
    )


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("CLI_DATE_INVALID") from exc


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("CLI_THRESHOLD_INVALID") from exc
