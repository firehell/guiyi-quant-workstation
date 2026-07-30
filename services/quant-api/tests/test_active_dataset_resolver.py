from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

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
from app.services.active_dataset_resolver import ActiveDatasetResolver


def _legacy_asset_evidence(
    market_data_file_id: int,
    *,
    provider: str = "rqdata",
    quality_status: str = "passed",
    checksum: str | None = None,
) -> dict[str, Any]:
    return {
        "market_data_file_id": market_data_file_id,
        "provider": provider,
        "data_role": "primary",
        "quality_status": quality_status,
        "data_version": f"v{market_data_file_id}",
        "checksum": checksum or f"checksum-{market_data_file_id}",
        "start_time": "2026-01-01T00:00:00",
        "end_time": "2026-01-02T00:00:00",
        "source_interval": "1m",
        "source_interval_basis": "direct",
    }


def _legacy_context(
    *,
    contract: str = "jm.MAIN",
    access_mode: str = "browser",
    assets: list[dict[str, Any]] | None = None,
    profile_lineage: Any = None,
) -> SimpleNamespace:
    evidence = assets if assets is not None else [_legacy_asset_evidence(7)]
    is_continuous = contract == "jm.MAIN"
    lineage = SimpleNamespace(
        access_mode=access_mode,
        strict_research_ready=access_mode == "research",
        profile_id=getattr(profile_lineage, "profile_id", None),
        quality_policy=getattr(profile_lineage, "quality_policy", None),
        market_data_file_id=evidence[0]["market_data_file_id"] if len(evidence) == 1 else None,
        provider=evidence[0]["provider"] if evidence else None,
        data_role=evidence[0]["data_role"] if evidence else None,
        quality_status=evidence[0]["quality_status"] if evidence else "unchecked",
        binding_snapshot=getattr(profile_lineage, "binding_snapshot", None),
        lineage_token="legacy-token",
        view_role="continuous" if is_continuous else "actual_contract",
        continuous_contract="jm.MAIN",
        actual_contract=None if is_continuous else contract,
        asset_evidence=evidence,
    )
    market_files = [
        SimpleNamespace(id=item["market_data_file_id"], row_count=10)
        for item in evidence
    ]
    return SimpleNamespace(
        access_mode=access_mode,
        profile_lineage=profile_lineage,
        market_files=market_files,
        lineage=lineage,
    )


