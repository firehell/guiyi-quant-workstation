from pathlib import Path

import pytest

from app.market_data.subing_d1_quality_candidates import CandidatePreparationError
from scripts.reference_p9_d1_quality_prepare import (
    _source_attempt_path_valid, _validate_output_paths, _write_exclusive,
)


def test_candidate_parent_symlink_to_active_root_is_rejected(tmp_path: Path):
    project = tmp_path / "project"
    active = tmp_path / "active"
    (project / "data").mkdir(parents=True)
    (project / "outputs").mkdir()
    active.mkdir()
    (project / "data/canonical-candidates").symlink_to(active, target_is_directory=True)

    with pytest.raises(CandidatePreparationError, match="P9_CANDIDATE_ROOT_INVALID"):
        _validate_output_paths(
            project,
            project / "data/canonical-candidates" / ("a" * 64) / "attempt-001",
            project / "outputs/reference-p9-d1-quality-20260925",
            active,
            "a" * 64,
        )


def test_output_parent_symlink_is_rejected(tmp_path: Path):
    project = tmp_path / "project"
    active = tmp_path / "active"
    (project / "data/canonical-candidates").mkdir(parents=True)
    active.mkdir()
    (project / "outputs").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(CandidatePreparationError, match="P9_OUTPUT_PATH_INVALID"):
        _validate_output_paths(
            project,
            project / "data/canonical-candidates" / ("a" * 64) / "attempt-001",
            project / "outputs/reference-p9-d1-quality-20260925",
            active,
            "a" * 64,
        )


def test_source_attempt_can_be_relocated_to_same_project_evidence_path(tmp_path: Path):
    project = tmp_path / "project"
    attempt_id = "p9-d1-source-20260925-001"
    attempt = project / "outputs/reference-p9-d1-source-20260925" / attempt_id
    attempt.mkdir(parents=True)
    assert _source_attempt_path_valid(project, attempt, attempt_id)
    assert not _source_attempt_path_valid(project, tmp_path / attempt_id, attempt_id)
    assert not _source_attempt_path_valid(project, tmp_path, str(tmp_path))


def test_frozen_output_may_be_reused_only_when_bytes_match(tmp_path: Path):
    path = tmp_path / "plan.json"
    _write_exclusive(path, {"identity": "frozen"})
    _write_exclusive(path, {"identity": "frozen"})
    with pytest.raises(CandidatePreparationError, match="P9_OUTPUT_CONFLICT"):
        _write_exclusive(path, {"identity": "changed"})
