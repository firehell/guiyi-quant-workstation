from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
from types import MappingProxyType

import pytest

from app.core.env import PROJECT_ROOT
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
    SourceArtifactRef,
    verify_json_artifact,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    CandidateCrossSymbolEvidence,
    CandidateHorizonEvidence,
    FiveCandidateDossierReportError,
    FiveCandidateDossierProtocolError,
    FiveCandidateDossierRequest,
    load_five_candidate_dossier_protocol,
)
from app.research.candidate_convergence.five_candidate_dossier_service import (
    FiveCandidateResearchDossierService,
)


CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)
PROTOCOL_PATH = (
    PROJECT_ROOT / "data/research_protocols/five_candidate_research_dossier_v1.json"
)


@pytest.fixture
def service() -> FiveCandidateResearchDossierService:
    return FiveCandidateResearchDossierService(
        load_five_candidate_dossier_protocol()
    )


def test_dossier_protocol_is_exact() -> None:
    protocol = load_five_candidate_dossier_protocol()

    assert protocol.protocol_id == "five_candidate_research_dossier_v1"
    assert protocol.candidate_order == CANDIDATES
    assert len(protocol.source_artifacts) == 7
    assert len(protocol.comparability_pair_order) == 10
    assert protocol.research_only is True
    assert protocol.readonly is True
    assert protocol.prospective_consumed is False
    assert protocol.new_metric_calculation is False
    assert protocol.new_relationship_calculation is False
    assert protocol.parameter_perturbation is False
    assert protocol.automatic_scoring is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False


def _write_mutated_protocol(tmp_path: Path, mutator) -> Path:
    payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(payload)
    mutator(mutated)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.__setitem__("extra", True),
        lambda payload: payload["candidate_order"].reverse(),
        lambda payload: payload["comparability_pair_order"].reverse(),
        lambda payload: payload["source_artifacts"][0].__setitem__(
            "path", "/tmp/source.json"
        ),
        lambda payload: payload["source_artifacts"][0].__setitem__(
            "path", "reports/../source.json"
        ),
        lambda payload: payload["source_artifacts"][0].__setitem__(
            "expected_sha256", "A" * 64
        ),
    ],
    ids=(
        "extra-field",
        "candidate-order",
        "pair-order",
        "absolute-path",
        "path-escape",
        "invalid-sha",
    ),
)
def test_dossier_protocol_rejects_drift(tmp_path: Path, mutator) -> None:
    path = _write_mutated_protocol(tmp_path, mutator)

    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(path)


@pytest.mark.parametrize(
    ("artifact_id", "path", "sha256"),
    [
        ("", "source.json", "a" * 64),
        ("artifact", "/source.json", "a" * 64),
        ("artifact", "reports//source.json", "a" * 64),
        ("artifact", "reports/./source.json", "a" * 64),
        ("artifact", "reports/../source.json", "a" * 64),
        ("artifact\n", "source.json", "a" * 64),
        ("artifact", "source\n.json", "a" * 64),
        ("artifact", "source.json", "A" * 64),
    ],
)
def test_source_artifact_ref_rejects_invalid_identity(
    artifact_id: str,
    path: str,
    sha256: str,
) -> None:
    with pytest.raises(FiveCandidateDossierSourceError):
        SourceArtifactRef(artifact_id, path, sha256)


def test_verify_json_artifact_returns_immutable_verified_object(tmp_path: Path) -> None:
    raw = b'{"candidate_id":"one"}'
    source = tmp_path / "reports/source.json"
    source.parent.mkdir()
    source.write_bytes(raw)
    expected_sha256 = hashlib.sha256(raw).hexdigest()
    ref = SourceArtifactRef("one", "reports/source.json", expected_sha256)

    verified = verify_json_artifact(ref, tmp_path)

    assert verified.ref is ref
    assert verified.verified_sha256 == expected_sha256
    assert isinstance(verified.payload, MappingProxyType)
    assert verified.payload == {"candidate_id": "one"}
    with pytest.raises(TypeError):
        verified.payload["candidate_id"] = "changed"  # type: ignore[index]


def test_verify_json_artifact_fails_closed_without_source_details(
    tmp_path: Path,
) -> None:
    source = tmp_path / "secret-source.json"
    source.write_text("[]", encoding="utf-8")
    ref = SourceArtifactRef("one", source.name, "a" * 64)

    with pytest.raises(FiveCandidateDossierSourceError) as raised:
        verify_json_artifact(ref, tmp_path)

    assert str(raised.value) == "FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID"
    assert str(source) not in str(raised.value)
    assert "[]" not in str(raised.value)
    assert ref.expected_sha256 not in str(raised.value)


