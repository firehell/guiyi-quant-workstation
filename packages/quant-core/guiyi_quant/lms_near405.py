"""Complete deterministic near-LMS research candidate, never an execution engine.

All thresholds and combined rules are candidate assumptions. Old LMS versions
remain independent. Decimal prices, explicit human decisions, no fills/PnL.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from .lms405 import Position, Action, apply_action, physical_contract, timestamp
from .lms405.protection_band import active_band, visible_bands
from .lms_author_regions import RegionInput
from .lms_keybar_approx import classify, VERSION as KEYBAR_VERSION
from .lms_confirmed_replay import fingerprint

VERSION = "lms-near405-v1"
RULES = dict(
    version=VERSION,
    keybar_version=KEYBAR_VERSION,
    context_bars=6,
    block_bars=3,
    plan_lifetime_bars=12,
    max_attempts=2,
    availability_microseconds=1,
    fixture_delay_microseconds=1,
    priority=[
        "RISK_INVALID",
        "PLAN_EXPIRED",
        "REGIME_INVALID",
        "RANGE_TARGET",
        "LOCK",
        "UNLOCK",
        "REENTER",
        "ENTER",
    ],
)
RULE_HASH = fingerprint(RULES)
US = timedelta(microseconds=1)
STUDY_VERSION = "lms-near405-author-study-v1"
CLOCK_VERSIONS = {
    "DEFER_WHILE_LOCKED": "lms-near405-hold-clock-defer-v1",
    "PAUSE_WHILE_LOCKED": "lms-near405-hold-clock-pause-v1",
}
EXTERNAL_PROTECTION_VERSION = "lms-near405-external-protection-v1"
SCOPED_PROTECTION_VERSION = "lms-near405-scoped-protection-v1"
CARRY_IN_VERSION = "lms-near405-carry-in-v1"
CARRY_IN_EXIT_VERSION = "lms-near405-carry-in-explicit-exit-v1"
CARRY_SCOPED_PROTECTION_VERSION = "lms-near405-carry-scoped-protection-v1"
MANAGEMENT_VERSION = "lms-near405-managed-lifecycle-v1"


@dataclass(frozen=True)
class CarryInSeed:
    """Research-only starting observation. An older trade's entry plan is unknown."""

    contract: str
    known_at: datetime
    original_side: str | None
    locked: bool
    source: str

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.known_at)
        if (self.original_side not in (None, "LONG", "SHORT")
                or not isinstance(self.locked, bool)
                or (self.original_side is None and self.locked)
                or not isinstance(self.source, str) or not self.source.strip()):
            raise ValueError("INVALID_CARRY_IN_SEED")
        object.__setattr__(self, "known_at", self.known_at.astimezone(UTC))


@dataclass(frozen=True)
class CarryInExitEvidence:
    """Explicit full-exit condition for the supplied research position."""

    contract: str
    state_fingerprint: str
    observed_at: datetime
    known_at: datetime
    source: str
    record_kind: str

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.observed_at)
        timestamp(self.known_at)
        if (self.known_at < self.observed_at
                or any(not isinstance(value, str) or not value.strip()
                       for value in (self.state_fingerprint, self.source))
                or self.record_kind not in ("HUMAN_RESEARCH_EVIDENCE", "TEST_FIXTURE")):
            raise ValueError("INVALID_CARRY_IN_EXIT_EVIDENCE")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        object.__setattr__(self, "known_at", self.known_at.astimezone(UTC))


def _visible_carry_exits(evidence, contract, *, as_of, timely_fixture):
    visible = []
    for item in evidence:
        if not isinstance(item, CarryInExitEvidence):
            raise ValueError("CARRY_IN_EXIT_EVIDENCE_REQUIRED")
        if item.known_at >= as_of:
            continue
        if item.contract != contract:
            raise ValueError("CARRY_IN_EXIT_CONTRACT_MISMATCH")
        if not timely_fixture and item.record_kind != "HUMAN_RESEARCH_EVIDENCE":
            raise ValueError("HUMAN_CARRY_IN_EXIT_EVIDENCE_REQUIRED")
        visible.append(item)
    return tuple(dict.fromkeys(visible))


def _carry_exits_for_state(evidence, state):
    state_hash, since = fingerprint(state), _time(state["since"])
    return [item for item in evidence if item.state_fingerprint == state_hash and since < item.observed_at]


@dataclass(frozen=True)
class ProtectionConfirmation:
    """Explicit positive evidence of both protection need and opposite signal."""

    contract: str
    state_fingerprint: str
    due_at: datetime
    signal_at: datetime
    known_at: datetime
    source: str
    record_kind: str

    def __post_init__(self):
        physical_contract(self.contract)
        for time in (self.due_at, self.signal_at, self.known_at):
            timestamp(time)
        if (
            self.known_at < max(self.due_at, self.signal_at)
            or any(not isinstance(value, str) or not value.strip()
                   for value in (self.source, self.state_fingerprint))
            or self.record_kind not in ("HUMAN_RESEARCH_EVIDENCE", "TEST_FIXTURE")
        ):
            raise ValueError("INVALID_PROTECTION_CONFIRMATION")
        for field in ("due_at", "signal_at", "known_at"):
            object.__setattr__(self, field, getattr(self, field).astimezone(UTC))


@dataclass(frozen=True)
class ScopedProtectionConfirmation(ProtectionConfirmation):
    band_scope: str
    signal_start: datetime
    signal_side: str

    def __post_init__(self):
        super().__post_init__()
        timestamp(self.signal_start)
        if (not isinstance(self.band_scope, str) or not self.band_scope.strip()
                or self.signal_side not in ("LONG", "SHORT") or self.signal_start >= self.signal_at):
            raise ValueError("INVALID_SCOPED_PROTECTION_CONFIRMED_SIGNAL")
        object.__setattr__(self, "signal_start", self.signal_start.astimezone(UTC))


