"""Immutable, source-backed D1 price-unavailable facts; never substitute Bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Literal, cast

PRICE_UNAVAILABLE_CLASSIFICATION_VERSION = "rqdata-d1-zero-ohl-v1"
NONPOSITIVE_CLOSE_CLASSIFICATION_VERSION = "rqdata-d1-nonpositive-close-v1"


@dataclass(frozen=True, slots=True)
class PriceUnavailableFact:
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    open_interest: Decimal | None
    request_sha256: str
    response_sha256: str
    observed_at: datetime
    classification_version: str = PRICE_UNAVAILABLE_CLASSIFICATION_VERSION

    @property
    def classification(self) -> Literal["PRICE_UNAVAILABLE"]:
        return "PRICE_UNAVAILABLE"

    def __post_init__(self) -> None:
        if self.classification_version != PRICE_UNAVAILABLE_CLASSIFICATION_VERSION:
            raise ValueError("SOURCE_QUALITY_CLASSIFICATION_INVALID")
        for field in ("bar_end", "observed_at"):
            value = getattr(self, field)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("SOURCE_QUALITY_IDENTITY_INVALID")
            object.__setattr__(self, field, value.astimezone(UTC))
        if type(self.trading_day) is not date:
            raise ValueError("SOURCE_QUALITY_IDENTITY_INVALID")
        for digest in (self.request_sha256, self.response_sha256):
            if not isinstance(digest, str) or len(digest) != 64 or any(
                letter not in "0123456789abcdef" for letter in digest
            ):
                raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID")
        required = (self.open, self.high, self.low, self.close, self.volume, self.turnover)
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in required):
            raise ValueError("SOURCE_QUALITY_PRICE_INVALID")
        if (
            self.open != self.high or self.high != self.low or self.low != 0
            or self.close <= 0 or self.volume <= 0 or self.turnover < 0
            or self.open_interest is not None and (
                not isinstance(self.open_interest, Decimal)
                or not self.open_interest.is_finite()
                or self.open_interest < 0
            )
        ):
            raise ValueError("SOURCE_QUALITY_PRICE_INVALID")

    def to_record(self) -> dict[str, str | None]:
        return {
            "bar_end": self.bar_end.isoformat(),
            "trading_day": self.trading_day.isoformat(),
            "open": str(self.open), "high": str(self.high), "low": str(self.low),
            "close": str(self.close), "volume": str(self.volume),
            "turnover": str(self.turnover),
            "open_interest": None if self.open_interest is None else str(self.open_interest),
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "observed_at": self.observed_at.isoformat(),
            "classification_version": self.classification_version,
        }

    @classmethod
    def from_record(cls, record: dict[str, str | None]) -> PriceUnavailableFact:
        try:
            expected = set(cls.__dataclass_fields__)
            if set(record) != expected:
                raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID")
            return cls(
                bar_end=datetime.fromisoformat(record["bar_end"]),  # type: ignore[arg-type]
                trading_day=date.fromisoformat(record["trading_day"]),  # type: ignore[arg-type]
                open=Decimal(record["open"]),  # type: ignore[arg-type]
                high=Decimal(record["high"]),  # type: ignore[arg-type]
                low=Decimal(record["low"]),  # type: ignore[arg-type]
                close=Decimal(record["close"]),  # type: ignore[arg-type]
                volume=Decimal(record["volume"]),  # type: ignore[arg-type]
                turnover=Decimal(record["turnover"]),  # type: ignore[arg-type]
                open_interest=(None if record["open_interest"] is None else Decimal(record["open_interest"])),  # type: ignore[arg-type]
                request_sha256=record["request_sha256"],  # type: ignore[arg-type]
                response_sha256=record["response_sha256"],  # type: ignore[arg-type]
                observed_at=datetime.fromisoformat(record["observed_at"]),  # type: ignore[arg-type]
                classification_version=record["classification_version"],  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID") from exc


@dataclass(frozen=True, slots=True)
class NonpositiveCloseFact:
    """Exact source row whose nonpositive close cannot become a price Bar."""

    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    open_interest: Decimal | None
    request_sha256: str
    response_sha256: str
    observed_at: datetime
    classification_version: str = NONPOSITIVE_CLOSE_CLASSIFICATION_VERSION

    @property
    def classification(self) -> Literal["NONPOSITIVE_CLOSE"]:
        return "NONPOSITIVE_CLOSE"

    def __post_init__(self) -> None:
        if self.classification_version != NONPOSITIVE_CLOSE_CLASSIFICATION_VERSION:
            raise ValueError("SOURCE_QUALITY_CLASSIFICATION_INVALID")
        for field in ("bar_end", "observed_at"):
            value = getattr(self, field)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("SOURCE_QUALITY_IDENTITY_INVALID")
            object.__setattr__(self, field, value.astimezone(UTC))
        if type(self.trading_day) is not date:
            raise ValueError("SOURCE_QUALITY_IDENTITY_INVALID")
        for digest in (self.request_sha256, self.response_sha256):
            if not isinstance(digest, str) or len(digest) != 64 or any(
                letter not in "0123456789abcdef" for letter in digest
            ):
                raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID")
        required = (self.open, self.high, self.low, self.close, self.volume, self.turnover)
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in required):
            raise ValueError("SOURCE_QUALITY_PRICE_INVALID")
        if (
            self.close > 0 or self.volume < 0 or self.turnover < 0
            or self.open_interest is not None and (
                not isinstance(self.open_interest, Decimal)
                or not self.open_interest.is_finite()
                or self.open_interest < 0
            )
        ):
            raise ValueError("SOURCE_QUALITY_PRICE_INVALID")

    def to_record(self) -> dict[str, str | None]:
        return {
            "bar_end": self.bar_end.isoformat(),
            "trading_day": self.trading_day.isoformat(),
            "open": str(self.open), "high": str(self.high), "low": str(self.low),
            "close": str(self.close), "volume": str(self.volume),
            "turnover": str(self.turnover),
            "open_interest": None if self.open_interest is None else str(self.open_interest),
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "observed_at": self.observed_at.isoformat(),
            "classification_version": self.classification_version,
        }

    @classmethod
    def from_record(cls, record: dict[str, str | None]) -> NonpositiveCloseFact:
        try:
            expected = set(cls.__dataclass_fields__)
            if set(record) != expected:
                raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID")
            return cls(
                bar_end=datetime.fromisoformat(record["bar_end"]),  # type: ignore[arg-type]
                trading_day=date.fromisoformat(record["trading_day"]),  # type: ignore[arg-type]
                open=Decimal(record["open"]),  # type: ignore[arg-type]
                high=Decimal(record["high"]),  # type: ignore[arg-type]
                low=Decimal(record["low"]),  # type: ignore[arg-type]
                close=Decimal(record["close"]),  # type: ignore[arg-type]
                volume=Decimal(record["volume"]),  # type: ignore[arg-type]
                turnover=Decimal(record["turnover"]),  # type: ignore[arg-type]
                open_interest=(None if record["open_interest"] is None else Decimal(record["open_interest"])),  # type: ignore[arg-type]
                request_sha256=record["request_sha256"],  # type: ignore[arg-type]
                response_sha256=record["response_sha256"],  # type: ignore[arg-type]
                observed_at=datetime.fromisoformat(record["observed_at"]),  # type: ignore[arg-type]
                classification_version=record["classification_version"],  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID") from exc


SourceQualityFact = PriceUnavailableFact | NonpositiveCloseFact


def semantic_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("SOURCE_QUALITY_SEMANTIC_INVALID")
    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    exponent = cast(int, exponent)
    count = len(digits)
    while count > 1 and digits[count - 1] == 0:
        count -= 1
        exponent += 1
    return f"{'-' if sign else ''}{''.join(str(digit) for digit in digits[:count])}e{exponent}"


def source_quality_semantic_payload(fact: SourceQualityFact) -> dict[str, object]:
    """Numeric source fact, excluding provider transport and observation metadata."""
    if not isinstance(fact, (PriceUnavailableFact, NonpositiveCloseFact)):
        raise ValueError("SOURCE_QUALITY_SEMANTIC_INVALID")
    return {
        "classification": fact.classification,
        "classification_version": fact.classification_version,
        "bar_end": fact.bar_end.isoformat(),
        "trading_day": fact.trading_day.isoformat(),
        "open": semantic_decimal(fact.open),
        "high": semantic_decimal(fact.high),
        "low": semantic_decimal(fact.low),
        "close": semantic_decimal(fact.close),
        "volume": semantic_decimal(fact.volume),
        "turnover": semantic_decimal(fact.turnover),
        "open_interest": semantic_decimal(fact.open_interest),
    }


def source_quality_semantic_sha256(fact: SourceQualityFact) -> str:
    return sha256(json.dumps(
        {"schema": "source_quality_numeric_v1", "fact": source_quality_semantic_payload(fact)},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def source_quality_fact_from_record(
    record: dict[str, str | None],
) -> SourceQualityFact:
    version = record.get("classification_version")
    if version == PRICE_UNAVAILABLE_CLASSIFICATION_VERSION:
        return PriceUnavailableFact.from_record(record)
    if version == NONPOSITIVE_CLOSE_CLASSIFICATION_VERSION:
        return NonpositiveCloseFact.from_record(record)
    raise ValueError("SOURCE_QUALITY_EVIDENCE_INVALID")