def test_verify_json_artifact_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("{}", encoding="utf-8")
    source = tmp_path / "source.json"
    source.symlink_to(outside)
    ref = SourceArtifactRef(
        "one",
        source.name,
        hashlib.sha256(outside.read_bytes()).hexdigest(),
    )

    with pytest.raises(FiveCandidateDossierSourceError):
        verify_json_artifact(ref, tmp_path)


def test_request_is_pinned_to_exact_protocol() -> None:
    request = FiveCandidateDossierRequest(
        protocol_id="five_candidate_research_dossier_v1"
    )

    assert request.protocol_id == "five_candidate_research_dossier_v1"
    with pytest.raises(FiveCandidateDossierProtocolError):
        FiveCandidateDossierRequest(protocol_id="other")


def test_all_source_artifacts_verify_without_runtime_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session

    from app.market_data.market_data_service import MarketDataService
    from app.research.jdj.jdj_candidate_validation_service import (
        JdjCandidateValidationService,
    )
    from app.research.n_structure.n_candidate_validation_service import (
        NStructureCandidateValidationService,
    )
    from app.research.robustness.jdj_robustness_service import (
        JdjActive60RobustnessService,
    )
    from app.research.robustness.multi_candidate_robustness_service import (
        MultiCandidateRobustnessService,
    )
    from app.research.subing.subing_candidate_validation_service import (
        SubingCandidateValidationService,
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("runtime constructor invoked")

    for target in (
        Session,
        MarketDataService,
        SubingCandidateValidationService,
        NStructureCandidateValidationService,
        JdjCandidateValidationService,
        MultiCandidateRobustnessService,
        JdjActive60RobustnessService,
    ):
        monkeypatch.setattr(target, "__init__", forbidden)

    protocol = load_five_candidate_dossier_protocol()
    verified = tuple(
        verify_json_artifact(ref, PROJECT_ROOT)
        for ref in protocol.source_artifacts
    )

    assert tuple(item.verified_sha256 for item in verified) == tuple(
        ref.expected_sha256 for ref in protocol.source_artifacts
    )


def test_dossier_has_exact_inventory(
    service: FiveCandidateResearchDossierService,
) -> None:
    report = service.run(
        FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
    )

    assert report.schema_version == 1
    assert report.command == (
        "guiyi research candidate-dossier "
        "--protocol five_candidate_research_dossier_v1"
    )
    assert report.status == "ok"
    assert report.candidate_order == CANDIDATES
    assert len(report.candidate_dossiers) == 5
    assert len(report.source_artifacts) == 7
    assert sum(
        item.robustness.matrix_cell_count for item in report.candidate_dossiers
    ) == 300
    assert sum(
        item.robustness.available_symbol_count
        for item in report.candidate_dossiers
    ) == 245
    assert sum(
        item.robustness.unavailable_symbol_count
        for item in report.candidate_dossiers
    ) == 55
    assert report.metric_catalog == ()
    assert report.comparability_pairs == ()


def _horizon(
    sample_count: int,
    metric: str | None,
) -> CandidateHorizonEvidence:
    return CandidateHorizonEvidence(
        sample_count=sample_count,
        numeric_metrics=MappingProxyType(
            {
                "median_directional_return_bps": metric,
                "median_mfe_bps": metric,
                "median_mae_bps": metric,
            }
        ),
    )


def _cross_symbol(**overrides: object) -> CandidateCrossSymbolEvidence:
    values: dict[str, object] = {
        "candidate_id": CANDIDATES[0],
        "symbol": "jm",
        "status": "available",
        "reason_code": None,
        "evaluable_count": 10,
        "event_count": 0,
        "event_rate_per_1000_evaluable": "0",
        "horizon_summary": MappingProxyType(
            {3: _horizon(0, None), 5: _horizon(0, None), 8: _horizon(0, None)}
        ),
        "sector": None,
        "yearly": None,
    }
    values.update(overrides)
    return CandidateCrossSymbolEvidence(**values)  # type: ignore[arg-type]


def test_missingness_contract_preserves_three_distinct_states() -> None:
    unavailable = _cross_symbol(
        status="unavailable",
        reason_code="MULTI_CANDIDATE_SOURCE_UNAVAILABLE",
        evaluable_count=None,
        event_count=None,
        event_rate_per_1000_evaluable=None,
        horizon_summary=None,
    )
    zero_event = _cross_symbol()
    zero_sample = zero_event.horizon_summary[3]

    assert unavailable.reason_code == "MULTI_CANDIDATE_SOURCE_UNAVAILABLE"
    assert unavailable.event_count is None
    assert unavailable.horizon_summary is None
    assert zero_event.status == "available"
    assert zero_event.event_count == 0
    assert zero_sample.sample_count == 0
    assert all(value is None for value in zero_sample.numeric_metrics.values())


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "unavailable", "reason_code": None},
        {
            "status": "unavailable",
            "reason_code": "MULTI_CANDIDATE_SOURCE_UNAVAILABLE",
            "event_count": 0,
            "evaluable_count": None,
            "event_rate_per_1000_evaluable": None,
            "horizon_summary": None,
        },
        {"status": "available", "reason_code": "SOURCE_UNAVAILABLE"},
    ],
)
def test_cross_symbol_evidence_rejects_illegal_missingness_hybrid(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(FiveCandidateDossierReportError) as raised:
        _cross_symbol(**overrides)

    assert str(raised.value) == "FIVE_CANDIDATE_DOSSIER_REPORT_INVALID"


def test_horizon_evidence_rejects_numeric_metrics_for_zero_sample() -> None:
    with pytest.raises(FiveCandidateDossierReportError):
        _horizon(0, "0")


def test_service_projects_verified_json_without_runtime_construction(
    monkeypatch: pytest.MonkeyPatch,
    service: FiveCandidateResearchDossierService,
) -> None:
    from sqlalchemy.orm import Session

    from app.market_data.market_data_service import MarketDataService
    from app.research.jdj.jdj_candidate_validation_service import (
        JdjCandidateValidationService,
    )
    from app.research.n_structure.n_candidate_validation_service import (
        NStructureCandidateValidationService,
    )
    from app.research.robustness.jdj_robustness_service import (
        JdjActive60RobustnessService,
    )
    from app.research.robustness.multi_candidate_robustness_service import (
        MultiCandidateRobustnessService,
    )
    from app.research.subing.subing_candidate_validation_service import (
        SubingCandidateValidationService,
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("runtime constructor invoked")

    for target in (
        Session,
        MarketDataService,
        SubingCandidateValidationService,
        NStructureCandidateValidationService,
        JdjCandidateValidationService,
        MultiCandidateRobustnessService,
        JdjActive60RobustnessService,
    ):
        monkeypatch.setattr(target, "__init__", forbidden)

    report = service.run(
        FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
    )

    assert tuple(
        dossier.identity.candidate_id for dossier in report.candidate_dossiers
    ) == CANDIDATES


def _service_with_mutated_source(
    tmp_path: Path,
    artifact_index: int,
    mutator,
) -> FiveCandidateResearchDossierService:
    protocol = load_five_candidate_dossier_protocol()
    refs = list(protocol.source_artifacts)
    for ref in refs:
        destination = tmp_path / ref.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / ref.path, destination)
    target = tmp_path / refs[artifact_index].path
    payload = json.loads(target.read_text(encoding="utf-8"))
    mutator(payload)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    target.write_bytes(raw)
    refs[artifact_index] = replace(
        refs[artifact_index], expected_sha256=hashlib.sha256(raw).hexdigest()
    )
    object.__setattr__(protocol, "source_artifacts", tuple(refs))
    return FiveCandidateResearchDossierService(protocol, project_root=tmp_path)


@pytest.mark.parametrize(
    ("artifact_index", "mutator"),
    [
        (0, lambda payload: payload.__setitem__("candidate_id", "changed")),
        (0, lambda payload: payload.__setitem__("protocol_id", "changed")),
        (
            0,
            lambda payload: payload["retrospective"].__setitem__(
                "through", "2026-08-17"
            ),
        ),
        (5, lambda payload: payload["cross_symbol_results"].pop()),
        (5, lambda payload: payload["cross_symbol_results"].reverse()),
    ],
    ids=(
        "candidate-id",
        "protocol-id",
        "retrospective-through",
        "cross-symbol-row-count",
        "cross-symbol-row-order",
    ),
)
def test_valid_sha_source_semantic_drift_fails_closed(
    tmp_path: Path,
    artifact_index: int,
    mutator,
) -> None:
    service = _service_with_mutated_source(
        tmp_path,
        artifact_index,
        mutator,
    )

    with pytest.raises(FiveCandidateDossierSourceError) as raised:
        service.run(
            FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
        )

    assert str(raised.value) == "FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID"
