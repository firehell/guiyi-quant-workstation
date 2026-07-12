from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_MODULE_PATH = REPO_ROOT / "experiments" / "htdy_indicator" / "golden_sample.py"


def load_golden_module():
    spec = importlib.util.spec_from_file_location("htdy_golden_sample_for_tests", GOLDEN_MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_htdy_fixed_real_golden_sample_passes_visual_oracle_without_step5_authorization(tmp_path: Path) -> None:
    golden = load_golden_module()
    manifest = golden.load_manifest()
    try:
        source = golden.resolve_source_path(manifest)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))

    sample = golden.read_golden_sample(source, manifest)
    bundle_path = tmp_path / "htdy_web_bundle.json"
    result = golden.verify_golden_sample(manifest, sample, export_web_bundle=bundle_path)

    assert result["status"] == "GOLDEN_SAMPLE_PASS_VISUAL_ORACLE"
    assert result["input_sha256"] == "b81abf3ad27b828738de3e6c889dd62f9887b544b6798659c17d289b8d75cc85"
    assert result["row_count"] == 256
    assert result["start_datetime"] == "2026-06-24T22:30:00"
    assert result["end_datetime"] == "2026-07-09T23:00:00"
    assert result["original"]["boolean"]["yellow_candle"]["count"] == 32
    assert result["original"]["boolean"]["white_candle"]["count"] == 19
    assert result["original"]["boolean"]["buy_observation"]["count"] == 5
    assert result["original"]["boolean"]["sell_observation"]["count"] == 3
    assert result["original"]["boolean"]["callback_buy"]["count"] == 13
    assert result["original"]["boolean"]["xg"]["count"] == 1
    assert result["strict"]["boolean"]["yellow_candle"]["count"] == 31
    assert result["strict"]["boolean"]["white_candle"]["count"] == 69
    assert result["strict"]["boolean"]["buy_observation"]["count"] == 5
    assert result["strict"]["boolean"]["sell_observation"]["count"] == 6
    assert result["strict"]["boolean"]["callback_buy"]["count"] == 22
    assert result["strict"]["boolean"]["xg_observation"]["count"] == 2
    assert result["external_oracle_required"] is False
    assert result["oracle_type"] == "visual_screenshot"
    assert result["oracle_numeric_export_provided"] is False
    assert result["step5_authorized"] is False
    assert bundle_path.is_file()


def test_htdy_golden_sample_rejects_wrong_data_version() -> None:
    golden = load_golden_module()
    manifest = golden.load_manifest()
    try:
        source = golden.resolve_source_path(manifest)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    wrong = copy.deepcopy(manifest)
    wrong["source"]["lineage"]["data_version"] = "wrong-version"

    with pytest.raises(ValueError, match="source lineage mismatch for data_version"):
        golden.read_golden_sample(source, wrong)


def test_htdy_golden_sample_rejects_wrong_source_checksum(tmp_path: Path) -> None:
    golden = load_golden_module()
    manifest = golden.load_manifest()
    fake_source = tmp_path / "fake.parquet"
    fake_source.write_bytes(b"not the frozen canonical parquet")

    with pytest.raises(ValueError, match="source file sha256 mismatch"):
        golden.read_golden_sample(fake_source, manifest)


def test_htdy_golden_manifest_keeps_readonly_visual_oracle_gate() -> None:
    golden = load_golden_module()
    manifest = golden.load_manifest()

    assert not Path(manifest["source"]["relative_path"]).is_absolute()
    assert manifest["source"]["lineage"] == {
        "provider": "rqdata",
        "source": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "data_version": "rqdata_jm_standard_15m_20230103_20260710_v2",
        "symbol": "jm",
        "contract": "jm.MAIN",
        "period": "15m",
    }
    assert manifest["comparison"]["numeric_atol"] == 1e-8
    assert manifest["comparison"]["numeric_rtol"] == 1e-10
    assert manifest["policies"]["original"]["channel_period"] == 25
    assert manifest["policies"]["strict"]["xma_replacement_policy"] == "double_trailing_ema"
    assert manifest["policies"]["strict"]["first_finite_index"] == {
        "zk1": 48,
        "zd1": 48,
        "zd2": 72,
        "var23": 11,
    }
    assert manifest["acceptance"]["current_status"] == "GOLDEN_SAMPLE_PASS_VISUAL_ORACLE"
    assert manifest["acceptance"]["external_oracle_required"] is False
    assert manifest["acceptance"]["oracle_type"] == "visual_screenshot"
    assert manifest["acceptance"]["oracle_contract"] == "JM8 焦煤主连"
    assert manifest["acceptance"]["oracle_period"] == "15m"
    assert manifest["acceptance"]["oracle_window_covered"] is True
    assert manifest["acceptance"]["oracle_numeric_export_provided"] is False
    assert manifest["acceptance"]["step5_authorized"] is False
