from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import io
import json
from types import MappingProxyType
from types import SimpleNamespace

import pytest

from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.data_parser import CliUsageError
from app.guiyi_cli.research_commands import run_research_command
from app.guiyi_cli.research_requests import build_research_request
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    FiveCandidateDossierRequest,
    load_five_candidate_dossier_protocol,
)
from app.research.candidate_convergence.five_candidate_dossier_service import (
    FiveCandidateResearchDossierService,
)
from app.research.candidate_convergence.five_candidate_relationships import (
    FiveCandidateRelationshipRequest,
    FiveCandidateRelationshipSourceError,
)


def test_candidate_dossier_parser_builds_exact_request() -> None:
    args = build_parser().parse_args(
        [
            "research",
            "candidate-dossier",
            "--protocol",
            "five_candidate_research_dossier_v1",
        ]
    )

    request = build_research_request(args)

    assert request == FiveCandidateDossierRequest("five_candidate_research_dossier_v1")


@pytest.mark.parametrize(
    "extra_arguments",
    (
        ("--since", "2023-01-01"),
        ("--through", "2026-08-20"),
        ("--window", "2023-01-01..2026-08-20"),
        ("--symbol", "jm"),
        ("--candidate", "subing_lifecycle_v2_candidate_v1"),
        ("--products", "jm"),
        ("--threshold", "1"),
        ("--score", "1"),
        ("--rank", "1"),
    ),
)
def test_candidate_dossier_parser_rejects_out_of_contract_flags(
    extra_arguments: tuple[str, str],
) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-dossier",
                "--protocol",
                "five_candidate_research_dossier_v1",
                *extra_arguments,
            ]
        )


def test_candidate_dossier_parser_rejects_unknown_protocol() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-dossier",
                "--protocol",
                "five_candidate_research_dossier_v2",
            ]
        )


def _five_candidate_dossier_report():
    return FiveCandidateResearchDossierService(
        load_five_candidate_dossier_protocol()
    ).run(FiveCandidateDossierRequest("five_candidate_research_dossier_v1"))


