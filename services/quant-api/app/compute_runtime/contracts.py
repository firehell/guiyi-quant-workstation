"""Application-side identities for an exact read and subscribed Market work."""

from dataclasses import dataclass
from datetime import datetime
from re import fullmatch

from guiyi_quant.compute import (
    BarSeries, CompletedBar, FeatureIdentity, FeaturePoint, FeatureRequest, SeriesIdentity,
)
from guiyi_quant.compute.contracts import require_aware


@dataclass(frozen=True, slots=True)
class ComputeWindow:
    source: SeriesIdentity
    as_of: datetime
    first_bar_end: datetime | None
    last_bar_end: datetime | None
    bar_count: int
    input_digest: str

    def __post_init__(self) -> None:
        require_aware(self.as_of)
        if not fullmatch(r"[0-9a-f]{64}", self.input_digest):
            raise ValueError("COMPUTE_WINDOW_DIGEST_REQUIRED")
        if self.bar_count == 0 and self.first_bar_end is None and self.last_bar_end is None:
            return
        if self.bar_count < 1 or self.first_bar_end is None or self.last_bar_end is None:
            raise ValueError("COMPUTE_WINDOW_INVALID")
        require_aware(self.first_bar_end)
        require_aware(self.last_bar_end)
        if not self.first_bar_end <= self.last_bar_end <= self.as_of:
            raise ValueError("COMPUTE_WINDOW_INVALID")

    @classmethod
    def from_series(cls, series: BarSeries, *, as_of: datetime) -> "ComputeWindow":
        count = series.available_count(as_of)
        first = series.bars[0].bar_end if count else None
        last = series.bars[count - 1].bar_end if count else None
        return cls(series.identity, as_of, first, last, count, series.prefix_digest(count))


@dataclass(frozen=True, slots=True)
class ComputeScope:
    """A registered consumer's exact product, frequency, owner and parameters."""

    consumer: str
    product: str
    physical_contract: str
    segment_id: str
    frequency: str
    features: tuple[FeatureRequest, ...]
    source_revision: str | None = None


@dataclass(frozen=True, slots=True)
class CommittedLiveBar:
    """The simulation adapter's already committed, contiguous completed observation."""

    source: SeriesIdentity
    bar: CompletedBar
    commit_id: str
    previous_bar_end: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.bar, CompletedBar) or not self.commit_id or (
            self.bar.physical_contract, self.bar.segment_id
        ) != (
            self.source.physical_contract, self.source.segment_id,
        ):
            raise ValueError("COMPUTE_LIVE_OWNER_OR_COMMIT_INVALID")
        if self.previous_bar_end is not None:
            require_aware(self.previous_bar_end)
            if self.previous_bar_end >= self.bar.bar_end:
                raise ValueError("COMPUTE_LIVE_PREDECESSOR_INVALID")


@dataclass(frozen=True, slots=True)
class ComputeCheckpoint:
    """Portable recovery metadata. A TA-Lib handle is never persisted."""

    identity: FeatureIdentity
    state_schema_version: str
    prefix_digest: str
    mode: str
    live_commit_id: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureUpdate:
    checkpoint: ComputeCheckpoint
    point: FeaturePoint | None
    resumed_bars: int = 0
    duplicate: bool = False
    recovery: str | None = None
