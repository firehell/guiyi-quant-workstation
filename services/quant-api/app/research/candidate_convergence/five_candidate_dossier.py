from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.core.env import PROJECT_ROOT
from app.market_data.exact_json_contract import load_exact_json
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
    SourceArtifactRef,
)


_PROTOCOL_PATH = (
    PROJECT_ROOT / "data/research_protocols/five_candidate_research_dossier_v1.json"
)
_CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)
_SOURCE_ARTIFACTS = (
    (
        "subing_lifecycle_v2_candidate_v1",
        "reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-19.json",
        "1a1b3064dcb9084adc7347e024c001a2fe7c4bb7ba909c6c80f31659ecc3b3d1",
    ),
    (
        "n_structure_5m_candidate_v1",
        "reports/research/candidate_validation/n_structure_5m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-20.json",
        "12fed018751ae54d5bfd2d24897cc077c513560ac1377935e5fddd14a36a3fc6",
    ),
    (
        "jdj_trend_follow_1m_candidate_v1",
        "reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-21.json",
        "63a9f3021ae30eab777d838c39493f1ef195c07edc49f5471cbbb2de98621fef",
    ),
    (
        "jdj_trend_reentry_6_1m_candidate_v1",
        "reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-21.json",
        "63f9dfdd29eabfa2c7b44fbe24aa31198dddffae60fab856e9d1b2684cb35bea",
    ),
    (
        "jdj_key_level_breakout_1m_candidate_v1",
        "reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-21.json",
        "6e06b894bb05a0de2c857be0143cdd44d0b7479b33ad712a0db88197bbdcab10",
    ),
    (
        "multi_candidate_robustness_v1",
        "reports/research/candidate_robustness/multi_candidate_robustness_v1/"
        "anchor-jm-active60-retrospective-freeze-2026-08-20.json",
        "6aaa624d13eb3492232eeff44b919efb704bd2018ab9e35503678ffc2c17f433",
    ),
    (
        "jdj_active60_robustness_v1",
        "reports/research/candidate_robustness/jdj_active60_robustness_v1/"
        "active60-retrospective-freeze-2026-08-21.json",
        "f6078a5bc9d3071cb6f0366982dc709cf95087b5ec8b1872b72d1fd4b7790d87",
    ),
)
_PAIR_ORDER = (
    (_CANDIDATES[0], _CANDIDATES[1]),
    (_CANDIDATES[0], _CANDIDATES[2]),
    (_CANDIDATES[0], _CANDIDATES[3]),
    (_CANDIDATES[0], _CANDIDATES[4]),
    (_CANDIDATES[1], _CANDIDATES[2]),
    (_CANDIDATES[1], _CANDIDATES[3]),
    (_CANDIDATES[1], _CANDIDATES[4]),
    (_CANDIDATES[2], _CANDIDATES[3]),
    (_CANDIDATES[2], _CANDIDATES[4]),
    (_CANDIDATES[3], _CANDIDATES[4]),
)
SOURCE_SEMANTICS = {
    "subing_lifecycle_v2_candidate_v1": (
        "subing_lifecycle",
        ("5m", "15m"),
        "5m_ready_boundary",
        "same_trading_day_only",
        (3, 5, 8),
    ),
    "n_structure_5m_candidate_v1": (
        "n_structure",
        ("5m",),
        "5m_canonical_bar",
        "same_rank1_segment",
        (3, 5, 8),
    ),
    "jdj_trend_follow_1m_candidate_v1": (
        "jdj_1m",
        ("1m", "5m_strict_before_context"),
        "1m_canonical_bar",
        "same_trading_day_physical_contract_rank1_segment",
        (3, 5, 8, 20),
    ),
    "jdj_trend_reentry_6_1m_candidate_v1": (
        "jdj_1m",
        ("1m", "5m_strict_before_context"),
        "1m_canonical_bar",
        "same_trading_day_physical_contract_rank1_segment",
        (3, 5, 8, 20),
    ),
    "jdj_key_level_breakout_1m_candidate_v1": (
        "jdj_1m",
        ("1m", "5m_strict_before_context"),
        "1m_canonical_bar",
        "same_trading_day_physical_contract_rank1_segment",
        (3, 5, 8, 20),
    ),
}
_SOURCE_EVENT_KINDS = {
    _CANDIDATES[0]: "entry_confirmed",
    _CANDIDATES[1]: "n_completed",
    _CANDIDATES[2]: "jdj_trend_follow_triggered",
    _CANDIDATES[3]: "jdj_trend_reentry_6_triggered",
    _CANDIDATES[4]: "jdj_key_level_breakout_triggered",
}
_RETROSPECTIVE_WINDOWS = {
    _CANDIDATES[0]: (date(2023, 1, 1), date(2026, 8, 18)),
    _CANDIDATES[1]: (date(2023, 1, 1), date(2026, 8, 19)),
    _CANDIDATES[2]: (date(2023, 1, 1), date(2026, 8, 20)),
    _CANDIDATES[3]: (date(2023, 1, 1), date(2026, 8, 20)),
    _CANDIDATES[4]: (date(2023, 1, 1), date(2026, 8, 20)),
}
_EXPECTED: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": "five_candidate_research_dossier_v1",
    "frozen_at": "2026-08-22T11:43:34+08:00",
    "research_only": True,
    "readonly": True,
    "candidate_order": list(_CANDIDATES),
    "source_artifacts": [
        {
            "artifact_id": artifact_id,
            "path": path,
            "expected_sha256": expected_sha256,
        }
        for artifact_id, path, expected_sha256 in _SOURCE_ARTIFACTS
    ],
    "comparability_pair_order": [list(pair) for pair in _PAIR_ORDER],
    "prospective_consumed": False,
    "new_metric_calculation": False,
    "new_relationship_calculation": False,
    "parameter_perturbation": False,
    "automatic_scoring": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


