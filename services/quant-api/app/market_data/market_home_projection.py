"""Derived read projection for the Market Home overview."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.market_data.market_home_overview import (
    MarketHomeAuthorityIdentity,
    MarketHomeOverviewService,
    MarketHomeOverviewSnapshot,
)
from app.schemas.market import (
    MarketHomeItemOut,
    MarketHomeOverviewResponse,
    MarketHomeSectorOut,
    MarketHomeSummaryOut,
)


_MAX_PROJECTION_BYTES = 2 * 1024 * 1024
_AUTHORITY_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)


class MarketHomeProjectionError(RuntimeError):
    """Internal projection failure that must never become market authority."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def market_home_projection_path(canonical_root: Path) -> Path:
    """Place the removable projection beside the shared Canonical root."""

    return canonical_root.resolve() / ".derived" / "market-home-overview.json"


class MarketHomeProjectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    generated_at: datetime
    target_as_of: date
    authority_digest: str
    payload: MarketHomeOverviewResponse

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if _AUTHORITY_DIGEST.fullmatch(self.authority_digest) is None:
            raise ValueError("authority_digest invalid")
        if (
            self.payload.target_as_of != self.target_as_of
            or self.payload.data_as_of != self.target_as_of
        ):
            raise ValueError("payload identity mismatch")
        return self