class _FakeFiveCandidateDossierService:
    def __init__(self, report=None, error: Exception | None = None) -> None:
        self.report = report
        self.error = error
        self.requests: list[FiveCandidateDossierRequest] = []

    def run(self, request: FiveCandidateDossierRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.report


def test_candidate_dossier_cli_never_enters_session_context() -> None:
    service = _FakeFiveCandidateDossierService(_five_candidate_dossier_report())
    stdout = io.StringIO()
    stderr = io.StringIO()

    def fail_session_factory():
        pytest.fail("candidate-dossier must not construct a Session")

    code = main(
        [
            "research",
            "candidate-dossier",
            "--protocol",
            "five_candidate_research_dossier_v1",
        ],
        session_factory=fail_session_factory,
        candidate_dossier_service_factory=lambda: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert service.requests == [
        FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
    ]
    assert json.loads(stdout.getvalue())["command"] == (
        "guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1"
    )


def _contains_matrix_sized_list(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_matrix_sized_list(item) for item in value.values())
    if isinstance(value, list):
        return len(value) in {60, 120, 180, 300} or any(
            _contains_matrix_sized_list(item) for item in value
        )
    return False


def test_candidate_dossier_payload_is_compact_ordered_and_byte_deterministic() -> None:
    report = _five_candidate_dossier_report()
    first_relationship = dict(
        report.comparability_pairs[0].existing_relationship_reference or {}
    )
    relationships = list(first_relationship["relationships"])
    first_row = dict(relationships[0])
    first_row["signed_distance_median"] = Decimal("-0.000")
    relationships[0] = MappingProxyType(first_row)
    first_relationship["relationships"] = tuple(relationships)
    object.__setattr__(
        report.comparability_pairs[0],
        "existing_relationship_reference",
        MappingProxyType(first_relationship),
    )
    service = _FakeFiveCandidateDossierService(report)
    request = FiveCandidateDossierRequest("five_candidate_research_dossier_v1")

    first = run_research_command(request, service)
    second = run_research_command(request, service)
    first_bytes = json.dumps(first, separators=(",", ":"), ensure_ascii=False)
    second_bytes = json.dumps(second, separators=(",", ":"), ensure_ascii=False)

    assert first_bytes == second_bytes
    assert first["command"] == (
        "guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1"
    )
    assert first["candidate_order"] == list(report.candidate_order)
    assert first["source_artifacts"] == [
        {"artifact_id": artifact.artifact_id} for artifact in report.source_artifacts
    ]
    assert [dossier["candidate_id"] for dossier in first["candidate_dossiers"]] == list(
        report.candidate_order
    )
    assert [
        (pair["left_candidate_id"], pair["right_candidate_id"])
        for pair in first["comparability_pairs"]
    ] == [
        (pair.left_candidate_id, pair.right_candidate_id)
        for pair in report.comparability_pairs
    ]
    assert (
        first["comparability_pairs"][0]["existing_relationship_reference"][
            "relationships"
        ][0]["signed_distance_median"]
        == "0"
    )
    assert not _contains_matrix_sized_list(first)
    assert "expected_sha256" not in first_bytes
    assert '"path"' not in first_bytes


def test_candidate_dossier_payload_preserves_required_non_matrix_evidence() -> None:
    report = _five_candidate_dossier_report()
    payload = run_research_command(
        FiveCandidateDossierRequest("five_candidate_research_dossier_v1"),
        _FakeFiveCandidateDossierService(report),
    )
    dossier = payload["candidate_dossiers"][2]

    assert tuple(dossier) == (
        "candidate_id",
        "identity",
        "baseline",
        "robustness",
        "evidence_references",
    )
    assert tuple(dossier["robustness"]) == (
        "artifact_id",
        "protocol_id",
        "retrospective",
        "matrix_cell_count",
        "available_symbol_count",
        "unavailable_symbol_count",
        "unavailable_reason_counts",
        "zero_event_symbol_count",
        "zero_sample_symbol_count_by_horizon",
        "sector_evidence",
        "yearly_evidence",
        "quality_flags",
    )
    assert len(dossier["robustness"]["sector_evidence"]) == 10
    assert dossier["robustness"]["sector_evidence"][0]["sector"] == ("agriculture")
    assert dossier["robustness"]["sector_evidence"][0]["candidate_id"] == (
        "jdj_trend_follow_1m_candidate_v1"
    )
    assert len(dossier["robustness"]["yearly_evidence"]) == 49
    assert dossier["robustness"]["yearly_evidence"][0]["symbol"] == "a"
    assert (
        dossier["robustness"]["yearly_evidence"][0]["yearly"]["2023"]["event_count"]
        == 1843
    )

    references = dossier["evidence_references"]
    assert tuple(references) == (
        "temporal",
        "cross_symbol",
        "sector",
        "yearly",
        "horizon",
        "quality",
    )
    assert references["temporal"]["window_id"] == "retrospective"
    assert references["temporal"]["evaluable_bar_count"] == 297224
    assert references["cross_symbol"] == {
        "artifact_id": "jdj_active60_robustness_v1",
        "matrix_cell_count": 60,
        "omitted": True,
    }
    assert len(references["sector"]) == 10
    assert len(references["yearly"]) == 49
    assert tuple(references["horizon"]) == ("20", "3", "5", "8")
    assert references["horizon"]["3"] == {
        "median_directional_return_bps": "0",
        "median_mae_bps": "-11.08442675923552062198930752",
        "median_mfe_bps": "9.025270758122743682310469315",
        "sample_count": 7534,
    }
    assert references["quality"] == [
        "PROSPECTIVE_OOS_PENDING",
        "SOURCE_UNAVAILABLE_PRESENT",
        "SHORT_HISTORY_PRESENT",
    ]
    assert not _contains_matrix_sized_list(payload)


def test_candidate_dossier_source_error_is_stable_and_redacted() -> None:
    error = FiveCandidateDossierSourceError()
    error.args = ('/private/tmp/source.json {"source":"secret"} ' + "a" * 64,)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "research",
            "candidate-dossier",
            "--protocol",
            "five_candidate_research_dossier_v1",
        ],
        session_factory=lambda: pytest.fail("Session construction is forbidden"),
        candidate_dossier_service_factory=lambda: _FakeFiveCandidateDossierService(
            error=error
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.candidate-dossier",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID",
            "type": "FiveCandidateDossierSourceError",
        },
    }
    assert "/private/tmp/source.json" not in stderr.getvalue()
    assert '"source":"secret"' not in stderr.getvalue()
    assert "a" * 64 not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_candidate_relationships_parser_builds_exact_request() -> None:
    args = build_parser().parse_args(
        [
            "research",
            "candidate-relationships",
            "--protocol",
            "five_candidate_relationship_topology_v1",
        ]
    )

    assert build_research_request(args) == FiveCandidateRelationshipRequest(
        "five_candidate_relationship_topology_v1"
    )


