from pathlib import Path

import pytest

from app.market_data.subing_d1_quality_candidates import CandidatePreparationError
from scripts.reference_p9_d1_quality_prepare import _validate_output_paths


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