class FiveCandidateDossierProtocolError(ValueError):
    code = "FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class FiveCandidateDossierReportError(ValueError):
    code = "FIVE_CANDIDATE_DOSSIER_REPORT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CandidateHorizonEvidence:
    sample_count: int
    numeric_metrics: Mapping[str, str | None]

    def __post_init__(self) -> None:
        metrics = dict(self.numeric_metrics)
        if (
            not _nonnegative_int(self.sample_count)
            or not metrics
            or any(type(key) is not str or not key for key in metrics)
            or any(value is not None and type(value) is not str for value in metrics.values())
            or (self.sample_count == 0 and any(value is not None for value in metrics.values()))
            or (self.sample_count > 0 and any(value is None for value in metrics.values()))
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "numeric_metrics", MappingProxyType(metrics))


@dataclass(frozen=True, slots=True)
class CandidateCrossSymbolEvidence:
    candidate_id: str
    symbol: str
    status: str
    reason_code: str | None
    evaluable_count: int | None
    event_count: int | None
    event_rate_per_1000_evaluable: str | None
    horizon_summary: Mapping[int, CandidateHorizonEvidence] | None
    sector: str | None
    yearly: object | None

    def __post_init__(self) -> None:
        if (
            self.candidate_id not in _CANDIDATES
            or not _symbol(self.symbol)
            or self.status not in {"available", "unavailable"}
            or (self.sector is not None and (type(self.sector) is not str or not self.sector))
        ):
            raise FiveCandidateDossierReportError()
        if self.status == "unavailable":
            expected_reason = (
                "MULTI_CANDIDATE_SOURCE_UNAVAILABLE"
                if self.candidate_id in _CANDIDATES[:2]
                else "JDJ_SOURCE_UNAVAILABLE"
            )
            if (
                self.reason_code != expected_reason
                or self.evaluable_count is not None
                or self.event_count is not None
                or self.event_rate_per_1000_evaluable is not None
                or self.horizon_summary is not None
                or self.yearly is not None
            ):
                raise FiveCandidateDossierReportError()
            return
        if (
            self.reason_code is not None
            or not _nonnegative_int(self.evaluable_count)
            or not _nonnegative_int(self.event_count)
            or (
                self.event_rate_per_1000_evaluable is not None
                and type(self.event_rate_per_1000_evaluable) is not str
            )
        ):
            raise FiveCandidateDossierReportError()
        horizons = dict(self.horizon_summary or {})
        expected_horizons = SOURCE_SEMANTICS[self.candidate_id][4]
        if tuple(horizons) != expected_horizons or any(
            not isinstance(value, CandidateHorizonEvidence)
            for value in horizons.values()
        ):
            raise FiveCandidateDossierReportError()
        assert self.event_count is not None
        if self.event_count == 0 and any(
            value.sample_count != 0 for value in horizons.values()
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "horizon_summary", MappingProxyType(horizons))
        object.__setattr__(
            self,
            "yearly",
            _freeze_yearly_evidence(
                self.candidate_id,
                self.event_count,
                self.yearly,
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateIdentityEvidence:
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    source_event_kind: str
    source_timeframes: tuple[str, ...]
    evaluable_unit: str
    horizon_semantics: str
    horizons_bars: tuple[int, ...]

    def __post_init__(self) -> None:
        semantics = SOURCE_SEMANTICS.get(self.candidate_id)
        if (
            semantics is None
            or (
                self.source_kind,
                tuple(self.source_timeframes),
                self.evaluable_unit,
                self.horizon_semantics,
                tuple(self.horizons_bars),
            )
            != semantics
            or self.source_event_kind != _SOURCE_EVENT_KINDS[self.candidate_id]
            or type(self.policy_id) is not str
            or not self.policy_id
            or type(self.formula_version) is not str
            or not self.formula_version
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "source_timeframes", tuple(self.source_timeframes))
        object.__setattr__(self, "horizons_bars", tuple(self.horizons_bars))


@dataclass(frozen=True, slots=True)
class CandidateProspectiveEvidence:
    first_trading_day: date
    through: date
    status: str
    consumed: bool
    embargo_trading_days: tuple[date, ...]

    def __post_init__(self) -> None:
        embargo = tuple(self.embargo_trading_days)
        if (
            type(self.first_trading_day) is not date
            or type(self.through) is not date
            or self.through >= self.first_trading_day
            or self.status not in {"pending", "evaluated"}
            or self.consumed is not False
            or any(type(value) is not date for value in embargo)
            or tuple(sorted(set(embargo))) != embargo
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "embargo_trading_days", embargo)


@dataclass(frozen=True, slots=True)
class CandidateBaselineEvidence:
    artifact_id: str
    symbol: str
    validation_protocol_id: str
    baseline_request_through: date
    retrospective_since: date
    retrospective_through: date
    retrospective_event_count: int
    evaluable_count: int
    rolling_fold_count: int
    folds_with_events: int
    prospective: CandidateProspectiveEvidence
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        window = _RETROSPECTIVE_WINDOWS.get(self.artifact_id)
        flags = tuple(self.quality_flags)
        if (
            window is None
            or self.symbol != "jm"
            or type(self.validation_protocol_id) is not str
            or not self.validation_protocol_id
            or type(self.baseline_request_through) is not date
            or (self.retrospective_since, self.retrospective_through) != window
            or not _nonnegative_int(self.retrospective_event_count)
            or not _nonnegative_int(self.evaluable_count)
            or not _positive_int(self.rolling_fold_count)
            or not _nonnegative_int(self.folds_with_events)
            or self.folds_with_events > self.rolling_fold_count
            or not isinstance(self.prospective, CandidateProspectiveEvidence)
            or any(type(flag) is not str or not flag for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "quality_flags", flags)


@dataclass(frozen=True, slots=True)
class CandidateRobustnessEvidence:
    artifact_id: str
    robustness_protocol_id: str
    retrospective_since: date
    retrospective_through: date
    matrix_cell_count: int
    available_symbol_count: int
    unavailable_symbol_count: int
    unavailable_reason_counts: Mapping[str, int]
    zero_event_symbol_count: int
    zero_sample_symbol_count_by_horizon: Mapping[int, int]
    sector_evidence: tuple[object, ...]
    yearly_evidence: tuple[object, ...]
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        reason_counts = dict(self.unavailable_reason_counts)
        zero_samples = dict(self.zero_sample_symbol_count_by_horizon)
        sectors = tuple(_deep_freeze(value) for value in self.sector_evidence)
        yearly = tuple(_deep_freeze(value) for value in self.yearly_evidence)
        flags = tuple(self.quality_flags)
        expected_horizons = (
            (3, 5, 8)
            if self.artifact_id == "multi_candidate_robustness_v1"
            else (3, 5, 8, 20)
            if self.artifact_id == "jdj_active60_robustness_v1"
            else ()
        )
        allowed_windows = (
            {
                (date(2023, 1, 1), date(2026, 8, 18)),
            }
            if self.artifact_id == "multi_candidate_robustness_v1"
            else {
                _RETROSPECTIVE_WINDOWS[_CANDIDATES[2]],
            }
            if self.artifact_id == "jdj_active60_robustness_v1"
            else set()
        )
        if (
            not expected_horizons
            or type(self.robustness_protocol_id) is not str
            or not self.robustness_protocol_id
            or (self.retrospective_since, self.retrospective_through)
            not in allowed_windows
            or self.matrix_cell_count != 60
            or not _nonnegative_int(self.available_symbol_count)
            or not _nonnegative_int(self.unavailable_symbol_count)
            or self.available_symbol_count + self.unavailable_symbol_count != 60
            or any(type(key) is not str or not key for key in reason_counts)
            or any(not _positive_int(value) for value in reason_counts.values())
            or sum(reason_counts.values()) != self.unavailable_symbol_count
            or not _nonnegative_int(self.zero_event_symbol_count)
            or self.zero_event_symbol_count > self.available_symbol_count
            or tuple(zero_samples) != expected_horizons
            or any(
                not _nonnegative_int(value) or value > self.available_symbol_count
                for value in zero_samples.values()
            )
            or any(type(flag) is not str or not flag for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "unavailable_reason_counts", MappingProxyType(reason_counts))
        object.__setattr__(self, "zero_sample_symbol_count_by_horizon", MappingProxyType(zero_samples))
        object.__setattr__(self, "sector_evidence", sectors)
        object.__setattr__(self, "yearly_evidence", yearly)
        object.__setattr__(self, "quality_flags", flags)


@dataclass(frozen=True, slots=True)
class CandidateEvidenceReferences:
    temporal: object
    cross_symbol: tuple[CandidateCrossSymbolEvidence, ...]
    sector: tuple[object, ...]
    yearly: tuple[object, ...]
    horizon: object
    quality: tuple[str, ...]

    def __post_init__(self) -> None:
        rows = tuple(self.cross_symbol)
        flags = tuple(self.quality)
        if (
            len(rows) != 60
            or any(not isinstance(row, CandidateCrossSymbolEvidence) for row in rows)
            or any(type(flag) is not str or not flag for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "temporal", _deep_freeze(self.temporal))
        object.__setattr__(self, "cross_symbol", rows)
        object.__setattr__(self, "sector", tuple(_deep_freeze(value) for value in self.sector))
        object.__setattr__(self, "yearly", tuple(_deep_freeze(value) for value in self.yearly))
        object.__setattr__(self, "horizon", _deep_freeze(self.horizon))
        object.__setattr__(self, "quality", flags)


@dataclass(frozen=True, slots=True)
class CandidateDossier:
    identity: CandidateIdentityEvidence
    baseline: CandidateBaselineEvidence
    robustness: CandidateRobustnessEvidence
    evidence_references: CandidateEvidenceReferences

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, CandidateIdentityEvidence)
            or not isinstance(self.baseline, CandidateBaselineEvidence)
            or not isinstance(self.robustness, CandidateRobustnessEvidence)
            or not isinstance(self.evidence_references, CandidateEvidenceReferences)
        ):
            raise FiveCandidateDossierReportError()
        rows = tuple(self.evidence_references.cross_symbol)
        available = tuple(row for row in rows if row.status == "available")
        unavailable = tuple(row for row in rows if row.status == "unavailable")
        reason_counts = Counter(
            row.reason_code for row in unavailable if row.reason_code is not None
        )
        zero_samples = {
            horizon: sum(
                row.horizon_summary[horizon].sample_count == 0
                for row in available
                if row.horizon_summary is not None
            )
            for horizon in self.identity.horizons_bars
        }
        if (
            self.identity.candidate_id != self.baseline.artifact_id
            or self.robustness.artifact_id
            != _expected_robustness_artifact(self.identity.candidate_id)
            or any(
                row.candidate_id != self.identity.candidate_id
                for row in rows
            )
            or self.robustness.matrix_cell_count != len(rows)
            or self.robustness.available_symbol_count != len(available)
            or self.robustness.unavailable_symbol_count != len(unavailable)
            or dict(self.robustness.unavailable_reason_counts)
            != dict(reason_counts)
            or self.robustness.zero_event_symbol_count
            != sum(row.event_count == 0 for row in available)
            or dict(self.robustness.zero_sample_symbol_count_by_horizon)
            != zero_samples
        ):
            raise FiveCandidateDossierReportError()


@dataclass(frozen=True, slots=True)
class FiveCandidateResearchDossier:
    schema_version: int
    command: str
    status: str
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    prospective_consumed: bool
    candidate_order: tuple[str, ...]
    source_artifacts: tuple[SourceArtifactRef, ...]
    candidate_dossiers: tuple[CandidateDossier, ...]
    metric_catalog: tuple[object, ...]
    comparability_pairs: tuple[object, ...]
    quality_flags: tuple[str, ...]
    safety: Mapping[str, bool]

    def __post_init__(self) -> None:
        artifacts = tuple(self.source_artifacts)
        dossiers = tuple(self.candidate_dossiers)
        metric_catalog = tuple(self.metric_catalog)
        comparability_pairs = tuple(self.comparability_pairs)
        flags = tuple(self.quality_flags)
        safety = dict(self.safety)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.command
            != "guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1"
            or self.status != "ok"
            or self.protocol_id != "five_candidate_research_dossier_v1"
            or type(self.frozen_at) is not datetime
            or self.research_only is not True
            or self.readonly is not True
            or self.prospective_consumed is not False
            or tuple(self.candidate_order) != _CANDIDATES
            or len(artifacts) != 7
            or any(not isinstance(value, SourceArtifactRef) for value in artifacts)
            or tuple(item.identity.candidate_id for item in dossiers) != _CANDIDATES
            or metric_catalog
            or comparability_pairs
            or any(type(flag) is not str or not flag for flag in flags)
            or len(set(flags)) != len(flags)
            or set(safety)
            != {
                "new_metric_calculation",
                "new_relationship_calculation",
                "parameter_perturbation",
                "automatic_scoring",
                "automatic_ranking",
                "automatic_promotion",
            }
            or any(value is not False for value in safety.values())
        ):
            raise FiveCandidateDossierReportError()
        object.__setattr__(self, "candidate_order", tuple(self.candidate_order))
        object.__setattr__(self, "source_artifacts", artifacts)
        object.__setattr__(self, "candidate_dossiers", dossiers)
        object.__setattr__(self, "metric_catalog", metric_catalog)
        object.__setattr__(self, "comparability_pairs", comparability_pairs)
        object.__setattr__(self, "quality_flags", flags)
        object.__setattr__(self, "safety", MappingProxyType(safety))


@dataclass(frozen=True, slots=True)
class FiveCandidateDossierProtocol:
    schema_version: int
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    candidate_order: tuple[str, ...]
    source_artifacts: tuple[SourceArtifactRef, ...]
    comparability_pair_order: tuple[tuple[str, str], ...]
    prospective_consumed: bool
    new_metric_calculation: bool
    new_relationship_calculation: bool
    parameter_perturbation: bool
    automatic_scoring: bool
    automatic_ranking: bool
    automatic_promotion: bool

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.protocol_id != "five_candidate_research_dossier_v1"
            or self.frozen_at
            != datetime.fromisoformat("2026-08-22T11:43:34+08:00")
            or self.research_only is not True
            or self.readonly is not True
            or self.candidate_order != _CANDIDATES
            or self.source_artifacts
            != tuple(SourceArtifactRef(*values) for values in _SOURCE_ARTIFACTS)
            or self.comparability_pair_order != _PAIR_ORDER
            or self.prospective_consumed is not False
            or self.new_metric_calculation is not False
            or self.new_relationship_calculation is not False
            or self.parameter_perturbation is not False
            or self.automatic_scoring is not False
            or self.automatic_ranking is not False
            or self.automatic_promotion is not False
        ):
            raise FiveCandidateDossierProtocolError()


@dataclass(frozen=True, slots=True)
class FiveCandidateDossierRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != "five_candidate_research_dossier_v1":
            raise FiveCandidateDossierProtocolError()


def load_five_candidate_dossier_protocol(
    path: Path | None = None,
) -> FiveCandidateDossierProtocol:
    payload = load_exact_json(
        path or _PROTOCOL_PATH,
        _EXPECTED,
        FiveCandidateDossierProtocolError,
    )
    try:
        source_artifacts = tuple(
            SourceArtifactRef(
                artifact_id=value["artifact_id"],
                path=value["path"],
                expected_sha256=value["expected_sha256"],
            )
            for value in payload["source_artifacts"]
        )
    except FiveCandidateDossierSourceError:
        raise FiveCandidateDossierProtocolError() from None
    return FiveCandidateDossierProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        frozen_at=datetime.fromisoformat(payload["frozen_at"]),
        research_only=payload["research_only"],
        readonly=payload["readonly"],
        candidate_order=tuple(payload["candidate_order"]),
        source_artifacts=source_artifacts,
        comparability_pair_order=tuple(
            tuple(pair) for pair in payload["comparability_pair_order"]
        ),
        prospective_consumed=payload["prospective_consumed"],
        new_metric_calculation=payload["new_metric_calculation"],
        new_relationship_calculation=payload["new_relationship_calculation"],
        parameter_perturbation=payload["parameter_perturbation"],
        automatic_scoring=payload["automatic_scoring"],
        automatic_ranking=payload["automatic_ranking"],
        automatic_promotion=payload["automatic_promotion"],
    )


