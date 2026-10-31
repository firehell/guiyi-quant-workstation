"""Research-only static artifact contract for the independently versioned candidate."""

import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path("scripts/research/lms_near405_replay.py")


def module():
    spec = importlib.util.spec_from_file_location("near_cli", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_refuses_existing_directory_without_touching_it(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep").write_bytes(b"untouched")
    with pytest.raises(FileExistsError, match="OUTPUT_ALREADY_EXISTS"):
        module().write_report(tmp_path / "missing", out, "0" * 64, [], None)
    assert (out / "keep").read_bytes() == b"untouched"


def test_static_report_escapes_input_and_labels_fixture():
    result = dict(
        version="lms-near405-v1",
        mode="TIMELY_TEST_FIXTURE",
        current_state={},
        summary={},
        evaluations=[{"reason": "<script>evil</script>"}],
        proposals=[],
        decisions=[],
        transitions=[],
        executable=False,
        fill=None,
        performance=None,
    )
    html = module().render_html(result)
    assert "<script>evil</script>" not in html
    assert "&lt;script&gt;evil&lt;/script&gt;" in html
    assert "TEST_FIXTURE" in html and "人工" in html
    assert "收益" in html and "null" in html


def test_bad_snapshot_hash_cannot_create_success_report(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("bad")
    out = tmp_path / "new"
    with pytest.raises(ValueError, match="SNAPSHOT_HASH_MISMATCH"):
        module().write_report(source, out, "0" * 64, [], None)
    assert not out.exists()


def test_supplied_provenance_cannot_claim_other_snapshot():
    with pytest.raises(ValueError, match="PROVENANCE_SNAPSHOT_MISMATCH"):
        module().validate_provenance([], "a" * 64, {"csv_sha256": "b" * 64})


def test_real_frozen_manual_report_keeps_proposals_without_applying(tmp_path):
    source = Path(
        "output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv"
    )
    result = module().write_report(
        source,
        tmp_path / "a",
        "71c668cc3874cfdcb1c52b47c26615a89ed455977bfb5c80883a9e18b3cb91b3",
        [],
        None,
    )
    assert result["summary"]["transition_count"] == 0
    assert result["summary"]["human_decision_count"] == 0
    assert result["summary"]["environment_counts"]["WARMUP"] == 7
    assert result["summary"]["proposal_count"] > 0
    assert (tmp_path / "a/COMPLETE").exists() and not (
        tmp_path / "a/INCOMPLETE"
    ).exists()


def test_missing_authoritative_session_bar_fails_closed():
    from datetime import datetime, UTC
    from guiyi_quant.lms405 import Bar
    from decimal import Decimal as D

    # Known Session requires two 5m ends; supplying one is not a shorter window.
    p = dict(
        csv_sha256="a" * 64,
        request_identity=dict(contract="JM2509", frequency="5m"),
        sessions={
            "2025-01-01": [
                dict(start="2025-01-01T00:00:00+00:00", end="2025-01-01T00:10:00+00:00")
            ]
        },
    )
    b = Bar(
        "JM2509",
        datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
        D(1),
        D(2),
        D(1),
        D(2),
        start=datetime(2025, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="PROVENANCE_SESSION_COVERAGE_MISMATCH"):
        module().validate_provenance([b], "a" * 64, p)
