import importlib.util
import json
from pathlib import Path

import pytest


def module():
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("matrix_report", root / "scripts/research/jm_causal_matrix_report.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture_matrix(tmp_path):
    report = module()
    end = "2026-10-09T07:00:00+00:00"
    window = {"owner_continuity": {"unique_contracts": True, "nonoverlapping_trading_day_coverage": True,
              "status": "PASS", "owners": [{"contract": "JM2701"}]},
              "execution_1m": {"first_bar_end": "2025-10-10T13:01:00+00:00", "last_bar_end": end, "bar_count": 82305},
              "frequencies": {f: {"input_sha256": f} for f in report.FREQUENCIES}}
    (tmp_path / "input-window-readback.json").write_text(json.dumps(window))
    for frequency in report.FREQUENCIES:
        for strategy in report.STRATEGIES:
            row = {"frequency": frequency, "strategy": strategy, "scenario": "baseline",
                "signal_input_hash": frequency, "execution_input_hash": "same-1m", "facts_hash": "same-fees",
                "started_at": "2025-10-10T13:00:00+00:00", "planned_through": end, "processed_through": end,
                "execution_bar_count": 82305, "scope": "continuous_year", "status": "COMPLETE",
                "annual_eligible": True, "account_return_pct": "1", "owner_diagnostics": [{"physical_contract": "JM2701"}]}
            (tmp_path / f"{frequency}-{strategy}-baseline.json").write_text(json.dumps(row))
    return report


@pytest.mark.parametrize("field,value,code", [
    ("processed_through", "2026-01-01T07:00:00+00:00", "MATRIX_INCOMPLETE_YEAR_RANKED"),
    ("facts_hash", "other-fees", "MATRIX_MIXED_EXECUTION_FACTS"),
    ("signal_input_hash", "other-source", "MATRIX_CELL_IDENTITY_MISMATCH"),
])
def test_report_rejects_mixed_or_truncated_evidence(tmp_path, field, value, code):
    report = fixture_matrix(tmp_path)
    path = tmp_path / "5m-trend-baseline.json"
    row = json.loads(path.read_text())
    row[field] = value
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match=code):
        report.collect(tmp_path)


def test_report_excludes_partial_high_return_and_marks_unrun_stress(tmp_path):
    report = fixture_matrix(tmp_path)
    path = tmp_path / "5m-trend-baseline.json"
    row = json.loads(path.read_text())
    row.update(annual_eligible=False, status="PAPER_ROLLOVER_INTERRUPTED", account_return_pct="1000")
    path.write_text(json.dumps(row))
    _, cells, ranking = report.collect(tmp_path)
    assert len(cells) == 42 and len(ranking) == 41
    assert all(r["account_return_pct"] == "1" for r in ranking)
    assert ranking[0]["stress"]["double_slippage"]["status"] == "NOT_RUN"


@pytest.mark.parametrize("field,value,code", [
    ("scenario", "baseline", "MATRIX_STRESS_IDENTITY_MISMATCH"),
    ("processed_through", "2026-01-01T07:00:00+00:00", "MATRIX_INCOMPLETE_STRESS_YEAR_RANKED"),
])
def test_report_rejects_mislabeled_or_partial_stress(tmp_path, field, value, code):
    report = fixture_matrix(tmp_path)
    row = json.loads((tmp_path / "5m-trend-baseline.json").read_text())
    row["scenario"] = "double_commission"
    row[field] = value
    (tmp_path / "5m-trend-double_commission.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match=code):
        report.collect(tmp_path)
