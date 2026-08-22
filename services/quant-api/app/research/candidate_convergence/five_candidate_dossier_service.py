from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from types import MappingProxyType

from app.core.env import PROJECT_ROOT
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
    VerifiedJsonArtifact,
    verify_json_artifact,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    CandidateBaselineEvidence,
    CandidateCrossSymbolEvidence,
    CandidateDossier,
    CandidateEvidenceReferences,
    CandidateHorizonEvidence,
    CandidateIdentityEvidence,
    CandidateProspectiveEvidence,
    CandidateRobustnessEvidence,
    ComparabilityPair,
    ComparabilityStatus,
    FiveCandidateDossierProtocol,
    FiveCandidateDossierProtocolError,
    FiveCandidateDossierReportError,
    FiveCandidateDossierRequest,
    FiveCandidateResearchDossier,
    MetricComparability,
    SOURCE_SEMANTICS,
)
from app.research.candidate_convergence.identities import (
    ACTIVE60_PRODUCTS,
    ACTIVE60_SECTORS,
    CANDIDATE_BASELINE_IDENTITIES,
    CANDIDATE_EVENT_KINDS,
    DOSSIER_PAIR_ORDER,
    FIVE_CANDIDATE_ORDER,
)


_CANDIDATES = FIVE_CANDIDATE_ORDER
_PAIR_ORDER = DOSSIER_PAIR_ORDER
_PRODUCTS = ACTIVE60_PRODUCTS
_SECTORS = ACTIVE60_SECTORS
_EVENT_KINDS = CANDIDATE_EVENT_KINDS
_BASELINE_IDENTITIES = CANDIDATE_BASELINE_IDENTITIES
_TEMPORAL_IDENTITIES = {
    _CANDIDATES[0]: {
        "anchor_symbol": "jm",
        "candidate_protocol_id": "candidate_validation_v1",
        "source_kind": "subing_lifecycle",
        "event_unit": "entry_confirmed",
        "retrospective_since": "2023-01-01",
        "retrospective_through": "2026-08-18",
        "prospective_status": "pending",
        "prospective_first_trading_day": "2026-08-20",
        "prospective_through": "2026-08-19",
        "horizon_semantics": "same_trading_day_only",
    },
    _CANDIDATES[1]: {
        "anchor_symbol": "jm",
        "candidate_protocol_id": "n_structure_validation_v1",
        "source_kind": "n_structure",
        "event_unit": "n_completed",
        "retrospective_since": "2023-01-01",
        "retrospective_through": "2026-08-19",
        "prospective_status": "pending",
        "prospective_first_trading_day": "2026-08-21",
        "prospective_through": "2026-08-20",
        "horizon_semantics": "same_rank1_segment",
    },
}
_SHARED_METRIC_IDS = (
    "evidence_availability",
    "zero_event_inventory",
    "zero_sample_inventory",
    "rolling_fold_coverage",
    "prospective_status",
)
_JDJ_METRIC_IDS = (
    "event_rate",
    "long_short_event_count",
    "source_outcome_horizon_3",
    "source_outcome_horizon_5",
    "source_outcome_horizon_8",
    "source_outcome_horizon_20",
    "yearly_evidence",
    "symbol_balanced_sector_evidence",
)


