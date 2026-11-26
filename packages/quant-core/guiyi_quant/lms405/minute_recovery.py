"""Opt-in, research-only 1m recovery for an existing two-leg position."""

from dataclasses import asdict
from datetime import timedelta

from . import Bar, timestamp
from .handoff import Handoff, assess_handoff
from .public_conditions import Condition
from .recovery_permission import MinuteRecoveryPermission, current_permission, visible_permissions
from ..lms_confirmed_replay import fingerprint
from ..lms_keybar_approx import classify_research_period

VERSION = "lms405-minute-recovery-v1"
MINUTE = timedelta(minutes=1)
US = timedelta(microseconds=1)


def _visible(bars, contract, period, as_of):
    rows = []
    for bar in bars:
        if not isinstance(bar, Bar):
            raise ValueError("MINUTE_RECOVERY_BAR_REQUIRED")
        if bar.end + US >= as_of:
            continue
        if (bar.completed is not True or bar.contract != contract or bar.start is None
                or bar.end - bar.start != period * MINUTE or (rows and bar.start < rows[-1].end)):
            raise ValueError("MINUTE_RECOVERY_BAR_IDENTITY_MISMATCH")
        rows.append(bar)
    return rows


def _crossing(minutes, beyond, edge):
    """Find the start of this run; a gap or already-outside opening does not start it."""
    if len(minutes) < 3 or not all(beyond(bar.close, edge) for bar in minutes[-2:]):
        return None
    for previous, current in zip(reversed(minutes[:-1]), reversed(minutes[1:]), strict=True):
        if previous.end != current.start:
            return None
        if not beyond(previous.close, edge):
            return current
    return None


def _match_aggregate(bar, quotes):
    minutes = [quotes.get(bar.start + n * MINUTE) for n in range(5)]
    if not all(minutes):
        return False
    return (bar.open, bar.high, bar.low, bar.close) == (
        minutes[0].open, max(m.high for m in minutes), min(m.low for m in minutes), minutes[-1].close,
    )


def _signal(minutes, shapes, period, side, opened):
    confirm = minutes[-1]
    quotes = {bar.start: bar for bar in minutes}
    for index, shape in enumerate(shapes):
        if not (opened < shape.start and shape.end <= confirm.start and confirm.end <= shape.end + period * MINUTE):
            continue
        previous = shapes[index - 1] if index and shapes[index - 1].end == shape.start else None
        if period == 5 and (not _match_aggregate(shape, quotes)
                            or (previous is not None and not _match_aggregate(previous, quotes))):
            continue
        frame = classify_research_period(previous, shape, minutes=period)
        if not (frame.ibar or frame.pinbar == side):
            continue
        boundary = shape.high if side == "LONG" else shape.low
        followups = [quotes.get(shape.end + offset * MINUTE)
                     for offset in range((confirm.end - shape.end) // MINUTE)]
        if not all(followups):
            continue
        first = next((b for b in followups if _beyond(side, b.close, boundary)), None)
        if first == confirm:
            return dict(shape=shape, mother=previous, confirmation=confirm, boundary=boundary,
                        keybar_version=frame.rule_version)
    return None


def _beyond(side, price, edge):
    return price > edge if side == "LONG" else price < edge


def assess_minute_recovery(request, minutes, five_minutes=(), *, permissions=(), as_of, facts=(), approval=None,
                           version_405=None, allow_test_fixture=False):
    """Assess the latest completed minute. Expired or superseded proposals cannot be accepted later."""
    timestamp(as_of)
    if not isinstance(request, Handoff) or request.route != "RESUME_ORIGINAL":
        raise ValueError("MINUTE_RECOVERY_REQUIRES_LOCKED_HANDOFF")
    contract = request.before.contract
    state = dict(contract=contract, plan={"plan_id": request.plan_id}, cycle_id=request.cycle_id,
                 original_side=request.original_side, since=request.position_since.isoformat())
    records = visible_permissions(permissions, contract, as_of=as_of, timely_fixture=allow_test_fixture,
                                  record_type=MinuteRecoveryPermission)
    permit, issue = current_permission(records, state, as_of)
    result = dict(version=VERSION, proposal=None, after=None, executable=False)
    if request.position_known_at >= as_of:
        return result | dict(status="LOCK_NOT_YET_KNOWN")
    if issue:
        return result | dict(status=issue)
    rows = _visible(minutes, contract, 1, as_of)
    if not rows:
        return result | dict(status="MINUTE_DATA_UNAVAILABLE")
    confirm = rows[-1]
    observed = confirm.end + US
    if as_of > observed + MINUTE:
        return result | dict(status="MINUTE_CONFIRMATION_STALE")
    opened = max(permit.known_at, request.position_known_at)
    crossing = _crossing(rows, lambda price, edge: _beyond(request.original_side, price, edge), permit.edge)
    if crossing is None or crossing.start <= opened:
        return result | dict(status="MINUTE_FRESH_PRICE_RETURN_UNCONFIRMED")
    period = permit.shape_minutes
    shapes = rows if period == 1 else _visible(five_minutes, contract, 5, as_of)
    signal = _signal(rows, shapes, period, request.original_side, opened)
    if signal is None:
        return result | dict(status="MINUTE_KEYBAR_UNCONFIRMED")
    evidence = dict(permission=permit.identity, shape_minutes=period, crossing=asdict(crossing),
                    signal={key: asdict(value) if isinstance(value, Bar) else value for key, value in signal.items()})
    proposal_source = VERSION + ":" + fingerprint(evidence)
    public = Condition("SIGNAL", request.scope, contract, True, confirm.end, observed, proposal_source, "EVENT_TIME")
    facts = tuple(facts)
    if any(not isinstance(fact, Condition) or fact.name == "SIGNAL" for fact in facts):
        raise ValueError("MINUTE_RECOVERY_SIGNAL_COMPUTED_FROM_BARS")
    outcome = assess_handoff(request, (public, *facts), as_of=as_of, source=proposal_source,
                             source_available_at=observed, version_405=version_405, approval=approval,
                             allow_test_fixture=allow_test_fixture)
    proposal = dict(source=proposal_source, available_at=observed, action="UNLOCK_" + request.original_side,
                    permission_id=permit.identity, endpoint=permit.endpoint, price_edge=permit.edge,
                    shape_minutes=period, confirmation_minutes=1, shape_start=signal["shape"].start,
                    crossing_end=crossing.end, confirmed_at=confirm.end,
                    approval_scope=request.confirmation_scope(proposal_source, observed, version_405))
    return outcome | dict(version=VERSION, proposal=proposal)