def _expected_robustness_artifact(candidate_id: str) -> str:
    if candidate_id in _CANDIDATES[:2]:
        return "multi_candidate_robustness_v1"
    if candidate_id in _CANDIDATES[2:]:
        return "jdj_active60_robustness_v1"
    raise FiveCandidateDossierReportError()


def _freeze_yearly_evidence(
    candidate_id: str,
    event_count: int,
    value: object | None,
) -> object | None:
    if candidate_id in _CANDIDATES[:2]:
        if value is not None:
            raise FiveCandidateDossierReportError()
        return None
    if not isinstance(value, Mapping):
        raise FiveCandidateDossierReportError()
    yearly = dict(value)
    expected_years = ("2023", "2024", "2025", "2026")
    expected_horizons = SOURCE_SEMANTICS[candidate_id][4]
    if set(yearly) != set(expected_years):
        raise FiveCandidateDossierReportError()
    total_event_count = 0
    for year in expected_years:
        item = yearly[year]
        if not isinstance(item, Mapping):
            raise FiveCandidateDossierReportError()
        year_evidence = dict(item)
        if set(year_evidence) != {"event_count", "horizon_summary"}:
            raise FiveCandidateDossierReportError()
        year_event_count = year_evidence["event_count"]
        horizons = year_evidence["horizon_summary"]
        if not _nonnegative_int(year_event_count) or not isinstance(
            horizons,
            Mapping,
        ):
            raise FiveCandidateDossierReportError()
        horizon_values = dict(horizons)
        if set(horizon_values) != {
            str(horizon) for horizon in expected_horizons
        }:
            raise FiveCandidateDossierReportError()
        year_sample_counts: list[int] = []
        for horizon in expected_horizons:
            raw_summary = horizon_values[str(horizon)]
            if not isinstance(raw_summary, Mapping):
                raise FiveCandidateDossierReportError()
            summary = dict(raw_summary)
            if set(summary) != {
                "sample_count",
                "historical_positive_outcome_rate",
                "median_directional_return_bps",
            }:
                raise FiveCandidateDossierReportError()
            sample_count = summary.pop("sample_count")
            CandidateHorizonEvidence(
                sample_count=sample_count,  # type: ignore[arg-type]
                numeric_metrics=summary,  # type: ignore[arg-type]
            )
            if sample_count > year_event_count:  # type: ignore[operator]
                raise FiveCandidateDossierReportError()
            year_sample_counts.append(sample_count)  # type: ignore[arg-type]
        if year_event_count == 0 and any(year_sample_counts):
            raise FiveCandidateDossierReportError()
        total_event_count += year_event_count
    if total_event_count != event_count:
        raise FiveCandidateDossierReportError()
    return _deep_freeze(yearly)


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    return value


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _symbol(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value.isascii()
        and value.isalpha()
        and value == value.lower()
    )