def _visible_protection(confirmations, contract, *, as_of, timely_fixture):
    visible = []
    for item in confirmations:
        if not isinstance(item, ProtectionConfirmation):
            raise ValueError("PROTECTION_CONFIRMATION_REQUIRED")
        if item.known_at > as_of:
            continue
        if item.contract != contract:
            raise ValueError("PROTECTION_CONFIRMATION_CONTRACT_MISMATCH")
        if not timely_fixture and item.record_kind != "HUMAN_RESEARCH_EVIDENCE":
            raise ValueError("HUMAN_PROTECTION_EVIDENCE_REQUIRED")
        visible.append(item)
    return tuple(dict.fromkeys(visible))


def _rules_for(
    region_input, clock, external_protection=False, scoped_protection=False, carry_in=False, explicit_exit=False,
    managed_lifecycle=False,
):
    if not isinstance(managed_lifecycle, bool):
        raise ValueError("BOOLEAN_MODE_REQUIRED")
    if managed_lifecycle:
        if any((region_input is not None, clock is not None, external_protection, scoped_protection,
                carry_in, explicit_exit)):
            raise ValueError("MANAGED_LIFECYCLE_REQUIRES_INDEPENDENT_PLAN")
        rules = RULES | dict(
            version=MANAGEMENT_VERSION, plan_lifetime_bars=None, max_attempts=1,
            priority=["RISK_INVALID", "OPPOSING_KEYBAR_AFTER_RANGE_TARGET", "OPPOSING_KEYBAR_REGIME_REVERSAL",
                      "LOCK", "UNLOCK", "ENTER"],
            recovery="TWO_CONTIGUOUS_CLOSES_BEYOND_FRESH_FROZEN_EDGE_CROSSING_AFTER_LOCK",
            range_target="PRIOR_COMPLETE_BAR_TOUCH_AFTER_ENTRY_ONLY",
            held_signal="CONTIGUOUS_SHAPE_AND_CONFIRMATION_AFTER_STATE",
            reentry="NEW_PLAN_WITH_ALL_CONTEXT_STARTED_AFTER_EXIT",
        )
        return rules, fingerprint(rules)
    if explicit_exit and not carry_in:
        raise ValueError("EXPLICIT_EXIT_REQUIRES_CARRY_IN")
    if carry_in:
        if (region_input is not None or clock is not None
                or ((external_protection or scoped_protection)
                    and not (external_protection and scoped_protection and explicit_exit))):
            raise ValueError("CARRY_IN_BASELINE_RULES_REQUIRED")
        rules = RULES | dict(version=CARRY_IN_VERSION, seed_plan="PRESEED_CONTEXT_PROXY")
        if explicit_exit:
            rules.update(version=CARRY_IN_EXIT_VERSION, carry_exit="EXPLICIT_POSITION_EVIDENCE")
        if scoped_protection:
            rules.update(version=CARRY_SCOPED_PROTECTION_VERSION,
                         protection="EXPLICIT_STATE_AND_CURRENT_PROTECTION_RANGE_REQUIRED",
                         recovery="CONTIGUOUS_ORIGINAL_DIRECTION_KEYBAR_AFTER_LOCK",
                         pending_management="EXPIRE_ON_VISIBLE_EXIT_OR_PROTECTION_RANGE_SUPERSESSION")
        return rules, fingerprint(rules)
    if region_input is None and clock is None and not external_protection:
        return RULES, RULE_HASH
    rules = RULES.copy()
    if region_input is not None:
        rules.update(
            version=STUDY_VERSION,
            region_mode=region_input.source_mode,
            recovery_rule=region_input.recovery_rule,
        )
    if clock is not None:
        if not isinstance(clock, str) or clock not in CLOCK_VERSIONS:
            raise ValueError("UNKNOWN_HELD_PLAN_CLOCK")
        rules.update(version=CLOCK_VERSIONS[clock], held_plan_clock=clock)
    if external_protection:
        rules.update(version=EXTERNAL_PROTECTION_VERSION,
                     protection="EXPLICIT_STATE_BOUND_CONFIRMATION_ONLY")
    if scoped_protection:
        rules.update(version=SCOPED_PROTECTION_VERSION,
                     protection="EXPLICIT_STATE_AND_CURRENT_PROTECTION_RANGE_REQUIRED")
    return rules, fingerprint(rules)


def _time(value):
    t = datetime.fromisoformat(value)
    timestamp(t)
    return t


def context(bars, index):
    """Exclude signal(index-1) and confirmation(index); no future pivot labels."""
    if index < 7:
        return None
    w = bars[index - 7 : index - 1]
    a, b = w[:3], w[3:]
    ah, al = max(x.high for x in a), min(x.low for x in a)
    bh, bl = max(x.high for x in b), min(x.low for x in b)
    env = "UP" if bh > ah and bl > al else "DOWN" if bh < ah and bl < al else "RANGE"
    lower, upper = min(x.low for x in w), max(x.high for x in w)
    return dict(
        environment=env,
        lower=str(lower),
        upper=str(upper),
        valid=lower < upper,
        window_start=w[0].end.isoformat(),
        window_end=w[-1].end.isoformat(),
        context_hash=fingerprint([asdict(x) for x in w]),
    )


def _direction(frame, following):
    direction = (
        "LONG"
        if following.close > frame.bar.high
        else "SHORT"
        if following.close < frame.bar.low
        else None
    )
    if direction and (frame.ibar is True or frame.pinbar == direction):
        return direction
    return None


