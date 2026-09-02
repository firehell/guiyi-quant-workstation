"""Runtime-local derived projection for the Market Home overview."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.core.env import PROJECT_ROOT
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


DEFAULT_MARKET_HOME_PROJECTION_PATH = (
    PROJECT_ROOT / ".run" / "market-home-overview.json"
)
_MAX_PROJECTION_BYTES = 2 * 1024 * 1024
_AUTHORITY_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class MarketHomeProjectionError(RuntimeError):
    """Internal projection failure that must never become market authority."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
        try:
            if self.path.is_symlink() or not self.path.is_file():
                return None
            size = self.path.stat().st_size
            if size <= 0 or size > _MAX_PROJECTION_BYTES:
                return None
            envelope = MarketHomeProjectionEnvelope.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError, ValidationError):
            return None
        if (
            envelope.target_as_of != identity.target_as_of
            or envelope.authority_digest != identity.authority_digest
        ):
            return None
        return envelope.payload

    def publish(
        self,
        identity: MarketHomeAuthorityIdentity,
        payload: MarketHomeOverviewResponse,
        *,
        generated_at: datetime,
    ) -> None:
        envelope = MarketHomeProjectionEnvelope(
            generated_at=generated_at,
            target_as_of=identity.target_as_of,
            authority_digest=identity.authority_digest,
            payload=payload,
        )
        encoded = (envelope.model_dump_json() + "\n").encode("utf-8")
        if len(encoded) > _MAX_PROJECTION_BYTES:
            raise MarketHomeProjectionError("MARKET_HOME_PROJECTION_TOO_LARGE")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise MarketHomeProjectionError(
                "MARKET_HOME_PROJECTION_WRITE_FAILED"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


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
        if response.target_as_of != identity.target_as_of:
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
