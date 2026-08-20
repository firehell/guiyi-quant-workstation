from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from app.market_data.candidate_validation_schedule import (
    CandidateValidationIdentityError,
    CandidateValidationRequest,
    CandidateValidationSourceError,
    CandidateValidationWindowError,
    RollingValidationWindow,
    build_rolling_validation_windows,
    prospective_window,
)


def test_request_preserves_existing_normalization_and_is_immutable() -> None:
    request = CandidateValidationRequest(
        candidate_id="candidate-v1",
        protocol_id="protocol_v1",
        symbol=" JM ",
        through=date(2026, 8, 19),
    )

    assert request == CandidateValidationRequest(
        candidate_id="candidate-v1",
        protocol_id="protocol_v1",
        symbol="jm",
        through=date(2026, 8, 19),
    )
    with pytest.raises(FrozenInstanceError):
        request.symbol = "ag"  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    (
        {"candidate_id": 1},
        {"protocol_id": True},
        {"symbol": b"jm"},
        {"through": datetime(2026, 8, 19)},
    ),
)
def test_request_rejects_non_exact_input_types(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "candidate_id": "candidate",
        "protocol_id": "protocol",
        "symbol": "jm",
        "through": date(2026, 8, 19),
    }
    values.update(changes)

    with pytest.raises(ValueError, match="^CANDIDATE_VALIDATION_REQUEST_INVALID$"):
        CandidateValidationRequest(**values)  # type: ignore[arg-type]


def test_shared_errors_keep_existing_codes_and_messages() -> None:
    errors = (
        (
            CandidateValidationIdentityError,
            "CANDIDATE_VALIDATION_IDENTITY_MISMATCH",
        ),
        (CandidateValidationWindowError, "CANDIDATE_VALIDATION_WINDOW_INVALID"),
        (
            CandidateValidationSourceError,
            "CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE",
        ),
    )

    for error_type, code in errors:
        error = error_type()
        assert error.code == code
        assert str(error) == code


def test_builds_exact_ten_12_3_3_rolling_windows() -> None:
    windows = build_rolling_validation_windows(
        reference_months=12,
        test_months=3,
        step_months=3,
        first_test_since=date(2024, 1, 1),
        last_test_through=date(2026, 6, 30),
    )

    expected_tests = (
        (date(2024, 1, 1), date(2024, 3, 31)),
        (date(2024, 4, 1), date(2024, 6, 30)),
        (date(2024, 7, 1), date(2024, 9, 30)),
        (date(2024, 10, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 3, 31)),
        (date(2025, 4, 1), date(2025, 6, 30)),
        (date(2025, 7, 1), date(2025, 9, 30)),
        (date(2025, 10, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 3, 31)),
        (date(2026, 4, 1), date(2026, 6, 30)),
    )
    assert len(windows) == 10
    assert tuple(window.fold_id for window in windows) == tuple(
        f"fold_{index:02d}" for index in range(1, 11)
    )
    for window, (test_since, test_through) in zip(windows, expected_tests, strict=True):
        assert window.reference_since == date(test_since.year - 1, test_since.month, 1)
        assert window.reference_through == date.fromordinal(test_since.toordinal() - 1)
        assert window.test_since == test_since
        assert window.test_through == test_through


@pytest.mark.parametrize(
    "changes",
    (
        {"reference_months": True},
        {"test_months": 0},
        {"step_months": -1},
        {"first_test_since": datetime(2024, 1, 1)},
        {"first_test_since": date(2024, 1, 2)},
        {"last_test_through": date(2026, 6, 29)},
        {"last_test_through": date(2023, 12, 31)},
        {"last_test_through": date.max},
    ),
)
def test_rolling_schedule_rejects_invalid_types_and_month_boundaries(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "reference_months": 12,
        "test_months": 3,
        "step_months": 3,
        "first_test_since": date(2024, 1, 1),
        "last_test_through": date(2026, 6, 30),
    }
    values.update(changes)

    with pytest.raises(
        CandidateValidationWindowError,
        match="^CANDIDATE_VALIDATION_WINDOW_INVALID$",
    ):
        build_rolling_validation_windows(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"fold_id": "fold_1"},
        {"fold_id": "fold_00"},
        {"reference_since": datetime(2023, 1, 1)},
        {"reference_since": date(2023, 1, 2)},
        {"reference_through": date(2024, 1, 1)},
        {"test_since": date(2024, 1, 2)},
        {"test_through": date(2024, 3, 30)},
        {"test_through": date.max},
    ),
)
def test_rolling_window_rejects_invalid_fold_identity_and_dates(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "fold_id": "fold_01",
        "reference_since": date(2023, 1, 1),
        "reference_through": date(2023, 12, 31),
        "test_since": date(2024, 1, 1),
        "test_through": date(2024, 3, 31),
    }
    values.update(changes)

    with pytest.raises(
        CandidateValidationWindowError,
        match="^CANDIDATE_VALIDATION_WINDOW_INVALID$",
    ):
        RollingValidationWindow(**values)  # type: ignore[arg-type]


def test_prospective_window_is_pending_before_first_day_and_bounded_after_it() -> None:
    first_day = date(2026, 8, 20)

    assert (
        prospective_window(through=date(2026, 8, 19), first_trading_day=first_day)
        is None
    )
    assert prospective_window(through=first_day, first_trading_day=first_day) == (
        first_day,
        first_day,
    )
    assert prospective_window(
        through=date(2026, 8, 22), first_trading_day=first_day
    ) == (first_day, date(2026, 8, 22))


@pytest.mark.parametrize(
    ("through", "first_trading_day"),
    (
        (datetime(2026, 8, 19), date(2026, 8, 20)),
        (date(2026, 8, 19), datetime(2026, 8, 20)),
    ),
)
def test_prospective_window_rejects_non_exact_dates(
    through: object,
    first_trading_day: object,
) -> None:
    with pytest.raises(
        CandidateValidationWindowError,
        match="^CANDIDATE_VALIDATION_WINDOW_INVALID$",
    ):
        prospective_window(  # type: ignore[arg-type]
            through=through,
            first_trading_day=first_trading_day,
        )