def _entry_allowed(region, side, signal, following):
    lo, hi = Decimal(region["lower"]), Decimal(region["upper"])
    # Multiplication by 2 avoids midpoint rounding and a new indicator parameter.
    with localcontext() as ctx:
        values = (lo, hi, signal.low, signal.high)
        ctx.prec = max(
            28,
            max(x.adjusted() for x in values)
            - min(x.as_tuple().exponent for x in values)
            + 4,
        )
        near_high = signal.low <= hi and signal.high * 2 >= lo + hi
        near_low = signal.high >= lo and signal.low * 2 <= lo + hi
    env = region["environment"]
    c = following.close
    if side == "LONG":
        return (env == "UP" and near_high and c > hi) or (
            env == "RANGE" and near_low and lo < c < hi
        )
    return (env == "DOWN" and near_low and c < lo) or (
        env == "RANGE" and near_high and lo < c < hi
    )


def _plan_expired(state, j, clock):
    end = state["plan"]["created_index"] + RULES["plan_lifetime_bars"]
    if clock == "PAUSE_WHILE_LOCKED":
        # Accepted actions occur after the indexed bar is available. The lock
        # bar counts, and an unlock bar still belongs to the locked interval.
        end += sum(
            max(0, (j if unlocked is None else min(j, unlocked)) - locked)
            for locked, unlocked in state["lock_intervals"]
        )
    elif clock == "DEFER_WHILE_LOCKED" and any(
        locked < j and (unlocked is None or j <= unlocked)
        for locked, unlocked in state["lock_intervals"]
    ):
        return False
    return j >= end


def _risk_invalid(side, close, lo, hi):
    return (side == "LONG" and close <= lo) or (side == "SHORT" and close >= hi)


def _invalid(state, bars, index, clock):
    plan = state["plan"]
    side = state["original_side"]
    lo, hi = Decimal(plan["lower"]), Decimal(plan["upper"])
    # Persistent invalidation for this cycle: reveal history only, never heal a
    # breached plan while waiting for a human CLEAR. New reentry starts a cycle.
    for j in range(state["entry_index"] + 1, index + 1):
        found = set()
        c = bars[j].close
        if _risk_invalid(side, c, lo, hi):
            found.add("RISK_INVALID")
        if _plan_expired(state, j, clock):
            found.add("PLAN_EXPIRED")
        env = context(bars, j)
        if env and env["environment"] == ("DOWN" if side == "LONG" else "UP"):
            found.add("REGIME_INVALID")
        if plan["environment"] == "RANGE" and (
            (side == "LONG" and c >= hi) or (side == "SHORT" and c <= lo)
        ):
            found.add("RANGE_TARGET")
        first = next((r for r in RULES["priority"][:4] if r in found), None)
        if first:
            return first
    return None


def initial_state(bars):
    seed = (bars[0].start - US).isoformat()
    return dict(
        contract=bars[0].contract,
        long="0",
        short="0",
        original_side=None,
        cycle_id=None,
        cycle_seq=0,
        plan=None,
        attempt=0,
        entry_index=None,
        since=seed,
        known_at=seed,
        last_exit_at=None,
        last_exit_reason=None,
    )


def _carry_in_state(bars, seed, as_of):
    if not isinstance(seed, CarryInSeed) or seed.contract != bars[0].contract:
        raise ValueError("CARRY_IN_CONTRACT_MISMATCH")
    if seed.known_at > as_of:
        raise ValueError("CARRY_IN_NOT_YET_KNOWN")
    prefix_count = sum(bar.end + US < seed.known_at for bar in bars)
    region = context(bars, prefix_count - 1)
    if region is None or (seed.original_side and not region["valid"]):
        raise ValueError("CARRY_IN_PRESEED_CONTEXT_REQUIRED")
    known = seed.known_at.isoformat()
    seed_id = fingerprint(asdict(seed))
    state = initial_state(bars) | dict(since=known, known_at=known, carry_in_seed_id=seed_id,
                                       carry_in_known_at=known)
    if seed.original_side is None:
        return state
    index = sum(bar.end + US <= seed.known_at for bar in bars) - 1
    plan = {field: region[field] for field in ("lower", "upper", "environment", "context_hash")}
    plan.update(side=seed.original_side, created_index=index, created_at=known, source=seed.source,
                pricing_basis="PRESEED_CONTEXT_PROXY")
    plan["plan_id"] = fingerprint(dict(seed=seed_id, plan=plan))
    return state | dict(
        long="1" if seed.locked or seed.original_side == "LONG" else "0",
        short="1" if seed.locked or seed.original_side == "SHORT" else "0",
        original_side=seed.original_side,
        cycle_id=fingerprint(dict(seed=seed_id, plan=plan["plan_id"])),
        cycle_seq=1, plan=plan, attempt=1, entry_index=index,
    )


def _recovery_status(plan, direction, bars, index):
    key = "recovery_" + direction.lower()
    if plan.get("author_region_id"):
        boundary = plan.get(key)
        if boundary is None:
            return "RECOVERY_BOUNDARY_UNKNOWN"
    elif plan["environment"] != "RANGE":
        boundary = plan["upper" if direction == "LONG" else "lower"]
    else:
        # A generated range edge is already the hard CLEAR target.
        return None
    threshold = Decimal(boundary)
    closes = (bars[index - 1].close, bars[index].close)
    if bars[index].start != bars[index - 1].end:
        return "RECOVERY_TWO_CLOSES_NOT_MET"
    passed = all(
        close > threshold if direction == "LONG" else close < threshold
        for close in closes
    )
    return None if passed else "RECOVERY_TWO_CLOSES_NOT_MET"


def _managed_recovery(state, bars, index, edge):
    is_long = state["original_side"] == "LONG"
    locked_at = _time(state["since"])

    def beyond(bar):
        return bar.close > edge if is_long else bar.close < edge

    if not all(beyond(bar) for bar in bars[index - 1:index + 1]):
        return False
    for j in range(index - 1, state["entry_index"], -1):
        bar = bars[j]
        if bars[j + 1].start != bar.end or bar.end <= locked_at:
            return False
        if not beyond(bar):
            return True
    return False


