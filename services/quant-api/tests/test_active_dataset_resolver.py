from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime

import pytest

from app.services.active_dataset import (
    ACTIVE_DATASET_DOMAIN_ERROR_CODES,
    DESCRIPTOR_SNAPSHOT_TOKEN_VERSION,
    ActiveDatasetDomainError,
    BarsResult,
    DatasetAsset,
    DatasetDescriptor,
    DatasetRequest,
    snapshot_token,
    validate_dataset_request,
)


def _asset(market_data_file_id: int) -> DatasetAsset:
    return DatasetAsset(
        market_data_file_id=market_data_file_id,
        provider="rqdata",
        data_role="primary",
        quality_status="passed",
        data_version=f"v{market_data_file_id}",
        checksum=f"checksum-{market_data_file_id}",
        coverage_start=datetime(2026, 1, 1),
        coverage_end=datetime(2026, 1, 2),
        source_interval="1m",
        source_interval_basis="direct",
    )


def _descriptor(*, assets: list[DatasetAsset] | tuple[DatasetAsset, ...]) -> DatasetDescriptor:
    return DatasetDescriptor(
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
        assets=assets,
        mapping_identity=None,
        coverage_start=datetime(2026, 1, 1),
        coverage_end=datetime(2026, 1, 2),
        source_coverage_row_count=2,
        source_max_bar=datetime(2026, 1, 2),
        source_revision_hash="asset-revision",
        lineage_kind="historical_asset",
        lineage_token="legacy-historical-lineage",
        warnings=(),
    )


def test_domain_models_expose_only_contract_fields_and_are_frozen() -> None:
    request_fields = {field.name for field in fields(DatasetRequest)}
    descriptor_fields = {field.name for field in fields(DatasetDescriptor)}
    asset_fields = {field.name for field in fields(DatasetAsset)}

    assert {"file_path", "path", "orm", "password", "secret", "token"}.isdisjoint(request_fields | descriptor_fields | asset_fields)

    request = DatasetRequest(
        data_context="historical",
        symbol="jm",
        contract_selector="explicit",
        contract="jm.MAIN",
        period="15m",
        access_mode="browser",
    )
    with pytest.raises(FrozenInstanceError):
        request.period = "1m"  # type: ignore[misc]


def test_domain_error_codes_are_fixed_to_the_facade_contract() -> None:
    assert ACTIVE_DATASET_DOMAIN_ERROR_CODES == frozenset(
        {
            "DATASET_REQUEST_UNSUPPORTED",
            "DATASET_ASSET_MISSING",
            "DATASET_ASSET_AMBIGUOUS",
            "DATASET_LINEAGE_CHANGED",
            "DATASET_ACTUAL_CONTRACT_MISMATCH",
            "LIVE_ACTUAL_CONTRACT_REQUIRED",
            "LIVE_SOURCE_MODE_REQUIRED",
            "LIVE_SOURCE_MODE_MISMATCH",
            "LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED",
        }
    )


@pytest.mark.parametrize("period", ["1m", "5m", "15m", "30m", "60m", "1d", "1w"])
def test_historical_request_accepts_legacy_periods_and_normalizes_jm_continuous_contract(period: str) -> None:
    normalized = validate_dataset_request(
        DatasetRequest(
            data_context="historical",
            symbol=" JM ",
            contract_selector="explicit",
            contract=" jm.main ",
            period=period,
            access_mode="browser",
        )
    )

    assert normalized.symbol == "jm"
    assert normalized.contract == "jm.MAIN"
    assert normalized.period == period