@pytest.mark.parametrize(
    "extra_arguments",
    (
        ("--since", "2023-01-01"),
        ("--through", "2026-08-20"),
        ("--symbol", "jm"),
        ("--candidate", "jdj_trend_follow_1m_candidate_v1"),
        ("--products", "jm"),
        ("--threshold", "1"),
        ("--score", "1"),
        ("--rank", "1"),
    ),
)
def test_candidate_relationships_parser_rejects_out_of_contract_flags(
    extra_arguments: tuple[str, str],
) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-relationships",
                "--protocol",
                "five_candidate_relationship_topology_v1",
                *extra_arguments,
            ]
        )


def test_candidate_relationships_parser_rejects_unknown_protocol() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-relationships",
                "--protocol",
                "five_candidate_relationship_topology_v2",
            ]
        )


class _CountingSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session
        self.entries = 0

    def __enter__(self) -> object:
        self.entries += 1
        return self.session

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeFiveCandidateRelationshipService:
    def __init__(self, report=None, error: Exception | None = None) -> None:
        self.report = report
        self.error = error
        self.requests: list[FiveCandidateRelationshipRequest] = []

    def run(self, request: FiveCandidateRelationshipRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.report


def _minimal_relationship_report():
    return SimpleNamespace(
        schema_version=1,
        command=(
            "guiyi research candidate-relationships "
            "--protocol five_candidate_relationship_topology_v1"
        ),
        status="ok",
        protocol_id="five_candidate_relationship_topology_v1",
        frozen_at=datetime.fromisoformat("2026-08-22T14:01:54+08:00"),
        research_only=True,
        readonly=True,
        prospective_consumed=False,
        candidate_order=(),
        pair_order=(),
        relationship_catalog=(),
        existing_relationship_references=(),
        n_jdj_dependency_results=(),
        jdj_exact_overlap_results=(),
        quality_flags=(),
        safety={},
    )


def test_candidate_relationships_cli_enters_exactly_one_session_context() -> None:
    session = object()
    context = _CountingSessionContext(session)
    service = _FakeFiveCandidateRelationshipService(_minimal_relationship_report())
    factory_sessions: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    def relationship_factory(received_session: object):
        factory_sessions.append(received_session)
        return service

    code = main(
        [
            "research",
            "candidate-relationships",
            "--protocol",
            "five_candidate_relationship_topology_v1",
        ],
        session_factory=lambda: context,
        candidate_relationship_service_factory=relationship_factory,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert context.entries == 1
    assert factory_sessions == [session]
    assert service.requests == [
        FiveCandidateRelationshipRequest("five_candidate_relationship_topology_v1")
    ]
    assert json.loads(stdout.getvalue())["command"] == (
        "guiyi research candidate-relationships "
        "--protocol five_candidate_relationship_topology_v1"
    )


def test_candidate_relationships_source_error_is_stable_and_redacted() -> None:
    error = FiveCandidateRelationshipSourceError()
    error.args = (
        "/private/tmp/relationship-source.json "
        '{"source":"secret relationship content"} ' + "b" * 64,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "research",
            "candidate-relationships",
            "--protocol",
            "five_candidate_relationship_topology_v1",
        ],
        session_factory=lambda: _CountingSessionContext(object()),
        candidate_relationship_service_factory=lambda _session: (
            _FakeFiveCandidateRelationshipService(error=error)
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.candidate-relationships",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID",
            "type": "FiveCandidateRelationshipSourceError",
        },
    }
    assert "/private/tmp/relationship-source.json" not in stderr.getvalue()
    assert "secret relationship content" not in stderr.getvalue()
    assert "b" * 64 not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