class MarketHomeProjectionStore:
    """Strict single-file projection store with atomic last-good replacement."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(
        self,
        identity: MarketHomeAuthorityIdentity,
    ) -> MarketHomeOverviewResponse | None:
        parent_descriptor: int | None = None
        try:
            parent_descriptor = _open_projection_parent(self.path.parent, create=False)
            if parent_descriptor is None:
                return None
            try:
                descriptor = os.open(
                    self.path.name,
                    os.O_RDONLY | _required_nofollow(),
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                return None
            try:
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_size <= 0
                    or metadata.st_size > _MAX_PROJECTION_BYTES
                ):
                    return None
                encoded = _bounded_read(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            return None
        finally:
            if parent_descriptor is not None:
                os.close(parent_descriptor)
        try:
            raw = json.loads(encoded)
            if not _has_decimal_wire_contract(raw):
                return None
            envelope = MarketHomeProjectionEnvelope.model_validate_json(
                encoded,
                strict=True,
            )
        except (TypeError, ValueError, ValidationError, UnicodeDecodeError):
            return None
        if (
            envelope.target_as_of != identity.target_as_of
            or envelope.authority_digest != identity.authority_digest
        ):
            return None
        return envelope.payload

    def invalidate(self) -> None:
        """Remove the current projection before any authoritative apply mutation."""

        try:
            parent_descriptor = _open_projection_parent(self.path.parent, create=False)
            if parent_descriptor is None:
                return
            try:
                try:
                    os.unlink(self.path.name, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    return
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        except OSError as exc:
            raise MarketHomeProjectionError(
                "MARKET_HOME_PROJECTION_INVALIDATION_FAILED"
            ) from exc

    def publish(
        self,
        identity: MarketHomeAuthorityIdentity,
        payload: MarketHomeOverviewResponse,
        *,
        generated_at: datetime,
    ) -> None:
        try:
            envelope = MarketHomeProjectionEnvelope(
                generated_at=generated_at,
                target_as_of=identity.target_as_of,
                authority_digest=identity.authority_digest,
                payload=payload,
            )
            encoded = (envelope.model_dump_json() + "\n").encode("utf-8")
        except (TypeError, ValueError, ValidationError) as exc:
            raise MarketHomeProjectionError(
                "MARKET_HOME_PROJECTION_INVALID"
            ) from exc
        if len(encoded) > _MAX_PROJECTION_BYTES:
            raise MarketHomeProjectionError("MARKET_HOME_PROJECTION_TOO_LARGE")

        parent_descriptor: int | None = None
        descriptor: int | None = None
        temporary_name: str | None = None
        try:
            parent_descriptor = _open_projection_parent(self.path.parent, create=True)
            assert parent_descriptor is not None
            temporary_name = f".{self.path.name}.{uuid4().hex}.tmp"
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _required_nofollow(),
                0o600,
                dir_fd=parent_descriptor,
            )
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary_name,
                self.path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise MarketHomeProjectionError(
                "MARKET_HOME_PROJECTION_WRITE_FAILED"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name is not None and parent_descriptor is not None:
                try:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    pass
            if parent_descriptor is not None:
                os.close(parent_descriptor)


class MarketHomeProjection:
    """Projection-first Market Home read model with compute-only fallback."""

    def __init__(
        self,
        *,
        service: MarketHomeOverviewService,
        store: MarketHomeProjectionStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.service = service
        self.store = store
        self._now = now or (lambda: datetime.now(UTC))

    def read(self) -> MarketHomeOverviewResponse:
        identity = self.service.authority_identity()
        cached = self.store.load(identity)
        if cached is not None:
            return cached
        return market_home_response(self.service.snapshot())

    def refresh(self) -> MarketHomeOverviewResponse:
        identity = self.service.authority_identity()
        response = market_home_response(self.service.snapshot())
        if (
            response.target_as_of != identity.target_as_of
            or self.service.authority_identity() != identity
        ):
            raise MarketHomeProjectionError(
                "MARKET_HOME_PROJECTION_IDENTITY_CHANGED"
            )
        self.store.publish(
            identity,
            response,
            generated_at=self._now(),
        )
        return response


def market_home_response(
    snapshot: MarketHomeOverviewSnapshot,
) -> MarketHomeOverviewResponse:
    """Project the authoritative domain snapshot into the frozen HTTP contract."""

    return MarketHomeOverviewResponse(
        status=snapshot.status,
        target_as_of=snapshot.target_as_of,
        data_as_of=snapshot.data_as_of,
        freshness=snapshot.freshness,
        active_count=snapshot.active_count,
        participant_count=snapshot.participant_count,
        stale_count=snapshot.stale_count,
        unavailable_count=snapshot.unavailable_count,
        summary=MarketHomeSummaryOut(
            price_up_count=snapshot.summary.price_up_count,
            price_down_count=snapshot.summary.price_down_count,
            price_flat_count=snapshot.summary.price_flat_count,
            daily_up_count=snapshot.summary.daily_up_count,
            daily_down_count=snapshot.summary.daily_down_count,
            daily_neutral_count=snapshot.summary.daily_neutral_count,
            daily_unavailable_count=snapshot.summary.daily_unavailable_count,
            aligned_up_count=snapshot.summary.aligned_up_count,
            aligned_down_count=snapshot.summary.aligned_down_count,
        ),
        items=[
            MarketHomeItemOut(
                symbol=item.symbol,
                product_name=item.product_name,
                sector=item.sector,
                exchange=item.exchange,
                actual_contract=item.actual_contract,
                dominant_mapping_date=item.dominant_mapping_date,
                data_as_of=item.data_as_of,
                close=item.close,
                price_change_1d=item.price_change_1d,
                price_change_5d=item.price_change_5d,
                volume_ratio20=item.volume_ratio20,
                oi_change_1d=item.oi_change_1d,
                atr14_percentile252=item.atr14_percentile252,
                daily_trend=item.daily_trend,
                weekly_trend=item.weekly_trend,
                reason_codes=list(item.reason_codes),
            )
            for item in snapshot.items
        ],
        sectors=[
            MarketHomeSectorOut(
                sector=sector.sector,
                active_count=sector.active_count,
                participant_count=sector.participant_count,
                median_price_change_1d=sector.median_price_change_1d,
            )
            for sector in snapshot.sectors
        ],
    )


def _required_nofollow() -> int:
    if _NOFOLLOW is None:
        raise OSError("O_NOFOLLOW_UNAVAILABLE")
    return _NOFOLLOW


def _open_projection_parent(path: Path, *, create: bool) -> int | None:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | _required_nofollow(),
        )
    except FileNotFoundError:
        if create:
            raise
        return None


def _bounded_read(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = _MAX_PROJECTION_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    result = b"".join(chunks)
    if not result or len(result) > _MAX_PROJECTION_BYTES:
        raise OSError("PROJECTION_SIZE_INVALID")
    return result


def _write_all(descriptor: int, encoded: bytes) -> None:
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("PROJECTION_SHORT_WRITE")
        remaining = remaining[written:]


def _has_decimal_wire_contract(raw: object) -> bool:
    if not isinstance(raw, Mapping):
        return False
    payload = raw.get("payload")
    if not isinstance(payload, Mapping):
        return False
    items = payload.get("items")
    sectors = payload.get("sectors")
    if not isinstance(items, list) or not isinstance(sectors, list):
        return False
    item_decimal_fields = (
        "close",
        "price_change_1d",
        "price_change_5d",
        "volume_ratio20",
        "oi_change_1d",
        "atr14_percentile252",
    )
    for item in items:
        if not isinstance(item, Mapping) or any(
            not isinstance(item.get(field), str) and item.get(field) is not None
            for field in item_decimal_fields
        ):
            return False
        if not isinstance(item.get("close"), str):
            return False
    return all(
        isinstance(sector, Mapping)
        and (
            isinstance(sector.get("median_price_change_1d"), str)
            or sector.get("median_price_change_1d") is None
        )
        for sector in sectors
    )