@pytest.mark.parametrize(
    ("dataset_request", "code"),
    [
        (
            DatasetRequest(
                data_context="historical",
                symbol="rb",
                contract_selector="explicit",
                contract="rb.MAIN",
                period="15m",
                access_mode="browser",
            ),
            "DATASET_REQUEST_UNSUPPORTED",
        ),
        (
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="explicit",
                contract=None,
                period="15m",
                access_mode="browser",
            ),
            "DATASET_REQUEST_UNSUPPORTED",
        ),
        (
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="dominant_rank1",
                contract=None,
                period="15m",
                access_mode="browser",
            ),
            "DATASET_REQUEST_UNSUPPORTED",
        ),
        (
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="dominant_rank1",
                contract="jm.MAIN",
                period="15m",
                access_mode="browser",
                mapping_date=date(2026, 7, 30),
            ),
            "DATASET_ACTUAL_CONTRACT_MISMATCH",
        ),
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="dominant_rank1",
                contract=None,
                period="1m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="poll_get_price_1m",
            ),
            "DATASET_REQUEST_UNSUPPORTED",
        ),
    ],
)
def test_invalid_contract_selector_combinations_fail_with_stable_domain_code(
    dataset_request: DatasetRequest, code: str
) -> None:
    with pytest.raises(ActiveDatasetDomainError) as raised:
        validate_dataset_request(dataset_request)

    assert raised.value.code == code
    assert "/" not in str(raised.value)


@pytest.mark.parametrize(
    ("period", "source_mode"),
    [
        ("1m", "poll_get_price_1m"),
        ("15m", "live_1m_sequential_bucket"),
    ],
)
def test_live_request_accepts_only_actual_jm_contracts_with_required_source_mode(period: str, source_mode: str) -> None:
    normalized = validate_dataset_request(
        DatasetRequest(
            data_context="live",
            symbol="JM",
            contract_selector="explicit",
            contract="jm2609",
            period=period,
            access_mode="browser",
            provider="rqdata",
            live_source_mode=source_mode,
        )
    )

    assert normalized.symbol == "jm"
    assert normalized.contract == "JM2609"
    assert normalized.live_source_mode == source_mode


@pytest.mark.parametrize(
    ("dataset_request", "code"),
    [
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="jm.MAIN",
                period="1m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="poll_get_price_1m",
            ),
            "LIVE_ACTUAL_CONTRACT_REQUIRED",
        ),
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="5m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="poll_get_price_1m",
            ),
            "DATASET_REQUEST_UNSUPPORTED",
        ),
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="1m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode=None,
            ),
            "LIVE_SOURCE_MODE_REQUIRED",
        ),
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="1m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="live_1m_sequential_bucket",
            ),
            "LIVE_SOURCE_MODE_MISMATCH",
        ),
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="1m",
                access_mode="research",
                provider="rqdata",
                live_source_mode="poll_get_price_1m",
            ),
            "LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED",
        ),
    ],
)
def test_invalid_live_combinations_fail_closed(dataset_request: DatasetRequest, code: str) -> None:
    with pytest.raises(ActiveDatasetDomainError) as raised:
        validate_dataset_request(dataset_request)

    assert raised.value.code == code


def test_descriptor_preserves_caller_asset_order_as_an_immutable_tuple() -> None:
    first = _asset(2)
    second = _asset(1)
    descriptor = _descriptor(assets=[first, second])

    assert descriptor.assets == (first, second)
    assert tuple(asset.market_data_file_id for asset in descriptor.assets) == (2, 1)
    with pytest.raises(AttributeError):
        descriptor.assets.append(_asset(3))  # type: ignore[attr-defined]


def test_snapshot_token_is_versioned_deterministic_and_input_sensitive() -> None:
    snapshot = {
        "assets": [{"market_data_file_id": 2, "checksum": "two"}],
        "coverage_end": "2026-01-02T00:00:00",
    }

    first = snapshot_token(snapshot)
    second = snapshot_token(dict(snapshot))
    changed = snapshot_token({**snapshot, "coverage_end": "2026-01-03T00:00:00"})

    assert first == second
    assert first.startswith(f"{DESCRIPTOR_SNAPSHOT_TOKEN_VERSION}:")
    assert changed != first


def test_bars_result_freezes_bars_and_descriptor_warnings() -> None:
    result = BarsResult(
        descriptor=_descriptor(assets=()),
        bars=[{"datetime": "2026-01-02T00:00:00"}],
        response_bar_count=1,
        quality={"status": "passed"},
        coverage=None,
        response_request={"symbol": "jm"},
        message=None,
    )

    assert result.bars == ({"datetime": "2026-01-02T00:00:00"},)
    assert result.descriptor.warnings == ()
