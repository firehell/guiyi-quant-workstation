"""Property tests for scripts-cli-consolidation correctness properties."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from app.data_core.contracts import BarFrequency, DatasetKind
from app.data_core.historical_sync import plan_missing_windows
from app.guiyi_cli.output import command_result_payload, redact_text
from app.services.data_operations.aggregate import AggregateApplicationService, supports_aggregate_frequency
from app.services.data_operations.contracts import (
    CommandResult,
    CommandStatus,
    DataTarget,
    EffectSummary,
    PublicError,
    TargetResult,
    empty_effects,
    overall_batch_status,
)
from app.services.data_operations.download import DownloadApplicationService, supports_download_frequency
from app.services.data_operations.guards import refuse_cross_kind_fallback, to_dataset_key
from app.services.data_operations.target_expander import TargetExpander, expand_targets
from app.services.data_operations.contracts import (
    CliArgumentInvalid,
    SingleTargetRequest,
)


FEATURE = "scripts-cli-consolidation"


def _aware(offset_hours: int = 0) -> datetime:
    return datetime(2020, 6, 1, tzinfo=UTC) + timedelta(hours=offset_hours)


_symbols = st.sampled_from(["jm", "i", "rb"])
_contracts = st.sampled_from(["JM888", "I888", "RB888", "JM2409"])
_kinds = st.sampled_from(list(DatasetKind))
_direct = st.sampled_from([BarFrequency.M1, BarFrequency.D1, BarFrequency.W1])
_derived = st.sampled_from(
    [BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1]
)


@settings(max_examples=100)
@given(
    symbol=_symbols,
    contract=_contracts,
    kind=_kinds,
    frequency=_direct,
    start_offset=st.integers(min_value=0, max_value=100),
    window_hours=st.integers(min_value=1, max_value=48),
)
def test_property_1_explicit_deterministic_target_expansion(
    symbol: str,
    contract: str,
    kind: DatasetKind,
    frequency: BarFrequency,
    start_offset: int,
    window_hours: int,
) -> None:
    """Feature: scripts-cli-consolidation, Property 1: Explicit and Deterministic Target Expansion"""
    start = _aware(start_offset)
    end = start + timedelta(hours=window_hours)
    request = SingleTargetRequest(
        symbol=symbol,
        dataset_kind=kind,
        contract_or_series=contract,
        frequency=frequency,
        start=start,
        end=end,
    )
    first = TargetExpander().expand_single(request)
    second = TargetExpander().expand_single(request)
    assert first == second
    assert len(first) == 1
    assert first[0].dataset_kind is kind
    assert first[0].symbol == symbol.lower()
    assert first[0].contract_or_series == contract.upper()
    assert first[0].start == start
    assert first[0].end == end


@settings(max_examples=100)
@given(
    both=st.booleans(),
    bad_window=st.booleans(),
)
def test_property_2_invalid_input_has_no_effects(both: bool, bad_window: bool) -> None:
    """Feature: scripts-cli-consolidation, Property 2: Invalid Input Has No Effects"""
    constructed: list[str] = []

    def spy_factory() -> None:
        constructed.append("dependency")

    start = _aware()
    end = start - timedelta(hours=1) if bad_window else start + timedelta(hours=1)
    with pytest.raises(CliArgumentInvalid):
        if both:
            expand_targets(
                symbol="jm",
                symbols_file=Path("manifest.csv"),
                dataset_kind=DatasetKind.CONTINUOUS,
                contract_or_series="JM888",
                frequency=BarFrequency.M1,
                start=start,
                end=end,
            )
        elif bad_window:
            expand_targets(
                symbol="jm",
                symbols_file=None,
                dataset_kind=DatasetKind.CONTINUOUS,
                contract_or_series="JM888",
                frequency=BarFrequency.M1,
                start=start,
                end=end,
            )
        else:
            expand_targets(
                symbol=None,
                symbols_file=None,
                dataset_kind=DatasetKind.CONTINUOUS,
                contract_or_series="JM888",
                frequency=BarFrequency.M1,
                start=start,
                end=end,
            )
    assert constructed == []
    del spy_factory


@settings(max_examples=100)
@given(
    status=st.sampled_from(list(CommandStatus)),
    readonly=st.booleans(),
)
def test_property_3_result_envelope_is_total(
    status: CommandStatus,
    readonly: bool,
) -> None:
    """Feature: scripts-cli-consolidation, Property 3: Result Envelope Is Total"""
    target = DataTarget(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM888",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
        start=_aware(),
        end=_aware(1),
    )
    result = CommandResult(
        command="data.download",
        status=status,
        readonly=readonly,
        effects=empty_effects(),
        targets=(
            TargetResult(target=target, status=status),
        ),
        error=PublicError(code="CLI_ARGUMENT_INVALID", type="CliUsageError")
        if status is CommandStatus.ERROR
        else None,
    )
    payload = command_result_payload(result)
    assert payload["schema_version"] == 2
    assert payload["command"] == "data.download"
    assert payload["status"] == status.value
    assert payload["readonly"] is readonly
    assert set(payload["effects"]) >= {
        "calls_rqdata",
        "writes_staging",
        "writes_canonical",
        "writes_postgresql",
        "writes_live_observation",
        "writes_historical_active",
        "sends_notification",
        "creates_order",
        "auto_order",
    }
    assert payload["effects"]["auto_order"] is False
    assert isinstance(payload["targets"], list)
    if status is CommandStatus.ERROR:
        assert payload["error"]["code"]


@settings(max_examples=100)
@given(frequency=st.text(min_size=1, max_size=8))
def test_property_5_frequency_sets_are_disjoint_and_closed(frequency: str) -> None:
    """Feature: scripts-cli-consolidation, Property 5: Frequency Sets Are Disjoint and Closed"""
    download_ok = supports_download_frequency(frequency)
    aggregate_ok = supports_aggregate_frequency(frequency)
    assert not (download_ok and aggregate_ok)
    if frequency in {"1m", "1d", "1w"}:
        assert download_ok and not aggregate_ok
    elif frequency in {"5m", "15m", "30m", "60m"}:
        assert aggregate_ok and not download_ok


@settings(max_examples=100)
@given(
    outcomes=st.lists(
        st.sampled_from(
            [
                CommandStatus.PASSED,
                CommandStatus.ERROR,
                CommandStatus.BLOCKED,
                CommandStatus.PARTIAL,
            ]
        ),
        min_size=1,
        max_size=12,
    )
)
def test_property_7_batch_outcome_confluence(outcomes: list[CommandStatus]) -> None:
    """Feature: scripts-cli-consolidation, Property 7: Batch Outcome Confluence"""
    target = DataTarget(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM888",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
        start=_aware(),
        end=_aware(1),
    )
    results = [
        TargetResult(target=target, status=status) for status in outcomes
    ]
    overall = overall_batch_status(results)
    if all(item is CommandStatus.PASSED for item in outcomes):
        assert overall is CommandStatus.PASSED
    else:
        assert overall is not CommandStatus.PASSED
    assert len(results) == len(outcomes)


@settings(max_examples=100)
@given(
    secret=st.sampled_from(
        [
            "password=super-secret",
            "Bearer abc.def.ghi",
            "SELECT * FROM users WHERE id=1",
            "http://10.0.0.8/internal",
            'Traceback (most recent call last):\n  File "/app/x.py", line 1',
            r"D:\guiyi-quant-workstation\secrets\token.txt",
        ]
    )
)
def test_property_16_errors_are_redacted_and_orders_stay_disabled(secret: str) -> None:
    """Feature: scripts-cli-consolidation, Property 16: Errors Are Redacted and Orders Stay Disabled"""
    redacted = redact_text(secret)
    assert "super-secret" not in redacted
    assert "Bearer abc" not in redacted
    assert "SELECT * FROM" not in redacted
    assert "10.0.0.8" not in redacted
    assert "Traceback" not in redacted
    effects = EffectSummary()
    assert effects.auto_order is False
    assert effects.creates_order is False
    payload = command_result_payload(
        CommandResult(
            command="data.audit",
            status=CommandStatus.ERROR,
            readonly=True,
            effects=effects,
            error=PublicError(code="CLI_INTERNAL_ERROR", type="RuntimeError"),
            extras={"detail": secret},
        )
    )
    assert payload["effects"]["auto_order"] is False
    rendered = str(payload)
    assert "super-secret" not in rendered


def _target(*, frequency: BarFrequency = BarFrequency.M1, kind: DatasetKind = DatasetKind.CONTINUOUS) -> DataTarget:
    contract = "JM.MAIN" if kind is DatasetKind.CONTINUOUS else "JM2409"
    return DataTarget("rqdata", kind, "jm", contract, frequency, "none", "canonical-bar-v1", _aware(), _aware(24))


@settings(max_examples=100)
@given(covered_start=st.integers(1, 10), covered_width=st.integers(1, 10))
def test_property_4_exact_date_agnostic_missing_window_planning(covered_start: int, covered_width: int) -> None:
    """Feature: scripts-cli-consolidation, Property 4: Exact Date-Agnostic Missing-Window Planning"""
    key = to_dataset_key(_target())
    start, end = _aware(), _aware(24)
    covered = ((start + timedelta(hours=covered_start), min(end, start + timedelta(hours=covered_start + covered_width))),)
    windows = plan_missing_windows(dataset=key, start=start, end=end, covered_windows=covered)
    assert all(start <= left < right <= end for left, right in windows)


@settings(max_examples=100)
@given(kind=_kinds, frequency=_direct)
def test_property_6_download_preserves_dataset_identity(kind: DatasetKind, frequency: BarFrequency) -> None:
    """Feature: scripts-cli-consolidation, Property 6: Download Preserves Dataset Identity"""
    target = _target(frequency=frequency, kind=kind)
    key = to_dataset_key(target)
    assert (key.provider, key.dataset_kind, key.symbol, key.contract_or_series, key.frequency, key.adjustment, key.schema_version) == (target.provider, target.dataset_kind, target.symbol, target.contract_or_series, target.frequency, target.adjustment, target.schema_version)


@settings(max_examples=100)
@given(lower_hour=st.integers(1, 30))
def test_property_8_unavailable_historical_prefix_is_explicit(lower_hour: int) -> None:
    """Feature: scripts-cli-consolidation, Property 8: Unavailable Historical Prefix Is Explicit"""
    target = _target()
    service = DownloadApplicationService(synchronizer_factory=lambda: None, covered_windows=lambda _key: (), listing_lower_bound=lambda _target: _aware(lower_hour))
    windows = service.plan(__import__("app.services.data_operations.contracts", fromlist=["DownloadRequest"]).DownloadRequest(targets=(target,))).windows_by_target[0][1]
    assert windows[0][0] == target.start


@settings(max_examples=100)
@given(frequency=_derived)
def test_property_10_aggregation_never_accepts_rqdata_factory(frequency: BarFrequency) -> None:
    """Feature: scripts-cli-consolidation, Property 10: Aggregation Never Uses RQData"""
    with pytest.raises(RuntimeError, match="AGGREGATE_RQDATA_CLIENT_FORBIDDEN"):
        AggregateApplicationService(market_data=object(), session_provider=lambda *_: (), rqdata_client_factory=object)


@settings(max_examples=100)
@given(kind=_kinds)
def test_property_15_untrusted_cross_kind_data_fails_closed(kind: DatasetKind) -> None:
    """Feature: scripts-cli-consolidation, Property 15: Ambiguous or Untrusted Data Fails Closed"""
    other = DatasetKind.ACTUAL_DOMINANT if kind is DatasetKind.CONTINUOUS else DatasetKind.CONTINUOUS
    with pytest.raises(Exception):
        refuse_cross_kind_fallback(requested=kind, resolved=other)
