import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


def module():
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "package", root / "scripts/research/lms405_validation_package.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, root


def test_existing_evidence_reports_gaps_without_fake_match_or_profit(tmp_path):
    m, root = module()
    report = m.build_package(root, datetime(2026, 10, 11, tzinfo=UTC))
    assert report["source_count"] == 58
    assert report["author_complete_lifecycles"] == 0
    assert report["behavior_metrics"]["match_rate"] is None
    assert report["causal"]["status"] == "BLOCKED"
    assert report["causal"]["performance"] is None
    assert report["holdout_count"] == 0
    assert len(report["work_packages"]) == 6
    assert any(r["reason"] == "既有索引" for r in report["failures"])
    assert all(row["effective_at"] == "UNKNOWN" for row in report["observations"])
    m.publish(report, tmp_path / "new")
    assert json.loads((tmp_path / "new/report.json").read_text()) == report
    assert (tmp_path / "new/failures.csv").is_file()
    assert b"\r" not in (tmp_path / "new/failures.csv").read_bytes()
    assert "BLOCKED" in (tmp_path / "new/report.md").read_text()
    with pytest.raises(FileExistsError):
        m.publish(report, tmp_path / "new")


def test_source_conflict_and_bad_identity_fail_before_report(tmp_path):
    m, root = module()
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        m.build_package(missing, datetime(2026, 10, 11, tzinfo=UTC))