def _managed_position(state, bars, index, region, direction, signal_fresh):
    plan, side = state["plan"], state["original_side"]
    lo, hi = Decimal(plan["lower"]), Decimal(plan["upper"])
    entry_known = _time(state["management_entry_known_at"])
    since_entry = bars[state["entry_index"] + 1:index + 1]
    if any(entry_known < bar.end and _risk_invalid(side, bar.close, lo, hi) for bar in since_entry):
        return "CLEAR", "RISK_INVALID", "HOLD"
    if not direction or not signal_fresh:
        return None, None, "HOLD"
    locked = state["long"] == state["short"]
    if direction == side:
        if locked and _managed_recovery(state, bars, index, hi if side == "LONG" else lo):
            return "UNLOCK_" + side, "ORIGINAL_KEYBAR_AFTER_FRESH_RETURN", "HOLD"
        return None, None, "RECOVERY_RETURN_UNCONFIRMED" if locked else "HOLD"
    if plan["environment"] == "RANGE" and any(
        entry_known < bar.start and (bar.high >= hi if side == "LONG" else bar.low <= lo)
        for bar in since_entry[:-1]
    ):
        return "CLEAR", "OPPOSING_KEYBAR_AFTER_RANGE_TARGET", "HOLD"
    if region["environment"] == ("DOWN" if side == "LONG" else "UP"):
        return "CLEAR", "OPPOSING_KEYBAR_REGIME_REVERSAL", "HOLD"
    return (None, None, "HOLD") if locked else ("LOCK", "OPPOSING_KEYBAR", "HOLD")


def _validate_prefix(bars):
    for i, bar in enumerate(bars):
        classify(bars[i - 1] if i else None, bar)


def evaluate(
    state,
    bars,
    index,
    *,
    region_input=None,
    timely_fixture=False,
    clock=None,
    protection_confirmations=None,
    protection_bands=None,
    carry_exit_evidence=None,
    managed_lifecycle=False,
):
    """Evaluate one completed Bar against an explicit research state."""
    if "carry_in_seed_id" in state or managed_lifecycle:
        _validate_prefix(bars[:index + 1])
    return _evaluate(
        state, bars, index, region_input=region_input, timely_fixture=timely_fixture, clock=clock,
        protection_confirmations=protection_confirmations, protection_bands=protection_bands,
        carry_exit_evidence=carry_exit_evidence,
        managed_lifecycle=managed_lifecycle,
    )


