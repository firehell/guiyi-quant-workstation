"""Research permission to use an endpoint for one specific lock episode."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from . import number, physical_contract, timestamp
from ..lms_confirmed_replay import fingerprint


@dataclass(frozen=True)
class RecoveryPermission:
    contract: str
    plan_id: str
    cycle_id: str
    original_side: str
    locked_at: datetime
    known_at: datetime
    decision: str
    endpoint: str | None
    edge: Decimal | None
    source: str
    record_kind: str
    expires_at: datetime | None = None

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.locked_at)
        timestamp(self.known_at)
        if self.expires_at is not None:
            timestamp(self.expires_at)
        if (self.original_side not in ("LONG", "SHORT")
                or self.known_at < self.locked_at
                or (self.expires_at is not None and self.expires_at <= self.known_at)
                or not all(isinstance(v, str) and v.strip() for v in (self.plan_id, self.cycle_id, self.source))
                or self.record_kind not in ("HUMAN_RESEARCH_EVIDENCE", "TEST_FIXTURE")):
            raise ValueError("INVALID_RECOVERY_PERMISSION")
        if self.decision == "PERMIT" and self.endpoint in ("NEAR", "FAR") and self.edge is not None:
            number(self.edge, positive=True)
        elif self.decision != "DENY" or self.endpoint is not None or self.edge is not None:
            raise ValueError("INVALID_RECOVERY_PERMISSION_DECISION")
        for field in ("locked_at", "known_at", "expires_at"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, value.astimezone(UTC))

    @property
    def identity(self):
        return fingerprint(asdict(self))


def visible_permissions(records, contract, *, as_of, timely_fixture):
    if not isinstance(timely_fixture, bool):
        raise ValueError("BOOLEAN_MODE_REQUIRED")
    visible = {}
    for item in records:
        if not isinstance(item, RecoveryPermission):
            raise ValueError("RECOVERY_PERMISSION_REQUIRED")
        if item.known_at >= as_of:
            continue
        if item.contract != contract:
            raise ValueError("RECOVERY_PERMISSION_CONTRACT_MISMATCH")
        if not timely_fixture and item.record_kind != "HUMAN_RESEARCH_EVIDENCE":
            raise ValueError("HUMAN_RECOVERY_PERMISSION_REQUIRED")
        visible[item.identity] = item
    return tuple(visible.values())


def current_permission(records, state, as_of):
    """Resolve only the latest known permission for the current lock."""
    locked_at = datetime.fromisoformat(state["since"])
    matches = [item for item in records if item.known_at < as_of and item.locked_at == locked_at
               and item.contract == state["contract"] and item.plan_id == state["plan"]["plan_id"]
               and item.cycle_id == state["cycle_id"] and item.original_side == state["original_side"]]
    if not matches:
        return None, "RECOVERY_PERMISSION_UNKNOWN"
    latest_at = max(item.known_at for item in matches)
    latest = [item for item in matches if item.known_at == latest_at]
    if len(latest) != 1:
        return None, "RECOVERY_PERMISSION_CONFLICT"
    item = latest[0]
    if item.expires_at is not None and as_of >= item.expires_at:
        return None, "RECOVERY_PERMISSION_EXPIRED"
    return (item, None) if item.decision == "PERMIT" else (None, "RECOVERY_PERMISSION_DENIED")
