"""Near-replication proposals for explicit hypothetical states; never applies them."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Literal

from .lms405 import Action, Bar, Position, apply_action, timestamp
from .lms_keybar_approx import Frame, VERSION as KEYBAR_VERSION, classify, observe_next

VERSION = "lms-protection-proposal-v1"


@dataclass(frozen=True)
class ResearchState:
    position: Position
    original_side: Literal["LONG", "SHORT"]
    since: datetime
    known_at: datetime

    def __post_init__(self):
        if not isinstance(self.position, Position):
            raise ValueError("RESEARCH_POSITION_REQUIRED")
        self.position.__post_init__()
        timestamp(self.since)
        timestamp(self.known_at)
        p = self.position
        if (
            self.original_side not in {"LONG", "SHORT"}
            or self.known_at < self.since
            or p.long not in (Decimal(0), Decimal(1))
            or p.short not in (Decimal(0), Decimal(1))
        ):
            raise ValueError("INVALID_UNIT_RESEARCH_STATE")
        if (p.long > p.short and self.original_side != "LONG") or (
            p.short > p.long and self.original_side != "SHORT"
        ):
            raise ValueError("ORIGINAL_SIDE_STATE_CONFLICT")

    @property
    def phase(self):
        if self.position.long == self.position.short == 0:
            return "FLAT"
        return "LOCKED" if self.position.long == self.position.short else "DIRECTIONAL"


def _fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def recommend(
    state: ResearchState, frame: Frame, following: Bar, *, as_of: datetime
) -> dict:
    """Only next supplied-row confirmation. No state transition or order is made.

    A caller may inspect the same state repeatedly: a proposal remains a proposal.
    A later, externally supplied research state is required to study restoration.
    """
    state.__post_init__()
    timestamp(as_of)
    if (
        frame != classify(frame.previous, frame.bar)
        or frame.rule_version != KEYBAR_VERSION
    ):
        raise ValueError("KEYBAR_FRAME_IDENTITY_MISMATCH")
    classify(
        frame.bar, following
    )  # completed interval, chronology, contract validation
    if state.position.contract != frame.bar.contract:
        raise ValueError("CONTRACT_BOUNDARY")
    state_hash = _fingerprint(asdict(state))
    result = dict(
        policy_version=VERSION,
        keybar_version=KEYBAR_VERSION,
        input_kind="EXPLICIT_HYPOTHETICAL_UNIT_STATE",
        contract=state.position.contract,
        original_side=state.original_side,
        phase=state.phase,
        state_since=state.since.isoformat(),
        state_known_at=state.known_at.isoformat(),
        state_fingerprint=state_hash,
        unit_position_before={
            "long": str(state.position.long),
            "short": str(state.position.short),
        },
        signal_bar_end=frame.bar.end.isoformat(),
        available_after=following.end.isoformat(),
        as_of=as_of.isoformat(),
        status="NO_CONFIRMED_DIRECTION",
        signal_direction=None,
        suggested_action=None,
        proposal_id=None,
        basis=[],
        hypothetical_unit_position_after=None,
        requires_human_confirmation=True,
        executable=False,
        fill=None,
        performance=None,
    )
    if as_of <= following.end:
        return result | {"status": "NOT_YET_AVAILABLE"}
    if state.known_at >= as_of:
        return result | {"status": "STATE_NOT_AVAILABLE"}
    if frame.bar.end <= state.since:
        return result | {"status": "STALE_SIGNAL"}
    if state.phase == "FLAT":
        return result | {"status": "FLAT_NO_ENTRY"}
    if not frame.has_pattern:
        return result
    obs = observe_next(frame, frame.bar, following)
    direction = (
        "LONG" if obs.close_above_high else "SHORT" if obs.close_below_low else None
    )
    if direction is None:
        return result
    suffix = "UP_CLOSE_BREAK" if direction == "LONG" else "DOWN_CLOSE_BREAK"
    if frame.ibar is True:
        result["basis"].append(f"IBAR_{suffix}")
    if frame.pinbar == direction:
        result["basis"].append(f"PINBAR_{direction}_{suffix}")
    if not result["basis"]:
        return result
    result["signal_direction"] = direction
    if state.phase == "DIRECTIONAL":
        if direction == state.original_side:
            return result | {"status": "SAME_DIRECTION_HOLD"}
        kind = "LOCK"
    else:
        if direction != state.original_side:
            return result | {"status": "OPPOSING_SIGNAL_WHILE_LOCKED"}
        kind = f"UNLOCK_{state.original_side}"
    after = apply_action(state.position, Action(kind, Decimal(1)))
    identity = dict(
        policy=VERSION,
        state=state_hash,
        frame=asdict(frame),
        following=asdict(following),
        action=kind,
    )
    return result | dict(
        status="PROPOSAL",
        suggested_action=kind,
        proposal_id=_fingerprint(identity),
        hypothetical_unit_position_after={
            "long": str(after.long),
            "short": str(after.short),
        },
    )
