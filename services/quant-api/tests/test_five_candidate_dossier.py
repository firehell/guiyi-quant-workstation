from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from app.core.env import PROJECT_ROOT
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
    SourceArtifactRef,
    verify_json_artifact,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    FiveCandidateDossierProtocolError,
    FiveCandidateDossierRequest,
    load_five_candidate_dossier_protocol,
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