def _mapping_row(**overrides: Any) -> SimpleNamespace:
    values = {
        "id": 11,
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "trade_date": date(2026, 7, 30),
        "provider": "rqdata",
        "rule": "volume_open_interest",
        "rank": 1,
        "data_version": "mapping-v1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
        (
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="1m",
                access_mode="research",
                provider="rqdata",
                live_source_mode=None,
            ),
            "LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED",
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
                live_source_mode="live_1m_sequential_bucket",
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


def test_dataset_descriptor_owns_nested_mapping_inputs() -> None:
    binding_snapshot = {
        "selection": {
            "market_data_file_ids": [7],
            "evidence": {"checksum": "before"},
        }
    }
    mapping_identity = {
        "rank": 1,
        "source": {"versions": ["mapping-v1"]},
    }
    descriptor = replace(
        _descriptor(assets=[]),
        binding_snapshot=binding_snapshot,
        mapping_identity=mapping_identity,
    )

    binding_snapshot["selection"]["market_data_file_ids"].append(8)
    binding_snapshot["selection"]["evidence"]["checksum"] = "after"
    mapping_identity["source"]["versions"].append("mapping-v2")

    assert descriptor.binding_snapshot == {
        "selection": {
            "market_data_file_ids": [7],
            "evidence": {"checksum": "before"},
        }
    }
    assert descriptor.mapping_identity == {
        "rank": 1,
        "source": {"versions": ["mapping-v1"]},
    }
    assert type(descriptor.binding_snapshot) is dict
    assert type(descriptor.mapping_identity) is dict


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


def test_bars_result_owns_nested_bar_and_mapping_inputs() -> None:
    bar = {
        "datetime": "2026-01-02T00:00:00",
        "metadata": {"revisions": [1]},
    }
    bars = [bar]
    quality = {"status": "passed", "details": {"reasons": []}}
    coverage = {"window": {"bounds": ["2026-01-01", "2026-01-02"]}}
    response_request = {"filters": {"periods": ["15m"]}}
    result = BarsResult(
        descriptor=_descriptor(assets=()),
        bars=bars,
        response_bar_count=1,
        quality=quality,
        coverage=coverage,
        response_request=response_request,
        message=None,
    )

    bars.append({"datetime": "2026-01-03T00:00:00"})
    bar["metadata"]["revisions"].append(2)
    quality["details"]["reasons"].append("changed")
    coverage["window"]["bounds"][0] = "changed"
    response_request["filters"]["periods"].append("30m")

    assert result.bars == (
        {
            "datetime": "2026-01-02T00:00:00",
            "metadata": {"revisions": [1]},
        },
    )
    assert result.quality == {"status": "passed", "details": {"reasons": []}}
    assert result.coverage == {
        "window": {"bounds": ["2026-01-01", "2026-01-02"]}
    }
    assert result.response_request == {"filters": {"periods": ["15m"]}}
    assert type(result.bars[0]) is dict
    assert type(result.quality) is dict
    assert type(result.coverage) is dict
    assert type(result.response_request) is dict


# Task 2 — historical resolver


def test_historical_browser_delegates_once_and_preserves_asset_order_and_lineage_token() -> None:
    calls: list[dict[str, Any]] = []
    context = _legacy_context(
        assets=[
            _legacy_asset_evidence(2, provider="local_parquet", quality_status="warning"),
            _legacy_asset_evidence(1),
        ]
    )

    def resolve_context(session: object, **kwargs: Any) -> SimpleNamespace:
        calls.append({"session": session, **kwargs})
        return context

    session = object()
    resolution = ActiveDatasetResolver(session, resolve_context=resolve_context).resolve_historical(
        DatasetRequest(
            data_context="historical",
            symbol="jm",
            contract_selector="explicit",
            contract="jm.MAIN",
            period="15m",
            access_mode="browser",
            provider=None,
            data_role=None,
            expected_market_data_file_id=None,
            expected_lineage_token="legacy-token",
        )
    )

    assert calls == [
        {
            "session": session,
            "symbol": "jm",
            "contract": "jm.MAIN",
            "period": "15m",
            "provider": None,
            "data_role": None,
            "profile_id": None,
            "access_mode": "browser",
            "expected_market_data_file_id": None,
            "expected_lineage_token": "legacy-token",
        }
    ]
    assert resolution.context is context
    assert resolution.descriptor.lineage_token == "legacy-token"
    assert [asset.market_data_file_id for asset in resolution.descriptor.assets] == [2, 1]
    assert resolution.descriptor.quality_status == "warning"
    assert resolution.descriptor.contract_role == "continuous"
    assert resolution.descriptor.actual_contract is None


def test_historical_forwards_non_null_legacy_identity_guards() -> None:
    calls: list[dict[str, Any]] = []
    context = _legacy_context()

    def resolve_context(session: object, **kwargs: Any) -> SimpleNamespace:
        calls.append({"session": session, **kwargs})
        return context

    session = object()
    ActiveDatasetResolver(session, resolve_context=resolve_context).resolve_historical(
        DatasetRequest(
            data_context="historical",
            symbol="jm",
            contract_selector="explicit",
            contract="jm.MAIN",
            period="15m",
            access_mode="browser",
            provider="rqdata",
            data_role="primary",
            expected_market_data_file_id=7,
            expected_lineage_token="legacy-token",
        )
    )

    assert calls == [
        {
            "session": session,
            "symbol": "jm",
            "contract": "jm.MAIN",
            "period": "15m",
            "provider": "rqdata",
            "data_role": "primary",
            "profile_id": None,
            "access_mode": "browser",
            "expected_market_data_file_id": 7,
            "expected_lineage_token": "legacy-token",
        }
    ]


def test_profile_binding_with_pinned_id_rejects_a_different_legacy_selected_file() -> None:
    profile_lineage = SimpleNamespace(
        profile_id="intraday_research_v1",
        quality_policy="passed_only",
        binding_snapshot={
            "market_data_file_id": 8,
            "data_version": "v7",
        },
    )
    context = _legacy_context(
        contract="JM2609",
        access_mode="research",
        profile_lineage=profile_lineage,
    )

    with pytest.raises(ActiveDatasetDomainError) as raised:
        ActiveDatasetResolver(
            object(),
            resolve_context=lambda _session, **_kwargs: context,
        ).resolve_historical(
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="15m",
                access_mode="research",
                profile_id="intraday_research_v1",
            )
        )

    assert raised.value.code == "DATASET_LINEAGE_CHANGED"


