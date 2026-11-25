"""Time-scoped research protection bands, separate from price targets."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from . import number, physical_contract, timestamp
from ..lms_confirmed_replay import fingerprint


@dataclass(frozen=True)
class ProtectionBandUpdate:
    contract: str
    revision: str
    role: str
    known_at: datetime
    effective_after: datetime
    source: str
    side: str
    lower: Decimal | None = None
    upper: Decimal | None = None

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.known_at)
        timestamp(self.effective_after)
        if (
            not all(isinstance(v, str) and v.strip() for v in (self.revision, self.source))
            or self.role not in ("TARGET", "PROTECTION", "REVIEW_PENDING")
            or self.side not in ("LONG", "SHORT")
            or self.effective_after < self.known_at
        ):
            raise ValueError("INVALID_PROTECTION_BAND_UPDATE")
        if self.role == "REVIEW_PENDING":
            if self.lower is not None or self.upper is not None:
                raise ValueError("UNRESOLVED_PROTECTION_BAND_REQUIRES_NO_BOUNDS")
        else:
            number(self.lower, positive=True)
            number(self.upper, positive=True)
            if self.lower > self.upper:
                raise ValueError("INVALID_PROTECTION_BAND_BOUNDS")
        for name in ("known_at", "effective_after"):
            object.__setattr__(self, name, getattr(self, name).astimezone(UTC))

    @property
    def scope(self):
        return fingerprint(asdict(self))


def visible_bands(updates, contract, as_of):
    visible = {}
    for update in updates:
        if not isinstance(update, ProtectionBandUpdate):
            raise ValueError("PROTECTION_BAND_UPDATE_REQUIRED")
        if update.known_at >= as_of:
            continue
        if update.contract != contract:
            raise ValueError("PROTECTION_BAND_CONTRACT_MISMATCH")
        visible[update.scope] = update
    return tuple(visible.values())


def active_band(visible, as_of, side):
    eligible = [row for row in visible if row.role != "TARGET" and row.side == side and row.effective_after < as_of]
    if not eligible:
        return None, "PROTECTION_RANGE_UNAVAILABLE"
    latest = max(row.effective_after for row in eligible)
    updates = [row for row in eligible if row.effective_after == latest]
    if len(updates) != 1:
        return None, "PROTECTION_RANGE_CONFLICT"
    update = updates[0]
    if update.role == "REVIEW_PENDING":
        return None, "PROTECTION_RANGE_REVIEW_PENDING"
    return update, None
