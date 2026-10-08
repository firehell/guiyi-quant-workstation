import json
import subprocess

import pytest

from scripts.newow_p0_numeric import compare_artifacts
from tests.test_newow_v3379_market_oracle import ROOT, execute
from tests.test_newow_v3379_market_oracle import pytestmark as oracle_requirement

pytestmark = oracle_requirement


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    fixture = json.loads(
        (
            ROOT / "services/quant-api/tests/newow/fixtures/v3379-manual-oracle.json"
        ).read_text()
    )
    payload = {
        "frequency": "1d",
        "input_sha256": "a" * 64,
        "code_sha": "b" * 40,
        "product": "fixture-constructed",
        "segments": [
            {
                "owner": case["name"],
                "terminal_eligible": False,
                "bars": [
                    {
                        **row,
                        "trading_day": row["date"],
                        "observation_eligible": index >= 10,
                    }
                    for index, row in enumerate(case["bars"])
                ],
            }
            for case in fixture["cases"]
        ],
    }
    process, input_path, output_path = execute(
        tmp_path_factory.mktemp("raw-numeric"), payload
    )
    assert process.returncode == 0, process.stderr
    return input_path.read_bytes(), output_path.read_bytes()


def test_all_raw_source_complete_objects_match_without_masking(artifacts):
    report = compare_artifacts(*artifacts)
    assert report["status"] == "PASSED"
    assert report["all_raw_source_passed"] is True
    assert report["owner_count"] == 9
    assert all(len(owner["checks"]) == 8 for owner in report["owners"])
    assert report["acceptance_scope"] == "RAW_SOURCE_PARITY_ONLY"
    assert report["futures_adapter_comparison"] == "PENDING"
    assert report["overall_720_acceptance"] == "NOT_ASSESSED"


@pytest.mark.parametrize("field", ["equity", "trade_price"])
def test_changed_raw_curve_or_trade_price_fails_with_scalar_details(artifacts, field):
    input_bytes, raw_bytes = artifacts
    raw = json.loads(raw_bytes)
    source = next(
        item for item in raw["segments"] if item["ordinary"]["oscillation"]["trades"]
    )
    if field == "equity":
        source["ordinary"]["oscillation"]["equity"][0] += 1
    else:
        source["ordinary"]["oscillation"]["trades"][0]["sellPrice"] += 1
    report = compare_artifacts(input_bytes, json.dumps(raw).encode())
    assert report["status"] == "FAILED"
    assert report["all_raw_source_passed"] is False
    failed = [
        check
        for owner in report["owners"]
        for check in owner["checks"]
        if check["status"] == "FAILED"
    ]
    assert len(failed) == 1
    assert failed[0]["difference_count"] >= 1
    assert all(
        not isinstance(detail["expected"], (dict, list))
        and not isinstance(detail["actual"], (dict, list))
        for detail in failed[0]["details"]
    )
    assert (".equity[" if field == "equity" else ".trades[") in failed[0]["details"][0][
        "path"
    ]


def test_source_or_input_identity_drift_fails_before_projection(artifacts):
    input_bytes, raw_bytes = artifacts
    raw = json.loads(raw_bytes)
    raw["source_sha256"]["detail.html"] = "0" * 64
    report = compare_artifacts(input_bytes, json.dumps(raw).encode())
    assert report["reason"] == "P0_NUMERIC_SOURCE_IDENTITY_MISMATCH"
    assert report["owners"] == []
    payload = json.loads(input_bytes)
    payload["product"] = "changed-input"
    report = compare_artifacts(json.dumps(payload).encode(), raw_bytes)
    assert report["reason"] == "P0_NUMERIC_INPUT_BINDING_MISMATCH"


def test_cli_failure_preserves_report_without_printing_numeric_arrays(
    artifacts, tmp_path
):
    import sys

    input_bytes, raw_bytes = artifacts
    raw = json.loads(raw_bytes)
    raw["segments"][0]["ordinary"]["oscillation"]["equity"][0] += 1
    input_path, oracle_path, report_path = (
        tmp_path / name for name in ("input.json", "raw.json", "numeric.json")
    )
    input_path.write_bytes(input_bytes)
    oracle_path.write_text(json.dumps(raw))
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.newow_p0_numeric",
            "--input",
            str(input_path),
            "--oracle",
            str(oracle_path),
            "--output",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 1, process.stderr
    assert json.loads(report_path.read_text())["status"] == "FAILED"
    stdout = json.loads(process.stdout)
    assert set(stdout) == {"status", "acceptance_scope", "owner_count", "output"}


