"""Offline file/UI contract; fixture decisions never count as human operations."""

import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path("scripts/research/lms_confirmed_replay.py")


def module():
    spec = importlib.util.spec_from_file_location("confirmed_cli", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_snapshot_requires_exact_hash(tmp_path):
    source = tmp_path / "bars.csv"
    source.write_text("bad")
    with pytest.raises(ValueError, match="SNAPSHOT_HASH_MISMATCH"):
        module().read_bars(source, "0" * 64)


def test_output_refuses_existing_directory_before_reading_input(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep"
    marker.write_bytes(b"unchanged")
    with pytest.raises(FileExistsError, match="OUTPUT_ALREADY_EXISTS"):
        module().write_report(tmp_path / "missing", output, "0" * 64, {}, [], None)
    assert marker.read_bytes() == b"unchanged"


def test_ui_drafts_do_not_claim_application():
    result = dict(
        version="test",
        proposals=[],
        decisions=[],
        transitions=[],
        current_state={},
        evaluations=[],
        executable=False,
    )
    html = module().render_html(result, [], [])
    assert "导出决定草稿" in html
    assert "仅 CLI 验证重算后生效" in html
    assert "TEST_FIXTURE" in html
    assert "回看模式" in html
    assert "recorded_at" in html
    assert "textContent" in html


def test_real_frozen_snapshot_zero_confirmation_and_stable_output(tmp_path):
    import hashlib

    source = Path(
        "output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv"
    )
    initial = dict(
        position=dict(contract="JM2509", long="1", short="0"),
        original_side="LONG",
        since="2025-07-01T00:00:00+08:00",
        known_at="2025-07-01T00:00:00+08:00",
    )
    c = module()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    a, b = tmp_path / "a", tmp_path / "b"
    r = c.write_report(source, a, digest, initial, [], None)
    c.write_report(source, b, digest, initial, [], None)
    assert len(c.read_bars(source, digest)) == 138
    assert r["transitions"] == [] and r["decisions"] == []
    assert r["current_state"] == initial
    assert (a / "state-timeline.json").exists()
    assert r["summary"]["human_decision_count"] == 0
    assert (a / "COMPLETE").exists() and not (a / "INCOMPLETE").exists()
    assert {p.name: p.read_bytes() for p in a.iterdir()} == {
        p.name: p.read_bytes() for p in b.iterdir()
    }


def test_ui_exports_trusted_prefix_records_with_drafts():
    html = module().render_html(dict(checkpoint=dict(decision_records=[])), [], [])
    assert "prefix.checkpoint.decision_records" in html
    assert "exportRecords" in html


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("completed", "false", "COMPLETED_INPUT_REQUIRED"),
        ("start", "2025-07-18T21:04:00+08:00", "FIVE_MINUTE_INPUT_REQUIRED"),
    ],
)
def test_explicit_bar_contract_fields_are_validated(tmp_path, field, value, error):
    import hashlib

    source = tmp_path / "bar.csv"
    source.write_text(
        "contract,frequency,bar_end_shanghai,open,high,low,close,"
        + field
        + "\nJM2509,5m,2025-07-18T21:05:00+08:00,2,3,1,2,"
        + value
        + "\n"
    )
    with pytest.raises(ValueError, match=error):
        module().read_bars(source, hashlib.sha256(source.read_bytes()).hexdigest())