@pytest.mark.parametrize(
    ("candidate_ids", "expected_code"),
    [
        ([], "DATASET_ASSET_MISSING"),
        ([7], None),
        ([8], "DATASET_LINEAGE_CHANGED"),
        ([7, 8], "DATASET_ASSET_AMBIGUOUS"),
    ],
)
def test_legacy_profile_binding_fallback_requires_one_matching_candidate(
    candidate_ids: list[int],
    expected_code: str | None,
) -> None:
    profile_lineage = SimpleNamespace(
        profile_id="intraday_research_v1",
        quality_policy="passed_only",
        binding_snapshot={
            "market_data_file_id": None,
            "data_version": "v7",
        },
    )
    context = _legacy_context(
        contract="JM2609",
        access_mode="research",
        profile_lineage=profile_lineage,
    )
    fallback_calls: list[dict[str, Any]] = []

    def load_candidates(session: object, **kwargs: Any) -> list[SimpleNamespace]:
        fallback_calls.append({"session": session, **kwargs})
        return [SimpleNamespace(id=candidate_id) for candidate_id in candidate_ids]

    session = object()
    resolver = ActiveDatasetResolver(
        session,
        resolve_context=lambda _session, **_kwargs: context,
        fallback_candidates_loader=load_candidates,
    )
    request = DatasetRequest(
        data_context="historical",
        symbol="jm",
        contract_selector="explicit",
        contract="JM2609",
        period="15m",
        access_mode="research",
        profile_id="intraday_research_v1",
    )

    if expected_code is None:
        assert resolver.resolve_historical(request).descriptor.assets[0].market_data_file_id == 7
    else:
        with pytest.raises(ActiveDatasetDomainError) as raised:
            resolver.resolve_historical(request)
        assert raised.value.code == expected_code

    assert fallback_calls == [
        {
            "session": session,
            "symbol": "jm",
            "contract": "JM2609",
            "period": "15m",
            "data_version": "v7",
            "data_role": "primary",
        }
    ]


def test_rank1_historical_requires_equal_strict_and_effective_identity_before_legacy_resolution() -> None:
    strict_row = _mapping_row()
    effective_row = _mapping_row()
    mapping_calls: list[tuple[str, object, dict[str, Any]]] = []
    context_calls: list[dict[str, Any]] = []
    context = _legacy_context(contract="JM2609")

    def load_strict(session: object, **kwargs: Any) -> SimpleNamespace:
        mapping_calls.append(("strict", session, kwargs))
        return strict_row

    def load_effective(session: object, **kwargs: Any) -> SimpleNamespace:
        mapping_calls.append(("effective", session, kwargs))
        return effective_row

    def resolve_context(session: object, **kwargs: Any) -> SimpleNamespace:
        context_calls.append({"session": session, **kwargs})
        return context

    session = object()
    resolution = ActiveDatasetResolver(
        session,
        resolve_context=resolve_context,
        strict_mapping_loader=load_strict,
        effective_mapping_loader=load_effective,
    ).resolve_historical(
        DatasetRequest(
            data_context="historical",
            symbol="jm",
            contract_selector="dominant_rank1",
            contract=None,
            period="15m",
            access_mode="browser",
            mapping_date=date(2026, 7, 30),
        )
    )

    assert mapping_calls == [
        (
            "strict",
            session,
            {"instrument_symbol": "jm", "trade_date": date(2026, 7, 30)},
        ),
        (
            "effective",
            session,
            {"instrument_symbol": "jm", "trade_date": date(2026, 7, 30)},
        ),
    ]
    assert len(context_calls) == 1
    assert context_calls[0]["contract"] == "JM2609"
    assert resolution.descriptor.requested_contract is None
    assert resolution.descriptor.resolved_contract == "JM2609"
    assert resolution.descriptor.mapping_identity == {
        "id": 11,
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "trade_date": "2026-07-30",
        "provider": "rqdata",
        "rule": "volume_open_interest",
        "rank": 1,
        "data_version": "mapping-v1",
    }


