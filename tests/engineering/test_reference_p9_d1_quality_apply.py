"""P9 publication accepts only its frozen batch and pre-apply backup."""

from pathlib import Path

import pytest

from app.market_data.subing_d1_quality_apply import QualityCandidateApplyError
from scripts.reference_p9_d1_quality_apply import _validate_paths


def test_fixed_p9_paths_and_backup_are_required(tmp_path: Path) -> None:
    root = tmp_path / "project"
    output = root / "outputs/reference-p9-d1-quality-20260925"
    candidate = root / "data/canonical-candidates" / ("a" * 64) / "attempt-001"
    output.mkdir(parents=True)
    candidate.mkdir(parents=True)
    plan = output / "plan.json"
    manifest = output / "manifest.json"
    backup = output / "preapply-pointer-backup-20260925.json"
    for path in (plan, manifest, backup):
        path.write_text("frozen")

    _validate_paths(root, plan, manifest, candidate, backup, "a" * 64)
    with pytest.raises(QualityCandidateApplyError, match="P9_PATH_INVALID"):
        _validate_paths(root, plan, manifest, tmp_path, backup, "a" * 64)
    with pytest.raises(QualityCandidateApplyError, match="P9_PATH_INVALID"):
        _validate_paths(root, plan, manifest, candidate, tmp_path / "other", "a" * 64)