def _evaluate(
    state,
    bars,
    index,
    *,
    region_input=None,
    timely_fixture=False,
    clock=None,
    protection_confirmations=None,
    protection_bands=None,
    carry_exit_evidence=None,
    managed_lifecycle=False,
):
    """One revealed Bar, one possible proposal; state is never mutated here."""
    c = bars[index]
    t = c.end + US
    external = protection_confirmations is not None
    scoped = protection_bands is not None
    if scoped and not external:
        raise ValueError("SCOPED_PROTECTION_REQUIRES_EXPLICIT_CONFIRMATIONS")
    seeded = "carry_in_seed_id" in state
    explicit_exit = carry_exit_evidence is not None
    rules, rule_hash = _rules_for(region_input, clock, external, scoped, seeded, explicit_exit, managed_lifecycle)
    if state.get("plan") is not None and managed_lifecycle != ("management_entry_known_at" in state):
        raise ValueError("MANAGED_STATE_RULE_MISMATCH")
    if managed_lifecycle and state["contract"] != c.contract:
        raise ValueError("MANAGED_STATE_CONTRACT_MISMATCH")
    if seeded:
        if state["contract"] != c.contract:
            raise ValueError("CARRY_IN_CONTRACT_MISMATCH")
        if t <= _time(state["carry_in_known_at"]):
            raise ValueError("CARRY_IN_NOT_YET_KNOWN")
    if explicit_exit:
        if not isinstance(timely_fixture, bool):
            raise ValueError("BOOLEAN_MODE_REQUIRED")
        carry_exit_evidence = _visible_carry_exits(
            carry_exit_evidence, c.contract, as_of=t, timely_fixture=timely_fixture,
        )
    if external:
        if not isinstance(timely_fixture, bool):
            raise ValueError("BOOLEAN_MODE_REQUIRED")
        if state["contract"] != c.contract:
            raise ValueError("PROTECTION_STATE_CONTRACT_MISMATCH")
        protection_confirmations = _visible_protection(
            protection_confirmations, c.contract, as_of=c.end, timely_fixture=timely_fixture,
        )
        if not scoped and any(isinstance(p, ScopedProtectionConfirmation) for p in protection_confirmations):
            raise ValueError("SCOPED_CONFIRMATION_REQUIRES_PROTECTION_BANDS")
    band, band_issue = (active_band(visible_bands(protection_bands, c.contract, t), t, state["original_side"])
                        if scoped else (None, None))
    region = context(bars, index)
    region_issue = None
    author_region = None
    if region and region_input and region_input.source_mode == "AUTHOR":
        author_region, region_issue = region_input.resolve(
            bars[index - 1], t, timely_fixture=timely_fixture
        )
        if author_region:
            region.update(
                lower=str(author_region.zone.lower),
                upper=str(author_region.zone.upper),
                valid=True,
                window_start=author_region.starts_at.isoformat(),
                author_region_id=author_region.zone.id,
                source=author_region.zone.source,
                context_hash=fingerprint(
                    (region["context_hash"], asdict(author_region))
                ),
                recovery_long=(
                    str(author_region.recovery_long)
                    if author_region.recovery_long is not None
                    else None
                ),
                recovery_short=(
                    str(author_region.recovery_short)
                    if author_region.recovery_short is not None
                    else None
                ),
            )
    frame = (
        classify(bars[index - 2] if index >= 2 else None, bars[index - 1])
        if index
        else None
    )
    direction = _direction(frame, c) if frame else None
    result = dict(
        index=index,
        bar_end=c.end.isoformat(),
        available_at=t.isoformat(),
        environment=region["environment"] if region else None,
        region=region,
        pattern=dict(
            ibar=frame.ibar,
            pinbar=frame.pinbar,
            signal_bar_end=frame.bar.end.isoformat(),
        )
        if frame
        else None,
        signal_direction=direction,
        status="WARMUP" if region is None else "HOLD",
        proposal=None,
    )
    if region_input is not None:
        result["region_issue"] = region_issue
        if region_issue:
            result["region"] = None
    if scoped:
        result["protection_band_scope"] = band.scope if band else None
        result["protection_band_revision"] = band.revision if band else None
    if region is None:
        return result
    action = reason = plan = protection = exit_proof = None
    held = Decimal(state["long"]) + Decimal(state["short"]) > 0
    signal_fresh = frame.bar.end > _time(state["since"])
    if seeded:
        signal_fresh = signal_fresh and frame.bar.start > _time(state["carry_in_known_at"])
        if scoped and held:
            signal_fresh = (signal_fresh and frame.bar.start > _time(state["since"])
                            and frame.bar.end == c.start and bars[index - 2].end == frame.bar.start)
    if held and managed_lifecycle:
        signal_fresh = (frame.bar.start > _time(state["since"]) and frame.bar.end == c.start
                        and bars[index - 2].end == frame.bar.start)
        action, reason, result["status"] = _managed_position(state, bars, index, region, direction, signal_fresh)
    elif held:
        reason = _invalid(state, bars, index, clock)
        locked = state["long"] == state["short"]
        if explicit_exit and state["plan"].get("pricing_basis") == "PRESEED_CONTEXT_PROXY":
            matches = _carry_exits_for_state(carry_exit_evidence, state)
            result["carry_exit_proxy_reason"] = reason
            result["carry_exit_status"] = "UNKNOWN"
            reason = None
            if len(matches) == 1:
                exit_proof = matches[0]
                result["carry_exit_status"] = "CONFIRMED"
                reason = "EXPLICIT_CARRY_IN_EXIT"
            elif matches:
                result["carry_exit_status"] = "CONFLICT"
        if reason:
            action = "CLEAR"
        elif not locked and external:
            since = _time(state["since"])
            proof = [item for item in protection_confirmations
                     if bars[index - 1].end + US <= item.known_at < t
                     and since < min(item.due_at, item.signal_at)
                     and item.state_fingerprint == fingerprint(state)]
            if scoped:
                original_side = state["original_side"]
                proof = [
                    item for item in proof
                    if band is not None and isinstance(item, ScopedProtectionConfirmation)
                    and item.band_scope == result["protection_band_scope"]
                    and item.signal_side != original_side
                    and band.effective_after < item.due_at
                    and max(since, band.effective_after) < item.signal_start
                ]
            if band_issue:
                result["status"] = band_issue
            elif len(proof) == 1:
                action, reason = "LOCK", "EXTERNAL_PROTECTION_CONFIRMED"
                protection = proof[0]
            elif len(proof) > 1:
                result["status"] = "CONFLICTING_PROTECTION_CONFIRMATIONS"
            else:
                result["status"] = "PROTECTION_UNCONFIRMED"
        elif direction and signal_fresh:
            if not locked and direction != state["original_side"]:
                action = "LOCK"
                reason = "OPPOSING_KEYBAR"
            elif locked and direction == state["original_side"]:
                recovery_status = (
                    _recovery_status(state["plan"], direction, bars, index)
                    if region_input
                    and region_input.recovery_rule == "TWO_CLOSES_BEYOND"
                    else None
                )
                if recovery_status:
                    result["status"] = recovery_status
                else:
                    action = "UNLOCK_" + direction
                    reason = "ORIGINAL_DIRECTION_KEYBAR"
    elif region_issue:
        result["status"] = "INDETERMINATE"
    elif direction and signal_fresh and region["valid"]:
        prior = state["plan"]
        context_start = bars[index - 7].start if managed_lifecycle else _time(region["window_start"])
        if (
            not managed_lifecycle and prior
            and state["last_exit_reason"] == "RISK_INVALID"
            and state["attempt"] < RULES["max_attempts"]
            and index < prior["created_index"] + RULES["plan_lifetime_bars"]
            and (
                not author_region or author_region.zone.id == prior["author_region_id"]
            )
            and direction == prior["side"]
            and region["environment"] != ("DOWN" if direction == "LONG" else "UP")
            and _entry_allowed(prior, direction, frame.bar, c)
        ):
            action = "REENTER_" + direction
            reason = "FRESH_SIGNAL_RETRY"
            plan = prior
        # A new plan requires an entire post-exit context, not merely a new id.
        elif (
            state["last_exit_at"] is None
            or context_start > _time(state["last_exit_at"])
        ) and _entry_allowed(region, direction, frame.bar, c):
            action = "ENTER_" + direction
            reason = "FRESH_PLAN_KEYBAR"
            plan = {
                k: region[k] for k in ("lower", "upper", "environment", "context_hash")
            }
            if author_region:
                plan.update(
                    {
                        key: region[key]
                        for key in (
                            "author_region_id",
                            "source",
                            "recovery_long",
                            "recovery_short",
                        )
                    }
                )
            plan.update(side=direction, created_index=index, created_at=t.isoformat())
            plan["plan_id"] = fingerprint(
                dict(
                    rules=rule_hash,
                    contract=c.contract,
                    region=plan,
                    signal=asdict(frame.bar),
                    confirmation=asdict(c),
                )
            )
    if action:
        proposed_plan = plan or state["plan"]
        p = dict(
            version=rules["version"],
            rule_hash=rule_hash,
            keybar_version=KEYBAR_VERSION,
            contract=c.contract,
            action=action,
            reason=reason,
            state_fingerprint=fingerprint(state),
            cycle_id=state["cycle_id"],
            plan_id=proposed_plan["plan_id"],
            signal_bar_end=frame.bar.end.isoformat(),
            generated_at=t.isoformat(),
            index=index,
            plan=proposed_plan,
            status="PENDING",
            executable=False,
        )
        if protection:
            p.update(signal_bar_end=None, protection_confirmation=fingerprint(asdict(protection)))
            if band:
                p.update(protection_band_scope=band.scope, protection_band_revision=band.revision)
        if exit_proof:
            p.update(signal_bar_end=None, carry_exit_evidence=fingerprint(asdict(exit_proof)))
        p["proposal_id"] = fingerprint(p)
        result.update(status="PROPOSAL", proposal=p)
    elif not held and not region_issue:
        result["status"] = "NO_ENTRY" if region["valid"] else "DEGENERATE_REGION"
    elif held and direction and not signal_fresh and result["status"] == "HOLD":
        result["status"] = "STALE_SIGNAL"
    return result