@pytest.mark.parametrize(
    ("field_name", "effective_value"),
    [
        ("id", 12),
        ("contract_code", "JM2610"),
        ("trade_date", date(2026, 7, 29)),
        ("provider", "local_parquet"),
        ("rule", "open_interest"),
        ("rank", 2),
        ("data_version", "mapping-v2"),
    ],
)
def test_rank1_strict_and_effective_identity_mismatch_fails_before_legacy_context(
    field_name: str,
    effective_value: Any,
) -> None:
    strict_row = _mapping_row()
    effective_row = _mapping_row(**{field_name: effective_value})
    context_calls = 0

    def resolve_context(_session: object, **_kwargs: Any) -> SimpleNamespace:
        nonlocal context_calls
        context_calls += 1
        return _legacy_context(contract="JM2609")

    with pytest.raises(ActiveDatasetDomainError) as raised:
        ActiveDatasetResolver(
            object(),
            resolve_context=resolve_context,
            strict_mapping_loader=lambda _session, **_kwargs: strict_row,
            effective_mapping_loader=lambda _session, **_kwargs: effective_row,
        ).resolve_historical(
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="dominant_rank1",
                contract=None,
                period="15m",
                access_mode="browser",
                mapping_date=date(2026, 7, 30),
            )
        )

    assert raised.value.code == "DATASET_ACTUAL_CONTRACT_MISMATCH"
    assert context_calls == 0


@pytest.mark.parametrize(
    ("strict_row", "effective_row", "requested_contract", "context_contract"),
    [
        (None, _mapping_row(), None, "JM2609"),
        (_mapping_row(), None, None, "JM2609"),
        (_mapping_row(), _mapping_row(), "JM2610", "JM2609"),
        (_mapping_row(), _mapping_row(), None, "JM2610"),
    ],
)
def test_rank1_missing_requested_or_legacy_resolved_contract_mismatch_fails_closed(
    strict_row: SimpleNamespace | None,
    effective_row: SimpleNamespace | None,
    requested_contract: str | None,
    context_contract: str,
) -> None:
    with pytest.raises(ActiveDatasetDomainError) as raised:
        ActiveDatasetResolver(
            object(),
            resolve_context=lambda _session, **_kwargs: _legacy_context(
                contract=context_contract
            ),
            strict_mapping_loader=lambda _session, **_kwargs: strict_row,
            effective_mapping_loader=lambda _session, **_kwargs: effective_row,
        ).resolve_historical(
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="dominant_rank1",
                contract=requested_contract,
                period="15m",
                access_mode="browser",
                mapping_date=date(2026, 7, 30),
            )
        )

    assert raised.value.code == "DATASET_ACTUAL_CONTRACT_MISMATCH"


@pytest.mark.parametrize(
    "legacy_code",
    [
        "ACTUAL_CONTRACT_MAPPING_INVALID",
        "ACTUAL_CONTRACT_MAPPING_CONFLICT",
        "ACTUAL_CONTRACT_MAPPING_DUPLICATE",
    ],
)
def test_rank1_preserves_strict_mapping_error_codes(legacy_code: str) -> None:
    effective_calls = 0

    def load_strict(_session: object, **_kwargs: Any) -> SimpleNamespace:
        raise ValueError(legacy_code)

    def load_effective(_session: object, **_kwargs: Any) -> SimpleNamespace:
        nonlocal effective_calls
        effective_calls += 1
        return _mapping_row()

    with pytest.raises(ValueError, match=f"^{legacy_code}$"):
        ActiveDatasetResolver(
            object(),
            resolve_context=lambda _session, **_kwargs: _legacy_context(
                contract="JM2609"
            ),
            strict_mapping_loader=load_strict,
            effective_mapping_loader=load_effective,
        ).resolve_historical(
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="dominant_rank1",
                contract=None,
                period="15m",
                access_mode="browser",
                mapping_date=date(2026, 7, 30),
            )
        )

    assert effective_calls == 0


def test_explicit_actual_research_preserves_pinned_profile_lineage() -> None:
    binding_snapshot = {
        "market_data_file_id": 7,
        "data_version": "v7",
        "provider": "rqdata",
        "data_role": "primary",
    }
    profile_lineage = SimpleNamespace(
        profile_id="intraday_research_v1",
        quality_policy="passed_only",
        binding_snapshot=binding_snapshot,
    )
    context = _legacy_context(
        contract="JM2609",
        access_mode="research",
        profile_lineage=profile_lineage,
    )

    descriptor = ActiveDatasetResolver(
        object(),
        resolve_context=lambda _session, **_kwargs: context,
    ).resolve_historical(
        DatasetRequest(
            data_context="historical",
            symbol="jm",
            contract_selector="explicit",
            contract="JM2609",
            period="15m",
            access_mode="research",
            profile_id="intraday_research_v1",
        )
    ).descriptor

    assert descriptor.contract_role == "actual_contract"
    assert descriptor.actual_contract == "JM2609"
    assert descriptor.strict_research_ready is True
    assert descriptor.profile_id == "intraday_research_v1"
    assert descriptor.binding_snapshot == binding_snapshot
    assert descriptor.binding_snapshot is not binding_snapshot


