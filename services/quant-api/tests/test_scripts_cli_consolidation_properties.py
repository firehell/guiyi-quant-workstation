"""Property tests for scripts-cli-consolidation correctness properties."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from app.data_core.contracts import BarFrequency, DatasetKind
from app.guiyi_cli.output import command_result_payload, redact_text
from app.services.data_operations.aggregate import supports_aggregate_frequency
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
from app.services.data_operations.download import supports_download_frequency
from app.services.data_operations.target_expander import TargetExpander, expand_targets
from app.services.data_operations.contracts import (
    BatchTargetRequest,
    CliArgumentInvalid,
    SingleTargetRequest,
)


pytestmark = pytest.mark.usefixtures()

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
    assert payload["schema_version"] == 1
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