def _apply(state, p, t, clock):
    action = p["action"]
    before = Position(
        state["contract"], Decimal(state["long"]), Decimal(state["short"])
    )
    quantity = before.long + before.short if action == "CLEAR" else Decimal(1)
    pos = apply_action(before, Action(action, quantity))
    after = state | dict(
        long=str(pos.long),
        short=str(pos.short),
        since=t.isoformat(),
        known_at=t.isoformat(),
    )
    if action.startswith(("ENTER_", "REENTER_")):
        side = action.split("_")[-1]
        seq = state["cycle_seq"] + 1
        after.update(
            original_side=side,
            cycle_seq=seq,
            cycle_id=fingerprint(
                dict(version=p["version"], sequence=seq, proposal_id=p["proposal_id"])
            ),
            plan=p["plan"],
            attempt=state["attempt"] + 1 if action.startswith("REENTER_") else 1,
            entry_index=p["index"],
            last_exit_reason=None,
        )
        if p["version"] == MANAGEMENT_VERSION:
            after["management_entry_known_at"] = t.isoformat()
    elif action == "CLEAR":
        after.update(
            last_exit_at=t.isoformat(),
            last_exit_reason=p["reason"],
            cycle_id=None,
            entry_index=None,
        )
    if clock is not None:
        if action.startswith(("ENTER_", "REENTER_")) or action == "CLEAR":
            after["lock_intervals"] = []
        elif action == "LOCK":
            after["lock_intervals"] = [*state["lock_intervals"], [p["index"], None]]
        elif action.startswith("UNLOCK_"):
            *closed, (locked, _) = state["lock_intervals"]
            after["lock_intervals"] = [*closed, [locked, p["index"]]]
    return after


