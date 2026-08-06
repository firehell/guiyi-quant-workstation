from __future__ import annotations

import numpy as np
import pytest

from guiyi_quant.strategies.huotian_dayou_strict import (
    BOOLEAN_FIELDS,
    NUMERIC_FIELDS,
    compute_strict_fields,
)


def _ohlc(length: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    close = np.asarray([100.0 + index * 0.4 + (-1.0 if index % 4 == 0 else 0.5) for index in range(length)])
    open_ = close + np.asarray([0.25 if index % 2 == 0 else -0.3 for index in range(length)])
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    return open_, high, low, close


def test_strict_fields_preserve_declared_fields_and_warmup_nan_boundary() -> None:
    fields = compute_strict_fields(*_ohlc(12), channel_period=3, var23_period=2)

    assert set(fields) == set(NUMERIC_FIELDS) | set(BOOLEAN_FIELDS)
    assert all(len(fields[name]) == 12 for name in fields)
    assert all(fields[name].dtype == np.dtype(bool) for name in BOOLEAN_FIELDS)
    assert all(not fields[name][:4].any() for name in BOOLEAN_FIELDS)
    assert np.isnan(fields["zk1"][:4]).all()
    assert np.isfinite(fields["zk1"][4:]).all()
    assert np.isnan(fields["zd2"][:6]).all()
    assert np.isfinite(fields["zd2"][6:]).all()
    assert np.isnan(fields["var23"][:3]).all()
    assert np.isfinite(fields["var23"][3:]).all()


def test_strict_fields_future_tail_does_not_change_existing_prefix() -> None:
    prefix = _ohlc(18)
    extended = tuple(np.concatenate((values, np.asarray([170.0, 65.0, 160.0]))) for values in prefix)

    before = compute_strict_fields(*prefix, channel_period=4, var23_period=3)
    after = compute_strict_fields(*extended, channel_period=4, var23_period=3)

    for name in NUMERIC_FIELDS:
        np.testing.assert_allclose(before[name], after[name][:18], equal_nan=True)
    for name in BOOLEAN_FIELDS:
        np.testing.assert_array_equal(before[name], after[name][:18])


def test_strict_fields_prefix_append_is_consistent_at_every_step() -> None:
    series = _ohlc(16)
    complete = compute_strict_fields(*series, channel_period=3, var23_period=2)

    for length in range(1, 17):
        prefix = compute_strict_fields(
            *(values[:length] for values in series),
            channel_period=3,
            var23_period=2,
        )
        for name in NUMERIC_FIELDS:
            np.testing.assert_allclose(prefix[name], complete[name][:length], equal_nan=True)
        for name in BOOLEAN_FIELDS:
            np.testing.assert_array_equal(prefix[name], complete[name][:length])


def test_strict_fields_empty_and_short_inputs_return_safe_shapes() -> None:
    empty = compute_strict_fields([], [], [], [], channel_period=3, var23_period=2)
    short = compute_strict_fields(*_ohlc(2), channel_period=3, var23_period=2)

    assert all(fields.size == 0 for fields in empty.values())
    assert all(np.isnan(short[name]).all() for name in NUMERIC_FIELDS)
    assert all(not short[name].any() for name in BOOLEAN_FIELDS)


def test_strict_fields_reject_mismatched_input_lengths() -> None:
    with pytest.raises(ValueError, match="lengths must match"):
        compute_strict_fields([1.0], [2.0, 3.0], [0.0], [1.0])


@pytest.mark.parametrize(
    ("channel_period", "var23_period"),
    [(0, 2), (-1, 2), (3, 0), (3, -1)],
)
def test_strict_fields_reject_non_positive_periods(channel_period: int, var23_period: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        compute_strict_fields(
            *_ohlc(8),
            channel_period=channel_period,
            var23_period=var23_period,
        )
