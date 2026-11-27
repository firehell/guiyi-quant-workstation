"""Live admission for existing simulation kernels with their own typed state."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from re import fullmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.market_data.observation_stream import ObservationEnvelope


def verify_tick_original(
    original: "ObservationEnvelope", product: str, contract: str, frequency: str, day: date,
) -> datetime:
    from app.market_data.market_foundation_scope import LIVE_FINALIZATION_DELAY

    end = datetime.fromisoformat(original.data["bar_end"])
    if (end.utcoffset() is None or original.channel != f"live:bar:{product}:{frequency}" or original.trading_day != day
            or original.data["contract"] != contract
            or original.data["trading_day"] != day.isoformat()
            or original.observation_id != f"{day}:{contract}:{frequency}:{end.isoformat()}"
            or original.source_generation is None or original.raw_received_at is None
            or not original.notification_eligible or original.confirmed_at is None
            or not end + LIVE_FINALIZATION_DELAY <= original.confirmed_at
            or not end <= original.source_observed_at <= original.raw_received_at <= original.confirmed_at
            or not original.timely_for_forward(end, original.confirmed_at)):
        raise ValueError("COMPUTE_OWNED_LIVE_ORIGINAL_INVALID")
    return end


@dataclass(frozen=True, slots=True)
class OwnedLiveScope:
    consumer: str
    product: str
    contract: str
    frequency: str
    trading_day: date

    def __post_init__(self) -> None:
        allowed = {"htdy_simulation": ("60m",), "subing_simulation": ("30m", "60m")}
        if (self.frequency not in allowed.get(self.consumer, ())
                or fullmatch(r"[a-z]{1,8}", self.product) is None
                or fullmatch(self.product.upper() + r"[0-9]{3,4}", self.contract) is None
                or type(self.trading_day) is not date):
            raise ValueError("COMPUTE_OWNED_LIVE_SCOPE_INVALID")


@dataclass(frozen=True, slots=True)
class OwnedLiveCommit:
    scope: OwnedLiveScope
    stream_id: str
    bar_end: datetime
    confirmed_at: datetime
    previous_bar_end: datetime | None
    original_digest: str
    input_digest: str

    @classmethod
    def from_original(
        cls, scope: OwnedLiveScope, original: "ObservationEnvelope", *, previous_bar_end: datetime | None,
        input_digest: str | None = None,
    ) -> "OwnedLiveCommit":
        end = verify_tick_original(original, scope.product, scope.contract, scope.frequency, scope.trading_day)
        # verify_tick_original has proved the time exists.
        assert original.confirmed_at is not None
        digest = sha256(original.to_json().encode()).hexdigest()
        return cls(scope, original.stream_id, end, original.confirmed_at, previous_bar_end,
                   digest, input_digest if input_digest is not None else digest)

    def __post_init__(self) -> None:
        if (not isinstance(self.scope, OwnedLiveScope)
                or fullmatch(r"[0-9]+-[0-9]+", self.stream_id) is None
                or any(fullmatch(r"[0-9a-f]{64}", digest) is None
                       for digest in (self.original_digest, self.input_digest))
                or any(stamp.utcoffset() is None for stamp in (self.bar_end, self.confirmed_at))
                or self.bar_end > self.confirmed_at
                or self.previous_bar_end is not None and (
                    self.previous_bar_end.utcoffset() is None or self.previous_bar_end >= self.bar_end)):
            raise ValueError("COMPUTE_OWNED_LIVE_COMMIT_INVALID")


@dataclass(frozen=True, slots=True)
class OwnedLiveUpdate[T]:
    result: T
    duplicate: bool


class OwnedLiveState:
    """Owned kernels run serially on the same Live executor as generic features."""

    def __init__(self, scopes: tuple[OwnedLiveScope, ...]) -> None:
        self.scopes = frozenset(scopes)
        if len(self.scopes) != len(scopes):
            raise ValueError("COMPUTE_OWNED_LIVE_SCOPE_DUPLICATE")
        self._heads: dict[OwnedLiveScope, tuple[object, OwnedLiveCommit, object]] = {}
        self._failed: set[tuple[str, str, str, date]] = set()

    def advance[T](self, commit: OwnedLiveCommit, owner: object, run: Callable[[], T]) -> OwnedLiveUpdate[T]:
        from typing import cast

        scope = commit.scope
        owner_scope = (scope.consumer, scope.product, scope.contract, scope.trading_day)
        if owner_scope in self._failed:
            raise ValueError("COMPUTE_OWNED_LIVE_RESTORE_REQUIRED")
        if (head := self._heads.get(scope)) is not None:
            previous_owner, previous, result = head
            if previous_owner is not owner:
                raise ValueError("COMPUTE_OWNED_LIVE_OWNER_CONFLICT")
            if previous == commit:
                return OwnedLiveUpdate(cast(T, result), duplicate=True)
            if commit.bar_end <= previous.bar_end or commit.stream_id == previous.stream_id:
                raise ValueError("COMPUTE_OWNED_LIVE_COMMIT_CONFLICT")
            if commit.previous_bar_end != previous.bar_end or commit.confirmed_at < previous.confirmed_at:
                raise ValueError("COMPUTE_OWNED_LIVE_NONCONTIGUOUS")
        elif scope.consumer == "subing_simulation" and commit.previous_bar_end is not None:
            raise ValueError("COMPUTE_OWNED_LIVE_PREFIX_REQUIRED")
        try:
            computed = run()
        except Exception:
            # A consumer-owned step may have mutated some of its state.
            self._failed.add(owner_scope)
            raise
        self._heads[scope] = (owner, commit, computed)
        return OwnedLiveUpdate(computed, duplicate=False)
