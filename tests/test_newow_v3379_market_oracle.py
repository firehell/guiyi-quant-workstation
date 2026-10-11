"""Node executes frozen public functions; no Catalog/database calls."""

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "services/quant-api/tests/newow/fixtures/v3379-manual-oracle.json"
SOURCE = Path(
    os.environ.get(
        "NEWOW_V3379_PUBLIC_SOURCE",
        "/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-manual-v3379-20261008/public-source",
    )
)
TOOL = ROOT / "tools/newow_v3379_market_oracle.mjs"
pytestmark = pytest.mark.skipif(
    not (SOURCE / "detail.html").is_file() or not shutil.which("node"),
    reason="inspected fixed public source and Node required",
)


def execute(tmp_path, payload, source=SOURCE, output="oracle.json"):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload))
    output_path = tmp_path / output
    process = subprocess.run(
        ["node", str(TOOL), str(source), str(input_path), str(output_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return process, input_path, output_path


@pytest.fixture(scope="module")
def oracle(tmp_path_factory):
    frozen = json.loads(FIXTURE.read_text())
    payload = {
        "frequency": "1d",
        "input_sha256": "caller-bound-input",
        "responses": {"trend": "deliberately unusable; never source facts"},
        "segments": [
            {
                "owner": c["name"],
                "terminal_eligible": True,
                "bars": [
                    {**b, "trading_day": b["date"], "observation_eligible": True}
                    for b in c["bars"]
                ],
            }
            for c in frozen["cases"]
        ],
    }
    process, input_path, output_path = execute(
        tmp_path_factory.mktemp("market-oracle"), payload
    )
    assert process.returncode == 0, process.stderr
    return frozen, json.loads(output_path.read_text()), input_path.read_bytes()


def test_all_frozen_full_ordinary_ideal_chart_objects(oracle):
    frozen, result, _ = oracle
    assert result["source_sha256"] == frozen["source_sha256"]
    assert (
        result["extracted_declarations_sha256"]
        == frozen["extracted_declarations_sha256"]
    )
    for case, actual in zip(frozen["cases"], result["segments"], strict=True):
        for mode in ("ordinary", "ideal"):
            for strategy in ("trend", "oscillation", "main_rise"):
                assert actual[mode][strategy] == case[mode][strategy]
        assert [
            {k: s[k] for k in ("date", "type", "price")}
            for s in actual["chart"]["oscillation"]
        ] == case["chart"]
        for strategy in ("trend", "main_rise"):
            assert {k: actual["chart"][strategy][k] for k in case[strategy]} == case[
                strategy
            ]


def test_input_binding_and_independent_fusion_priority(oracle):
    _, result, input_bytes = oracle
    assert result["input_bytes_sha256"] == sha256(input_bytes).hexdigest()
    assert result["input_sha256"] == "caller-bound-input"
    assert result["semantics"]["futures_aggregate"] is False
    for segment in result["segments"]:
        fusion = segment["chart"]["fusion"]
        osc_count = len(segment["chart"]["oscillation"])
        assert all(s["st"] == "osc" for s in fusion[:osc_count])
        assert all(s["st"] == "trend" for s in fusion[osc_count:])
        assert [
            {k: s[k] for k in ("date", "type", "price")} for s in fusion[:osc_count]
        ] == [
            {k: s[k] for k in ("date", "type", "price")}
            for s in segment["chart"]["oscillation"]
        ]
        assert len(fusion) == osc_count + len(segment["chart"]["trend"]["signals"])


def test_raw_keeps_warm_prefix_and_source_forceclose_even_if_ineligible(tmp_path):
    frozen = json.loads(FIXTURE.read_text())
    case = next(c for c in frozen["cases"] if c["name"] == "oscillation-same-bar")
    bars = [
        {**b, "trading_day": b["date"], "observation_eligible": i >= 10}
        for i, b in enumerate(case["bars"])
    ]
    process, _, output = execute(
        tmp_path,
        {
            "frequency": "1d",
            "segments": [{"owner": "owner", "bars": bars, "terminal_eligible": False}],
        },
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(output.read_text())["segments"][0]
    assert result["ordinary"]["oscillation"] == case["ordinary"]["oscillation"]
    assert result["ordinary"]["oscillation"]["trades"][-1]["forceClose"] is True
    assert result["adapter_boundary"]["warmup_bar_count"] == 10
    assert result["adapter_boundary"]["terminal_eligible"] is False
    assert result["bar_count"] == len(bars)


def test_source_identity_mismatch_cannot_create_result(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    # Fail the first identity check; no alternate source or partial result.
    (source / "detail.html").write_text("tampered source")
    process, _, output = execute(tmp_path, {"frequency": "1d", "segments": []}, source)
    assert process.returncode != 0
    assert "NEWOW_ORACLE_SOURCE_IDENTITY_MISMATCH" in process.stderr
    assert not output.exists()


def test_existing_result_is_never_overwritten(tmp_path):
    result = tmp_path / "oracle.json"
    result.write_text("preserved evidence")
    process, _, _ = execute(tmp_path, {"frequency": "1d", "segments": []})
    assert process.returncode != 0
    assert result.read_text() == "preserved evidence"