def test_continuous_research_preserves_pinned_profile_lineage_and_access_mode() -> None:
    binding_snapshot = {
        "market_data_file_id": 7,
        "data_version": "v7",
    }
    profile_lineage = SimpleNamespace(
        profile_id="intraday_research_v1",
        quality_policy="passed_only",
        binding_snapshot=binding_snapshot,
    )
    context = _legacy_context(
        contract="jm.MAIN",
        access_mode="research",
        profile_lineage=profile_lineage,
    )
    calls: list[dict[str, Any]] = []

    def resolve_context(session: object, **kwargs: Any) -> SimpleNamespace:
        calls.append({"session": session, **kwargs})
        return context

    descriptor = ActiveDatasetResolver(
        object(),
        resolve_context=resolve_context,
    ).resolve_historical(
        DatasetRequest(
            data_context="historical",
            symbol="jm",
            contract_selector="explicit",
            contract="jm.MAIN",
            period="15m",
            access_mode="research",
            profile_id="intraday_research_v1",
        )
    ).descriptor

    assert len(calls) == 1
    assert calls[0]["access_mode"] == "research"
    assert calls[0]["profile_id"] == "intraday_research_v1"
    assert descriptor.contract_role == "continuous"
    assert descriptor.strict_research_ready is True
    assert descriptor.profile_id == "intraday_research_v1"
    assert descriptor.binding_snapshot == binding_snapshot


def test_rank1_research_preserves_mapping_and_pinned_profile_lineage() -> None:
    binding_snapshot = {
        "market_data_file_id": 7,
        "data_version": "v7",
    }
    profile_lineage = SimpleNamespace(
        profile_id="intraday_research_v1",
        quality_policy="passed_only",
        binding_snapshot=binding_snapshot,
    )
    context = _legacy_context(
        contract="JM2609",
        access_mode="research",
        profile_lineage=profile_lineage,
    )
    calls: list[dict[str, Any]] = []

    def resolve_context(session: object, **kwargs: Any) -> SimpleNamespace:
        calls.append({"session": session, **kwargs})
        return context

    descriptor = ActiveDatasetResolver(
        object(),
        resolve_context=resolve_context,
        strict_mapping_loader=lambda _session, **_kwargs: _mapping_row(),
        effective_mapping_loader=lambda _session, **_kwargs: _mapping_row(),
    ).resolve_historical(
        DatasetRequest(
            data_context="historical",
            symbol="jm",
            contract_selector="dominant_rank1",
            contract="JM2609",
            period="15m",
            access_mode="research",
            profile_id="intraday_research_v1",
            mapping_date=date(2026, 7, 30),
        )
    ).descriptor

    assert len(calls) == 1
    assert calls[0]["contract"] == "JM2609"
    assert calls[0]["access_mode"] == "research"
    assert calls[0]["profile_id"] == "intraday_research_v1"
    assert descriptor.resolved_contract == "JM2609"
    assert descriptor.strict_research_ready is True
    assert descriptor.profile_id == "intraday_research_v1"
    assert descriptor.binding_snapshot == binding_snapshot
    assert descriptor.mapping_identity == {
        "id": 11,
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "trade_date": "2026-07-30",
        "provider": "rqdata",
        "rule": "volume_open_interest",
        "rank": 1,
        "data_version": "mapping-v1",
    }


# Task 3 — live read-only descriptor


def test_live_resolver_returns_only_an_unverified_browser_descriptor() -> None:
    descriptor = ActiveDatasetResolver(object()).resolve_live(
        DatasetRequest(
            data_context="live",
            symbol="jm",
            contract_selector="explicit",
            contract="JM2609",
            period="15m",
            access_mode="browser",
            provider="rqdata",
            live_source_mode="live_1m_sequential_bucket",
        )
    )

    assert descriptor.data_context == "live"
    assert descriptor.resolved_contract == "JM2609"
    assert descriptor.contract_role == "actual_contract"
    assert descriptor.continuous_contract == "jm.MAIN"
    assert descriptor.actual_contract == "JM2609"
    assert descriptor.provider == "rqdata"
    assert descriptor.live_source_mode == "live_1m_sequential_bucket"
    assert descriptor.assets == ()
    assert descriptor.strict_research_ready is False
    assert descriptor.lineage_kind == "unavailable"
    assert descriptor.lineage_token is None
    assert descriptor.warnings == ("live_source_identity_unverified",)
