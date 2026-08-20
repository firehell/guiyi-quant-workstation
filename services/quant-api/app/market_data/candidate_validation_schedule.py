from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_FOLD_ID = re.compile(r"fold_(?:0[1-9]|[1-9][0-9])")


class CandidateValidationIdentityError(ValueError):
    code = "CANDIDATE_VALIDATION_IDENTITY_MISMATCH"

    def __init__(self) -> None:
        super().__init__(self.code)


class CandidateValidationWindowError(ValueError):
    code = "CANDIDATE_VALIDATION_WINDOW_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class CandidateValidationSourceError(ValueError):
    code = "CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

    def __post_init__(self) -> None:
        candidate_id = _normalize_identifier(self.candidate_id)
        protocol_id = _normalize_identifier(self.protocol_id)
        symbol = self.symbol.strip().lower() if type(self.symbol) is str else ""
        if (
            candidate_id is None
            or protocol_id is None
            or not symbol
            or not symbol.isascii()
            or not symbol.isalpha()
            or type(self.through) is not date
        ):
            raise ValueError("CANDIDATE_VALIDATION_REQUEST_INVALID")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "protocol_id", protocol_id)
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True, slots=True)
class RollingValidationWindow:
    fold_id: str
    reference_since: date
    reference_through: date
    test_since: date
    test_through: date

    def __post_init__(self) -> None:
        if (
            type(self.fold_id) is not str
            or _FOLD_ID.fullmatch(self.fold_id) is None
            or type(self.reference_since) is not date
            or type(self.reference_through) is not date
            or type(self.test_since) is not date
            or type(self.test_through) is not date
            or self.reference_since.day != 1
            or self.test_since.day != 1
            or self.reference_since > self.reference_through
            or self.reference_through.toordinal() + 1 != self.test_since.toordinal()
            or self.test_since > self.test_through
            or not _is_month_end(self.test_through)
        ):
            raise CandidateValidationWindowError()


def build_rolling_validation_windows(
    *,
    reference_months: int,
    test_months: int,
    step_months: int,
    first_test_since: date,
    last_test_through: date,
) -> tuple[RollingValidationWindow, ...]:
    if (
        type(reference_months) is not int
        or reference_months <= 0
        or type(test_months) is not int
        or test_months <= 0
        or type(step_months) is not int
        or step_months <= 0
        or type(first_test_since) is not date
        or type(last_test_through) is not date
        or first_test_since.day != 1
        or not _is_month_end(last_test_through)
        or first_test_since > last_test_through
    ):
        raise CandidateValidationWindowError()

    windows: list[RollingValidationWindow] = []
    test_since = first_test_since
    index = 1
    try:
        while test_since <= last_test_through:
            test_through = _add_months(test_since, test_months) - timedelta(days=1)
            if test_through > last_test_through:
                raise CandidateValidationWindowError()
            windows.append(
                RollingValidationWindow(
                    fold_id=f"fold_{index:02d}",
                    reference_since=_add_months(test_since, -reference_months),
                    reference_through=test_since - timedelta(days=1),
                    test_since=test_since,
                    test_through=test_through,
                )
            )
            test_since = _add_months(test_since, step_months)
            index += 1
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, CandidateValidationWindowError):
            raise
        raise CandidateValidationWindowError() from exc
    if not windows or windows[-1].test_through != last_test_through:
        raise CandidateValidationWindowError()
    return tuple(windows)


def prospective_window(
    *,
    through: date,
    first_trading_day: date,
) -> tuple[date, date] | None:
    if type(through) is not date or type(first_trading_day) is not date:
        raise CandidateValidationWindowError()
    if through < first_trading_day:
        return None
    return first_trading_day, through


def _normalize_identifier(value: object) -> str | None:
    if type(value) is not str:
        return None
    return value if _IDENTIFIER.fullmatch(value) else None


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + (value.month - 1) + months
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)


def _month_end(value: date) -> date:
    return _add_months(value, 1) - timedelta(days=1)


def _is_month_end(value: date) -> bool:
    try:
        return value == _month_end(value)
    except (OverflowError, ValueError):
        return False