def replay(
    bars,
    decisions=None,
    *,
    as_of,
    checkpoint=None,
    timely_fixture=False,
    region_input=None,
    clock=None,
    protection_confirmations=None,
    protection_bands=None,
    carry_in=None,
    carry_exit_evidence=None,
    managed_lifecycle=False,
):
    """Append-only hypothesis replay; checkpoint recovery validates the entire prefix.

    Only explicit timely_fixture creates TEST_FIXTURE records. Human mode never
    generates decisions, and no accepted action is a broker or fill fact.
    A carry-in seed activates after its archival knowledge time and uses a proxy
    plan. The broker entry and original author's plan are unknown.
    """
    timestamp(as_of)
    if not isinstance(timely_fixture, bool):
        raise ValueError("BOOLEAN_MODE_REQUIRED")
    if region_input is not None and not isinstance(region_input, RegionInput):
        raise ValueError("REGION_INPUT_REQUIRED")
    external = protection_confirmations is not None
    scoped = protection_bands is not None
    if scoped and not external:
        raise ValueError("SCOPED_PROTECTION_REQUIRES_EXPLICIT_CONFIRMATIONS")
    explicit_exit = carry_exit_evidence is not None
    rules, rule_hash = _rules_for(
        region_input, clock, external, scoped, carry_in is not None, explicit_exit, managed_lifecycle,
    )
    visible = [b for b in bars if b.end + US <= as_of]
    if not visible:
        raise ValueError("VISIBLE_BARS_REQUIRED")
    _validate_prefix(visible)
    if region_input and any(
        r.zone.contract != visible[0].contract for r in region_input.regions
    ):
        raise ValueError("AUTHOR_REGION_CONTRACT_BOUNDARY")
    if external:
        protection_confirmations = _visible_protection(
            protection_confirmations, visible[0].contract, as_of=as_of, timely_fixture=timely_fixture,
        )
        if not scoped and any(isinstance(p, ScopedProtectionConfirmation) for p in protection_confirmations):
            raise ValueError("SCOPED_CONFIRMATION_REQUIRES_PROTECTION_BANDS")
    if scoped:
        protection_bands = visible_bands(protection_bands, visible[0].contract, as_of)
    if explicit_exit:
        carry_exit_evidence = _visible_carry_exits(
            carry_exit_evidence, visible[0].contract, as_of=as_of, timely_fixture=timely_fixture,
        )
    starting_state = initial_state(visible) if carry_in is None else _carry_in_state(visible, carry_in, as_of)
    state = starting_state
    supplied = list(decisions or [])
    if timely_fixture and supplied:
        raise ValueError("FIXTURE_MODE_DISALLOWS_EXTERNAL_DECISIONS")
    if checkpoint is not None:
        old = _time(checkpoint["as_of"])
        if old > as_of:
            raise ValueError("CHECKPOINT_TIME_REVERSED")
        prior = replay(
            bars,
            None if timely_fixture else checkpoint["decision_records"],
            as_of=old,
            timely_fixture=timely_fixture,
            region_input=region_input,
            clock=clock,
            protection_confirmations=protection_confirmations,
            protection_bands=protection_bands,
            carry_in=carry_in,
            carry_exit_evidence=carry_exit_evidence,
            managed_lifecycle=managed_lifecycle,
        )["checkpoint"]
        if prior != checkpoint:
            raise ValueError("CHECKPOINT_IDENTITY_MISMATCH")
        if not timely_fixture:
            for d in supplied:
                if d not in checkpoint["decision_records"]:
                    try:
                        late = _time(d["known_at"]) <= old
                    except (ValueError, TypeError, KeyError):
                        late = True
                    if late:
                        raise ValueError("LATE_DECISION_BEFORE_CHECKPOINT")
            supplied = checkpoint["decision_records"] + [
                d for d in supplied if d not in checkpoint["decision_records"]
            ]
    proposals = []
    evaluations = []
    outcomes = []
    transitions = []
    records = []
    groups = {}
    processed = {}
    for d in supplied:
        try:
            if not isinstance(d, dict):
                raise ValueError()
            t = _time(d["known_at"])
            if t > as_of:
                continue
            if not isinstance(d.get("decision_id"), str) or not d["decision_id"]:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            records.append(d)
            outcomes.append(dict(record=d, status="INVALID", reason="INVALID_DECISION"))
            continue
        if d not in records:
            records.append(d)
            if carry_in is not None and t <= carry_in.known_at:
                outcomes.append(dict(record=d, status="INVALID", reason="DECISION_NOT_AFTER_CARRY_IN_SEED",
                                     confirmation_delay_seconds=None))
                continue
            groups.setdefault(t, []).append(d)
    events = [(b.end + US, 0, i) for i, b in enumerate(visible)
              if carry_in is None or b.end + US > carry_in.known_at] + [
        (t, 2, ds) for t, ds in groups.items()
    ]
    if explicit_exit:
        events.extend(
            (t, 1, None) for t in {item.known_at + US for item in carry_exit_evidence}
            if t > carry_in.known_at
        )
    carry_scoped = rules["version"] == CARRY_SCOPED_PROTECTION_VERSION
    if carry_scoped:
        events.extend(
            (t, 1, None) for t in {band.effective_after + US for band in protection_bands}
            if carry_in.known_at < t <= as_of
        )
    events.sort(key=lambda x: (x[0], x[1]))

    def expire_carry_exit_proposal(p, t):
        if p["status"] != "PENDING":
            return False
        proof = p.get("carry_exit_evidence")
        pending_carry_management = (carry_scoped and p["action"] in ("LOCK", "UNLOCK_LONG", "UNLOCK_SHORT")
                                    and p["plan"].get("pricing_basis") == "PRESEED_CONTEXT_PROXY")
        if not proof and not pending_carry_management:
            return False
        visible_exits = _visible_carry_exits(
            carry_exit_evidence, state["contract"], as_of=t, timely_fixture=timely_fixture,
        )
        matches = _carry_exits_for_state(visible_exits, state)
        if proof and (len(matches) != 1 or fingerprint(asdict(matches[0])) != proof):
            p.update(status="EXPIRED", expired_at=t.isoformat(), expiry_reason="CARRY_IN_EXIT_EVIDENCE_CHANGED")
            return True
        if pending_carry_management and len(matches) == 1:
            p.update(status="EXPIRED", expired_at=t.isoformat(), expiry_reason="EXPLICIT_CARRY_IN_EXIT_TAKES_PRIORITY")
            return True
        return False

    def expire_scoped_proposal(p, t):
        if p["status"] == "PENDING" and p.get("protection_band_scope"):
            area, issue = active_band(protection_bands, t, state["original_side"])
            if area is None or area.scope != p["protection_band_scope"]:
                p.update(status="EXPIRED", expired_at=t.isoformat(),
                         expiry_reason=issue or "PROTECTION_RANGE_SUPERSEDED")
                return True
        if not (
            p["status"] == "PENDING"
            and p["action"].startswith(("ENTER_", "REENTER_"))
            and p["plan"].get("author_region_id")
        ):
            return False
        area, issue = region_input.resolve(
            visible[p["index"] - 1], t, timely_fixture=timely_fixture
        )
        if area is None or area.zone.id != p["plan"]["author_region_id"]:
            p.update(
                status="EXPIRED",
                expired_at=t.isoformat(),
                expiry_reason=issue or "AUTHOR_PLAN_RANGE_SUPERSEDED",
            )
            return True
        return False

    def expire_before_acceptance(p, t):
        if carry_scoped:
            return expire_carry_exit_proposal(p, t) or expire_scoped_proposal(p, t)
        return expire_scoped_proposal(p, t) or expire_carry_exit_proposal(p, t)

    def process(ds, t):
        nonlocal state
        for d in sorted(ds, key=fingerprint):
            p = None
            reason = "INVALID_DECISION"
            try:
                if not all(
                    isinstance(d.get(k), str) and d[k]
                    for k in ("decision_id", "proposal_id", "state_fingerprint")
                ):
                    raise ValueError()
                decided = _time(d["decided_at"])
                if (
                    t < decided
                    or d["decision"] not in ("ACCEPT", "REJECT")
                    or d["record_kind"]
                    not in ("HUMAN_RESEARCH_DECISION", "TEST_FIXTURE")
                ):
                    raise ValueError()
                if "recorded_at" in d:
                    _time(d["recorded_at"])
                if d["decision_id"] in processed and processed[
                    d["decision_id"]
                ] != fingerprint(d):
                    reason = "DECISION_ID_CONTENT_CONFLICT"
                elif (
                    (region_input is not None or clock is not None or external or carry_in is not None or managed_lifecycle)
                    and not timely_fixture
                    and d["record_kind"] != "HUMAN_RESEARCH_DECISION"
                ):
                    reason = "HUMAN_DECISION_REQUIRED"
                elif len(ds) > 1:
                    reason = "SAME_TIME_DECISION_CONFLICT"
                elif any(
                    d.get(k, v) != v
                    for k, v in dict(
                        version=rules["version"],
                        rule_hash=rule_hash,
                        keybar_version=KEYBAR_VERSION,
                        contract=state["contract"],
                        cycle_id=state["cycle_id"],
                    ).items()
                ):
                    reason = "IDENTITY_MISMATCH"
                else:
                    p = next(
                        (p for p in proposals if p["proposal_id"] == d["proposal_id"]),
                        None,
                    )
                    if p is None:
                        reason = "UNKNOWN_PROPOSAL"
                    elif d.get("plan_id", p["plan_id"]) != p["plan_id"]:
                        reason = "IDENTITY_MISMATCH"
                    elif p["status"] != "PENDING":
                        reason = "PROPOSAL_NOT_PENDING"
                    elif d["state_fingerprint"] != p["state_fingerprint"] or d[
                        "state_fingerprint"
                    ] != fingerprint(state):
                        reason = "STATE_MISMATCH"
                    elif decided <= _time(p["generated_at"]) or t <= _time(
                        p["generated_at"]
                    ):
                        reason = "DECISION_NOT_AFTER_PROPOSAL"
                    elif expire_before_acceptance(p, t):
                        reason = p["expiry_reason"]
                    elif d["decision"] == "REJECT":
                        p["status"] = "REJECTED"
                        reason = "REJECTED"
                    else:
                        before = state
                        state = _apply(state, p, t, clock)
                        p["status"] = "ACCEPTED"
                        reason = "ACCEPTED"
                        transitions.append(
                            dict(
                                proposal_id=p["proposal_id"],
                                decision_id=d["decision_id"],
                                action=p["action"],
                                reason=p["reason"],
                                known_at=t.isoformat(),
                                before=before,
                                after=state,
                                record_kind=d["record_kind"],
                            )
                        )
            except (ValueError, TypeError, KeyError):
                reason = "INVALID_DECISION"
            processed.setdefault(d["decision_id"], fingerprint(d))
            outcomes.append(
                dict(
                    record=d,
                    status=reason if reason in ("ACCEPTED", "REJECTED") else "INVALID",
                    reason=reason,
                    confirmation_delay_seconds=str(
                        (t - _time(p["generated_at"])).total_seconds()
                    )
                    if p
                    else None,
                )
            )

    for t, kind, payload in events:
        if kind == 1:
            for p in proposals:
                if carry_scoped:
                    expire_before_acceptance(p, t)
                else:
                    expire_carry_exit_proposal(p, t)
            continue
        if kind == 2:
            process(payload, t)
            continue
        for p in proposals:
            if p["status"] == "PENDING":
                p.update(status="EXPIRED", expired_at=t.isoformat())
        e = _evaluate(
            state,
            visible,
            payload,
            region_input=region_input,
            timely_fixture=timely_fixture,
            clock=clock,
            protection_confirmations=protection_confirmations,
            protection_bands=protection_bands,
            carry_exit_evidence=carry_exit_evidence,
            managed_lifecycle=managed_lifecycle,
        )
        evaluations.append({k: v for k, v in e.items() if k != "proposal"})
        if e["proposal"]:
            p = e["proposal"]
            proposals.append(p)
            ft = t + US
            if timely_fixture and ft <= as_of:
                d = dict(
                    decision_id="fixture-" + p["proposal_id"],
                    proposal_id=p["proposal_id"],
                    state_fingerprint=p["state_fingerprint"],
                    decision="ACCEPT",
                    decided_at=ft.isoformat(),
                    known_at=ft.isoformat(),
                    record_kind="TEST_FIXTURE",
                )
                records.append(d)
                process([d], ft)

    for p in proposals:
        expire_scoped_proposal(p, as_of)

    # Canonical chronological record order makes batch and resumed files identical.
    def record_key(record):
        try:
            return (1, _time(record["known_at"]), fingerprint(record))
        except (ValueError, TypeError, KeyError):
            return (0, as_of, fingerprint(record))

    records.sort(key=record_key)
    outcomes.sort(key=lambda outcome: record_key(outcome["record"]))
    cp = dict(
        version=rules["version"],
        rule_hash=rule_hash,
        as_of=as_of.isoformat(),
        mode="TIMELY_TEST_FIXTURE" if timely_fixture else "HUMAN_CONFIRMATION",
        input_prefix_hash=fingerprint([asdict(b) for b in visible]),
        cursor=len(visible),
        initial_state=starting_state,
        current_state=state,
        pending_proposals=[p for p in proposals if p["status"] == "PENDING"],
        decision_records=records,
        processed_decisions=[
            dict(
                decision_id=d.get("decision_id") if isinstance(d, dict) else None,
                content_hash=fingerprint(d),
            )
            for d in records
        ],
    )
    if region_input is not None:
        cp["region_prefix_hash"] = region_input.prefix_hash(as_of)
    if external:
        cp["protection_prefix_hash"] = fingerprint(sorted(
            fingerprint(asdict(item)) for item in protection_confirmations
        ))
    if scoped:
        cp["protection_band_prefix_hash"] = fingerprint(sorted(band.scope for band in protection_bands))
    if explicit_exit:
        cp["carry_exit_evidence_prefix_hash"] = fingerprint(sorted(
            fingerprint(asdict(item)) for item in carry_exit_evidence
        ))
    terminal = (
        "FLAT"
        if state["long"] == state["short"] == "0"
        else "OPEN_LOCKED"
        if state["long"] == state["short"]
        else "OPEN_DIRECTIONAL"
    )
    return dict(
        version=rules["version"],
        rule_hash=rule_hash,
        rules=deepcopy(rules),
        evaluations=evaluations,
        proposals=proposals,
        decisions=outcomes,
        transitions=transitions,
        current_state=state,
        terminal_status=terminal,
        checkpoint=cp,
        executable=False,
        fill=None,
        performance=None,
        cost=None,
        margin=None,
    )