class FiveCandidateResearchDossierService:
    def __init__(
        self,
        protocol: FiveCandidateDossierProtocol,
        *,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        if not isinstance(protocol, FiveCandidateDossierProtocol):
            raise FiveCandidateDossierProtocolError()
        self._protocol = protocol
        self._project_root = project_root

    def run(
        self,
        request: FiveCandidateDossierRequest,
    ) -> FiveCandidateResearchDossier:
        self._validate_request_protocol_identity(request)
        verified = tuple(
            verify_json_artifact(ref, self._project_root)
            for ref in self._protocol.source_artifacts
        )
        try:
            baselines = {
                candidate_id: _validated_baseline(
                    verified[index], candidate_id
                )
                for index, candidate_id in enumerate(_CANDIDATES)
            }
            multi = _validated_robustness_source(
                verified[5],
                "multi_candidate_robustness_v1",
                _CANDIDATES[:2],
            )
            jdj = _validated_robustness_source(
                verified[6],
                "jdj_active60_robustness_v1",
                _CANDIDATES[2:],
            )
            dossiers = tuple(
                self._project_candidate(
                    candidate_id,
                    baselines[candidate_id],
                    multi if candidate_id in _CANDIDATES[:2] else jdj,
                )
                for candidate_id in _CANDIDATES
            )
            relationship_reference = _project_relationship_reference(multi)
            metric_catalog = _metric_catalog()
            comparability_pairs = _comparability_pairs(relationship_reference)
        except (KeyError, TypeError, ValueError, FiveCandidateDossierReportError):
            raise FiveCandidateDossierSourceError() from None

        quality_flags = _ordered_unique(
            flag
            for artifact in verified
            for flag in _string_tuple(artifact.payload["quality_flags"])
        )
        return FiveCandidateResearchDossier(
            schema_version=1,
            command=(
                "guiyi research candidate-dossier "
                "--protocol five_candidate_research_dossier_v1"
            ),
            status="ok",
            protocol_id=self._protocol.protocol_id,
            frozen_at=self._protocol.frozen_at,
            research_only=True,
            readonly=True,
            prospective_consumed=False,
            candidate_order=_CANDIDATES,
            source_artifacts=tuple(item.ref for item in verified),
            candidate_dossiers=dossiers,
            metric_catalog=metric_catalog,
            comparability_pairs=comparability_pairs,
            quality_flags=quality_flags,
            safety=MappingProxyType(
                {
                    "new_metric_calculation": False,
                    "new_relationship_calculation": False,
                    "parameter_perturbation": False,
                    "automatic_scoring": False,
                    "automatic_ranking": False,
                    "automatic_promotion": False,
                }
            ),
        )

    def _validate_request_protocol_identity(
        self,
        request: FiveCandidateDossierRequest,
    ) -> None:
        protocol = self._protocol
        if (
            not isinstance(request, FiveCandidateDossierRequest)
            or request.protocol_id != protocol.protocol_id
            or protocol.protocol_id != "five_candidate_research_dossier_v1"
            or protocol.candidate_order != _CANDIDATES
            or len(protocol.source_artifacts) != 7
            or protocol.research_only is not True
            or protocol.readonly is not True
            or protocol.prospective_consumed is not False
            or any(
                value is not False
                for value in (
                    protocol.new_metric_calculation,
                    protocol.new_relationship_calculation,
                    protocol.parameter_perturbation,
                    protocol.automatic_scoring,
                    protocol.automatic_ranking,
                    protocol.automatic_promotion,
                )
            )
        ):
            raise FiveCandidateDossierProtocolError()

    def _project_candidate(
        self,
        candidate_id: str,
        baseline_source: VerifiedJsonArtifact,
        robustness_source: VerifiedJsonArtifact,
    ) -> CandidateDossier:
        baseline_payload = baseline_source.payload
        robustness_payload = robustness_source.payload
        identity_values = SOURCE_SEMANTICS[candidate_id]
        identity = CandidateIdentityEvidence(
            candidate_id=candidate_id,
            source_kind=identity_values[0],
            policy_id=_string(baseline_payload["policy_id"]),
            formula_version=_string(baseline_payload["formula_version"]),
            source_event_kind=_EVENT_KINDS[candidate_id],
            source_timeframes=identity_values[1],
            evaluable_unit=identity_values[2],
            horizon_semantics=identity_values[3],
            horizons_bars=identity_values[4],
        )
        rows = tuple(
            _project_cross_symbol(_mapping(row), candidate_id)
            for row in _list(robustness_payload["cross_symbol_results"])
            if _mapping(row).get("candidate_id") == candidate_id
        )
        baseline = _project_baseline(
            candidate_id,
            baseline_source,
            robustness_source,
            rows,
        )
        robustness = _project_robustness(
            candidate_id,
            robustness_source,
            rows,
        )
        baseline_quality = _string_tuple(baseline_payload["quality_flags"])
        robustness_quality = _string_tuple(robustness_payload["quality_flags"])
        retrospective = _mapping(baseline_payload["retrospective"])
        return CandidateDossier(
            identity=identity,
            baseline=baseline,
            robustness=robustness,
            evidence_references=CandidateEvidenceReferences(
                temporal=retrospective,
                cross_symbol=rows,
                sector=robustness.sector_evidence,
                yearly=robustness.yearly_evidence,
                horizon=_mapping(retrospective["horizon_summary"]),
                quality=_ordered_unique((*baseline_quality, *robustness_quality)),
            ),
        )


def _validated_baseline(
    artifact: VerifiedJsonArtifact,
    candidate_id: str,
) -> VerifiedJsonArtifact:
    payload = artifact.payload
    identity = _BASELINE_IDENTITIES[candidate_id]
    retrospective = _mapping(payload["retrospective"])
    prospective = _mapping(payload["prospective_oos"])
    rolling = _mapping(payload["rolling_stability"])
    expected_source_event = (
        _EVENT_KINDS[candidate_id]
        if candidate_id in _CANDIDATES[2:]
        else None
    )
    if (
        artifact.ref.artifact_id != candidate_id
        or payload.get("schema_version") != 1
        or payload.get("command") != "research.candidate-validation"
        or payload.get("status") != "ok"
        or payload.get("research_only") is not True
        or payload.get("readonly") is not True
        or payload.get("candidate_id") != candidate_id
        or payload.get("symbol") != "jm"
        or payload.get("protocol_id") != identity.protocol_id
        or payload.get("policy_id") != identity.policy_id
        or payload.get("formula_version") != identity.formula_version
        or payload.get("source_event_kind") != expected_source_event
        or _date(retrospective["since"]) != identity.retrospective_since
        or _date(retrospective["through"]) != identity.retrospective_through
        or _date(prospective["through"]) != identity.prospective_through
        or _date(prospective["first_trading_day"]) != identity.first_trading_day
        or prospective.get("status") != "pending"
        or prospective.get("result") is not None
        or rolling.get("fold_count") != 10
        or len(_list(payload["rolling_folds"])) != 10
    ):
        raise FiveCandidateDossierSourceError()
    _project_horizons(retrospective["horizon_summary"], candidate_id)
    _string_tuple(payload["quality_flags"])
    return artifact


def _validated_robustness_source(
    artifact: VerifiedJsonArtifact,
    protocol_id: str,
    candidate_ids: tuple[str, ...],
) -> VerifiedJsonArtifact:
    payload = artifact.payload
    rows = _list(payload["cross_symbol_results"])
    expected_order = tuple(
        (candidate_id, symbol)
        for candidate_id in candidate_ids
        for symbol in _PRODUCTS
    )
    status_inventory = tuple(
        (
            candidate_id,
            sum(
                _mapping(row).get("status") == "available"
                for row in rows
                if _mapping(row).get("candidate_id") == candidate_id
            ),
            sum(
                _mapping(row).get("status") == "unavailable"
                for row in rows
                if _mapping(row).get("candidate_id") == candidate_id
            ),
        )
        for candidate_id in candidate_ids
    )
    if (
        artifact.ref.artifact_id != protocol_id
        or payload.get("schema_version") != 1
        or payload.get("protocol_id") != protocol_id
        or payload.get("research_only") is not True
        or payload.get("readonly") is not True
        or tuple(
            (_mapping(row).get("candidate_id"), _mapping(row).get("symbol"))
            for row in rows
        )
        != expected_order
        or status_inventory
        != tuple((candidate_id, 49, 11) for candidate_id in candidate_ids)
    ):
        raise FiveCandidateDossierSourceError()
    if protocol_id == "multi_candidate_robustness_v1":
        temporal_dossiers = tuple(
            _mapping(value) for value in _list(payload["temporal_dossiers"])
        )
        if (
            payload.get("status") != "ok"
            or len(rows) != 120
            or _mapping(payload["common_retrospective"])
            != {"since": "2023-01-01", "through": "2026-08-18"}
            or tuple(
                value.get("candidate_id") for value in temporal_dossiers
            )
            != candidate_ids
            or tuple(_list(payload["metric_compatibility_flags"]))
            != ("EVALUABLE_UNIT_DIFFERS", "HORIZON_SEMANTICS_DIFFERS")
            or tuple(
                (
                    _mapping(value).get("source_candidate_id"),
                    _mapping(value).get("target_candidate_id"),
                )
                for value in _list(payload["relationships"])
            )
            != ((candidate_ids[0], candidate_ids[1]), (candidate_ids[1], candidate_ids[0]))
        ):
            raise FiveCandidateDossierSourceError()
        for value, candidate_id in zip(
            temporal_dossiers,
            candidate_ids,
            strict=True,
        ):
            _validate_temporal_dossier(value, candidate_id)
    else:
        if (
            len(rows) != 180
            or tuple(_list(payload["candidate_ids"])) != candidate_ids
            or _mapping(payload["common_retrospective"])
            != {"since": "2023-01-01", "through": "2026-08-20"}
            or payload.get("prospective_consumed") is not False
            or tuple(
                (
                    _mapping(value).get("candidate_id"),
                    _mapping(value).get("sector"),
                )
                for value in _list(payload["sector_summaries"])
            )
            != tuple(
                (candidate_id, sector)
                for candidate_id in candidate_ids
                for sector in _SECTORS
            )
        ):
            raise FiveCandidateDossierSourceError()
    for row in rows:
        _project_cross_symbol(_mapping(row), _string(_mapping(row)["candidate_id"]))
    _string_tuple(payload["quality_flags"])
    return artifact


def _metric_catalog() -> tuple[MetricComparability, ...]:
    return (
        *(
            MetricComparability(
                metric_id=metric_id,
                candidate_ids=_CANDIDATES,
                status=ComparabilityStatus.SUPPORTED_EXISTING,
                reason_codes=(),
            )
            for metric_id in _SHARED_METRIC_IDS
        ),
        *(
            MetricComparability(
                metric_id=metric_id,
                candidate_ids=_CANDIDATES[2:],
                status=ComparabilityStatus.SUPPORTED_SAME_FAMILY,
                reason_codes=(),
            )
            for metric_id in _JDJ_METRIC_IDS
        ),
        MetricComparability(
            metric_id="subing_source_outcome_horizons_3_5_8",
            candidate_ids=(_CANDIDATES[0],),
            status=ComparabilityStatus.NOT_COMPARABLE,
            reason_codes=("EVALUABLE_UNIT_DIFFERS", "HORIZON_SEMANTICS_DIFFERS"),
        ),
        MetricComparability(
            metric_id="n_source_outcome_horizons_3_5_8",
            candidate_ids=(_CANDIDATES[1],),
            status=ComparabilityStatus.NOT_COMPARABLE,
            reason_codes=("EVALUABLE_UNIT_DIFFERS", "HORIZON_SEMANTICS_DIFFERS"),
        ),
    )


def _comparability_pairs(
    relationship_reference: Mapping[str, object],
) -> tuple[ComparabilityPair, ...]:
    statuses = (
        ComparabilityStatus.SUPPORTED_EXISTING,
        *(ComparabilityStatus.NOT_COMPARABLE for _ in range(3)),
        *(ComparabilityStatus.NOT_YET_DEFINED for _ in range(3)),
        *(ComparabilityStatus.SUPPORTED_SAME_FAMILY for _ in range(3)),
    )
    reasons = (
        (
            "EXISTING_RELATIONSHIP_REFERENCE_ONLY",
            "EVALUABLE_UNIT_DIFFERS",
            "HORIZON_SEMANTICS_DIFFERS",
        ),
        *(("CROSS_TIMEFRAME_ALIGNMENT_UNDEFINED",) for _ in range(3)),
        *(
            (
                "STRUCTURAL_CONTEXT_DEPENDENCY_ONLY",
                "PAIR_METRIC_NOT_YET_DEFINED",
            )
            for _ in range(3)
        ),
        *(("SAME_FAMILY_SOURCE_SEMANTICS",) for _ in range(3)),
    )
    return tuple(
        ComparabilityPair(
            left_candidate_id=left,
            right_candidate_id=right,
            status=status,
            reason_codes=reason_codes,
            existing_relationship_reference=(
                relationship_reference if index == 0 else None
            ),
        )
        for index, ((left, right), status, reason_codes) in enumerate(
            zip(_PAIR_ORDER, statuses, reasons, strict=True)
        )
    )


def _project_relationship_reference(
    source: VerifiedJsonArtifact,
) -> Mapping[str, object]:
    payload = source.payload
    return MappingProxyType(
        {
            "protocol_id": payload["protocol_id"],
            "common_retrospective": payload["common_retrospective"],
            "metric_compatibility_flags": payload["metric_compatibility_flags"],
            "relationships": payload["relationships"],
        }
    )


def _validate_temporal_dossier(
    value: Mapping[str, object],
    candidate_id: str,
) -> None:
    expected = _TEMPORAL_IDENTITIES[candidate_id]
    if value.get("candidate_id") != candidate_id or any(
        value.get(field) != expected_value
        for field, expected_value in expected.items()
    ):
        raise FiveCandidateDossierSourceError()
    retrospective_event_count = value.get("retrospective_event_count")
    rolling_fold_count = value.get("rolling_fold_count")
    folds_with_events = value.get("folds_with_events")
    if (
        not isinstance(retrospective_event_count, int)
        or not isinstance(rolling_fold_count, int)
        or not isinstance(folds_with_events, int)
        or rolling_fold_count != 10
        or folds_with_events > rolling_fold_count
    ):
        raise FiveCandidateDossierSourceError()
    _project_horizons(value["horizon_summary"], candidate_id)
    _string_tuple(value["source_quality_flags"])


def _project_baseline(
    candidate_id: str,
    baseline_source: VerifiedJsonArtifact,
    robustness_source: VerifiedJsonArtifact,
    rows: tuple[CandidateCrossSymbolEvidence, ...],
) -> CandidateBaselineEvidence:
    payload = baseline_source.payload
    retrospective = _mapping(payload["retrospective"])
    prospective = _mapping(payload["prospective_oos"])
    rolling = _mapping(payload["rolling_stability"])
    if candidate_id in _CANDIDATES[:2]:
        temporal = next(
            (
                _mapping(value)
                for value in _list(
                    robustness_source.payload["temporal_dossiers"]
                )
                if _mapping(value).get("candidate_id") == candidate_id
            ),
            None,
        )
        if temporal is None:
            raise FiveCandidateDossierSourceError()
        event_count = _nonnegative_int_value(
            temporal["retrospective_event_count"]
        )
        folds_with_events = _nonnegative_int_value(
            temporal["folds_with_events"]
        )
    else:
        anchor_row = next((row for row in rows if row.symbol == "jm"), None)
        if anchor_row is None or anchor_row.event_count is None:
            raise FiveCandidateDossierSourceError()
        event_count = anchor_row.event_count
        folds_with_events = _nonnegative_int_value(rolling["folds_with_events"])
    if candidate_id == _CANDIDATES[0]:
        evaluable_count = _nonnegative_int_value(
            retrospective["evaluable_boundary_count"]
        )
    else:
        evaluable_count = _nonnegative_int_value(retrospective["evaluable_bar_count"])
    embargo = (
        tuple(
            _date(value)
            for value in _list(robustness_source.payload["embargo_trading_days"])
        )
        if candidate_id in _CANDIDATES[2:]
        else ()
    )
    return CandidateBaselineEvidence(
        artifact_id=baseline_source.ref.artifact_id,
        symbol="jm",
        validation_protocol_id=_string(payload["protocol_id"]),
        baseline_request_through=_date(prospective["through"]),
        retrospective_since=_date(retrospective["since"]),
        retrospective_through=_date(retrospective["through"]),
        retrospective_event_count=event_count,
        evaluable_count=evaluable_count,
        rolling_fold_count=_nonnegative_int_value(rolling["fold_count"]),
        folds_with_events=folds_with_events,
        prospective=CandidateProspectiveEvidence(
            first_trading_day=_date(prospective["first_trading_day"]),
            through=_date(prospective["through"]),
            status=_string(prospective["status"]),
            consumed=False,
            embargo_trading_days=embargo,
        ),
        quality_flags=_string_tuple(payload["quality_flags"]),
    )


def _project_robustness(
    candidate_id: str,
    source: VerifiedJsonArtifact,
    rows: tuple[CandidateCrossSymbolEvidence, ...],
) -> CandidateRobustnessEvidence:
    available = tuple(row for row in rows if row.status == "available")
    unavailable = tuple(row for row in rows if row.status == "unavailable")
    reasons = Counter(
        row.reason_code for row in unavailable if row.reason_code is not None
    )
    horizons = SOURCE_SEMANTICS[candidate_id][4]
    zero_samples = {
        horizon: sum(
            row.horizon_summary[horizon].sample_count == 0
            for row in available
            if row.horizon_summary is not None
        )
        for horizon in horizons
    }
    payload = source.payload
    sector_evidence = (
        tuple(
            _mapping(value)
            for value in _list(payload["sector_summaries"])
            if _mapping(value).get("candidate_id") == candidate_id
        )
        if source.ref.artifact_id == "jdj_active60_robustness_v1"
        else ()
    )
    yearly_evidence = tuple(
        MappingProxyType({"symbol": row.symbol, "yearly": row.yearly})
        for row in rows
        if row.yearly is not None
    )
    common_retrospective = _mapping(payload["common_retrospective"])
    return CandidateRobustnessEvidence(
        artifact_id=source.ref.artifact_id,
        robustness_protocol_id=_string(payload["protocol_id"]),
        retrospective_since=_date(common_retrospective["since"]),
        retrospective_through=_date(common_retrospective["through"]),
        matrix_cell_count=len(rows),
        available_symbol_count=len(available),
        unavailable_symbol_count=len(unavailable),
        unavailable_reason_counts=MappingProxyType(dict(reasons)),
        zero_event_symbol_count=sum(row.event_count == 0 for row in available),
        zero_sample_symbol_count_by_horizon=MappingProxyType(zero_samples),
        sector_evidence=sector_evidence,
        yearly_evidence=yearly_evidence,
        quality_flags=_string_tuple(payload["quality_flags"]),
    )


def _project_cross_symbol(
    raw: Mapping[str, object],
    candidate_id: str,
) -> CandidateCrossSymbolEvidence:
    if raw.get("candidate_id") != candidate_id:
        raise FiveCandidateDossierSourceError()
    status = _string(raw["status"])
    is_jdj = candidate_id in _CANDIDATES[2:]
    if not is_jdj and (
        raw.get("source_kind") != SOURCE_SEMANTICS[candidate_id][0]
        or raw.get("evaluable_unit") != SOURCE_SEMANTICS[candidate_id][2]
        or raw.get("horizon_semantics") != SOURCE_SEMANTICS[candidate_id][3]
    ):
        raise FiveCandidateDossierSourceError()
    if status == "unavailable":
        nullable = (
            "evaluable_bar_count" if is_jdj else "evaluable_count",
            "event_count",
            "event_rate_per_1000_evaluable",
            "horizon_summary",
            "yearly",
        )
        if any(raw.get(key) is not None for key in nullable):
            raise FiveCandidateDossierSourceError()
        if is_jdj and any(
            raw.get(key) is not None
            for key in (
                "observed_since",
                "observed_through",
                "long_event_count",
                "short_event_count",
            )
        ):
            raise FiveCandidateDossierSourceError()
        return CandidateCrossSymbolEvidence(
            candidate_id=candidate_id,
            symbol=_string(raw["symbol"]),
            status=status,
            reason_code=_string(raw["reason_code"]),
            evaluable_count=None,
            event_count=None,
            event_rate_per_1000_evaluable=None,
            horizon_summary=None,
            sector=_optional_string(raw.get("sector")),
            yearly=None,
        )
    evaluable_key = "evaluable_bar_count" if is_jdj else "evaluable_count"
    event_count = _nonnegative_int_value(raw["event_count"])
    evaluable_count = _nonnegative_int_value(raw[evaluable_key])
    if status != "available" or raw.get("reason_code") is not None:
        raise FiveCandidateDossierSourceError()
    if is_jdj:
        long_count = _nonnegative_int_value(raw["long_event_count"])
        short_count = _nonnegative_int_value(raw["short_event_count"])
        if long_count + short_count != event_count:
            raise FiveCandidateDossierSourceError()
        _date(raw["observed_since"])
        _date(raw["observed_through"])
    return CandidateCrossSymbolEvidence(
        candidate_id=candidate_id,
        symbol=_string(raw["symbol"]),
        status=status,
        reason_code=None,
        evaluable_count=evaluable_count,
        event_count=event_count,
        event_rate_per_1000_evaluable=_optional_string(
            raw.get("event_rate_per_1000_evaluable")
        ),
        horizon_summary=_project_horizons(raw["horizon_summary"], candidate_id),
        sector=_optional_string(raw.get("sector")),
        yearly=raw.get("yearly"),
    )


def _project_horizons(
    raw: object,
    candidate_id: str,
) -> Mapping[int, CandidateHorizonEvidence]:
    values = _mapping(raw)
    expected = SOURCE_SEMANTICS[candidate_id][4]
    if set(values) != {str(value) for value in expected}:
        raise FiveCandidateDossierSourceError()
    projected: dict[int, CandidateHorizonEvidence] = {}
    for horizon in expected:
        item = _mapping(values[str(horizon)])
        metrics = {
            key: value
            for key, value in item.items()
            if key != "sample_count" and not key.endswith("_sample_count")
        }
        projected[horizon] = CandidateHorizonEvidence(
            sample_count=_nonnegative_int_value(item["sample_count"]),
            numeric_metrics=MappingProxyType(metrics),  # type: ignore[arg-type]
        )
    return MappingProxyType(projected)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FiveCandidateDossierSourceError()
    return value


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise FiveCandidateDossierSourceError()
    return value


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise FiveCandidateDossierSourceError()
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    values = _list(value)
    result = tuple(_string(item) for item in values)
    if len(set(result)) != len(result):
        raise FiveCandidateDossierSourceError()
    return result


def _nonnegative_int_value(value: object) -> int:
    if type(value) is not int or value < 0:
        raise FiveCandidateDossierSourceError()
    return value


def _date(value: object) -> date:
    try:
        if type(value) is not str:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise FiveCandidateDossierSourceError() from None


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