@pytest.fixture(scope="module")
def native_fixture(artifacts):
    input_bytes, raw_bytes = artifacts
    payload, raw = json.loads(input_bytes), json.loads(raw_bytes)
    payload["native_actions"] = {"trend": [], "oscillation": []}
    for index, (segment, source) in enumerate(
        zip(payload["segments"], raw["segments"], strict=True)
    ):
        segment.update(
            physical_contract=f"contract-{index}",
            owner_segment_id=f"owner-{index}",
            calculation_segment_id=f"calc-{index}",
        )
        by_date = {bar["date"]: bar for bar in segment["bars"]}
        for strategy in ("trend", "oscillation"):
            signals = (
                source["chart"]["trend"]["signals"]
                if strategy == "trend"
                else source["chart"]["oscillation"]
            )
            first = True
            for signal in signals:
                date = (
                    segment["bars"][signal["index"]]["date"]
                    if strategy == "trend"
                    else signal["date"]
                )
                bar = by_date[date]
                if not bar["observation_eligible"]:
                    continue
                kind = "BUILD" if signal["type"] == "buy" else "CLEAR"
                eligibility = (
                    "INITIAL_CLEAR_NO_ENTRY"
                    if first and kind == "CLEAR"
                    else "NO_ELIGIBLE_ENTRY"
                    if kind == "CLEAR"
                    else "ELIGIBLE"
                )
                first = False
                payload["native_actions"][strategy].append(
                    {
                        "trading_day": bar["trading_day"],
                        "value": {
                            "kind": kind,
                            "bar_end": date,
                            "physical_contract": segment["physical_contract"],
                            "segment_id": segment["owner_segment_id"],
                            "calculation_segment_id": segment["calculation_segment_id"],
                            "reference_price": str(signal["price"]),
                            "trade_eligibility": eligibility,
                        },
                    }
                )
    return payload, raw


def test_complete_native_signals_include_initial_clear_and_no_eligible(native_fixture):
    from scripts.newow_p0_numeric import compare_native_signals

    report = compare_native_signals(*native_fixture)
    assert report["status"] == "PASSED"
    assert len(report["checks"]) == 18
    assert report["eligibility_counts"]["INITIAL_CLEAR_NO_ENTRY"] > 0
    assert report["eligibility_counts"]["NO_ELIGIBLE_ENTRY"] > 0
    assert report["max_price_delta"] == "0"


@pytest.mark.parametrize("change", ["price", "delete", "date"])
def test_native_price_1e3_missing_marker_and_wrong_date_all_fail(
    native_fixture, change
):
    from copy import deepcopy
    from decimal import Decimal
    from scripts.newow_p0_numeric import compare_native_signals

    payload, raw = deepcopy(native_fixture)
    actions = payload["native_actions"]["trend"]
    if change == "price":
        actions[0]["value"]["reference_price"] = str(
            Decimal(actions[0]["value"]["reference_price"]) + Decimal("0.001")
        )
    elif change == "delete":
        del actions[0]
    else:
        actions[0]["value"]["bar_end"] = "2099-01-01"
    report = compare_native_signals(payload, raw)
    assert report["status"] == "FAILED"
    if change == "price":
        assert Decimal(report["max_price_delta"]) == Decimal("0.001")


def test_only_price_has_documented_representation_tolerance(native_fixture):
    from copy import deepcopy
    from decimal import Decimal
    from scripts.newow_p0_numeric import compare_native_signals

    payload, raw = deepcopy(native_fixture)
    action = payload["native_actions"]["trend"][0]["value"]
    action["reference_price"] = str(
        Decimal(action["reference_price"]) + Decimal("1e-9")
    )
    report = compare_native_signals(payload, raw)
    assert report["status"] == "PASSED"
    assert Decimal(report["max_price_delta"]) == Decimal("1e-9")
    assert Decimal(report["price_tolerance"]) == Decimal("1e-8")
    assert report["date_owner_type_membership"] == "EXACT"


def test_missing_native_signals_not_assessed_and_warmup_only_ignored(
    artifacts, native_fixture
):
    from copy import deepcopy
    from scripts.newow_p0_numeric import compare_native_signals

    assert compare_artifacts(*artifacts)["native_signals"]["status"] == "NOT_ASSESSED"
    payload, raw = deepcopy(native_fixture)
    payload["native_actions"]["trend"].append(
        {"value": {"trade_eligibility": "WARMUP_ONLY"}}
    )
    report = compare_native_signals(payload, raw)
    assert report["status"] == "PASSED"
    assert report["ignored_warmup_only"] == 1


def test_native_comparison_does_not_truncate_after_200_markers():
    from datetime import date, timedelta
    from scripts.newow_p0_numeric import compare_native_signals

    bars, signals, points = [], [], []
    for i in range(251):
        day = (date(2020, 1, 1) + timedelta(days=i)).isoformat()
        kind = "buy" if i % 2 == 0 else "sell"
        bars.append({"date": day, "trading_day": day, "observation_eligible": True})
        signals.append({"date": day, "type": kind, "price": 100})
        points.append(
            {
                "trading_day": day,
                "value": {
                    "kind": "BUILD" if kind == "buy" else "CLEAR",
                    "bar_end": day,
                    "physical_contract": "physical",
                    "segment_id": "segment",
                    "calculation_segment_id": "calculation",
                    "reference_price": "100",
                    "trade_eligibility": "ELIGIBLE",
                },
            }
        )
    payload = {
        "segments": [
            {
                "owner": "owner",
                "physical_contract": "physical",
                "owner_segment_id": "segment",
                "calculation_segment_id": "calculation",
                "bars": bars,
            }
        ],
        "native_actions": {"trend": [], "oscillation": points},
    }
    raw = {"segments": [{"chart": {"trend": {"signals": []}, "oscillation": signals}}]}
    result = compare_native_signals(payload, raw)
    assert result["status"] == "PASSED"
    assert result["checks"][1]["expected_count"] == 251
    del points[230]
    result = compare_native_signals(payload, raw)
    assert result["status"] == "FAILED"
    assert result["checks"][1]["native_count"] == 250
