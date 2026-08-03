from __future__ import annotations

from datetime import datetime

from app.services.active_dataset import BarsResult, DatasetAsset, DatasetDescriptor
from app.services.core_cli import verify_active_dataset


def _result() -> BarsResult:
    descriptor = DatasetDescriptor(
        data_context="historical",
        access_mode="browser",
        symbol="jm",
        contract_selector="explicit",
        requested_contract="jm.MAIN",
        resolved_contract="jm.MAIN",
        contract_role="continuous",
        continuous_contract="jm.MAIN",
        actual_contract=None,
        period="15m",
        provider="rqdata",
        data_role="primary",
        live_source_mode=None,
        quality_status="passed",
        strict_research_ready=False,
        profile_id=None,
        quality_policy=None,
        binding_snapshot=None,
        assets=(
            DatasetAsset(
                market_data_file_id=7,
                provider="rqdata",
                data_role="primary",
                quality_status="passed",
                data_version="v1",
                checksum="a" * 64,
                coverage_start=datetime(2026, 7, 29),
                coverage_end=datetime(2026, 7, 29, 23, 59),
                source_interval="15m",
                source_interval_basis="direct",
            ),
        ),
        mapping_identity=None,
        coverage_start=datetime(2026, 7, 29),
        coverage_end=datetime(2026, 7, 29, 23, 59),
        source_coverage_row_count=23,
        source_max_bar=datetime(2026, 7, 29, 15),
        source_revision_hash=None,
        lineage_kind="historical_asset",
        lineage_token="lineage-v1:test",
        warnings=(),
    )
    return BarsResult(
        descriptor=descriptor,
        bars=(),
        response_bar_count=23,
        quality={
            "status": "passed",
            "missing_bars": 0,
            "duplicated_bars": 0,
            "abnormal_price_count": 0,
            "abnormal_volume_count": 0,
            "report_count": 1,
        },
        coverage=None,
        response_request={},
        message=None,
    )


def test_verify_active_dataset_delegates_to_facade_and_returns_no_write_contract() -> None:
    observed: dict[str, object] = {}

    class Facade:
        def __init__(self, session) -> None:
            observed["session"] = session

        def get_bars(self, request, **kwargs):
            observed["request"] = request
            observed["read"] = kwargs
            return _result()

    payload = verify_active_dataset(
        object(),
        symbol="jm",
        contract="jm.MAIN",
        period="15m",
        start=datetime(2026, 7, 29),
        end=datetime(2026, 7, 29, 23, 59, 59),
        provider="rqdata",
        profile_id=None,
        access_mode="browser",
        limit=5000,
        service_factory=Facade,
    )

    assert observed["request"].data_context == "historical"
    assert observed["read"] == {
        "start": datetime(2026, 7, 29),
        "end": datetime(2026, 7, 29, 23, 59, 59),
        "limit": 5000,
        "tail": False,
    }
    assert payload["status"] == "passed"
    assert payload["readonly"] is True
    assert payload["effects"] == {
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
    }
    assert payload["result"]["response_bar_count"] == 23
    assert payload["result"]["descriptor"]["assets"][0]["market_data_file_id"] == 7
