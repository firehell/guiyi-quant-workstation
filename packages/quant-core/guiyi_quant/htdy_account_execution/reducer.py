"""Pure account reducer. Its effects are inert proposals, never native requests."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from . import model as m
from .codec import digest

ZERO = Decimal(0)
TERMINAL = ("FILLED", "CANCELLED", "REJECTED", "LOCAL_ABORTED")


def product(state, name):
    for p in state.products:
        if p.product == name:
            return p
    raise ValueError("PRODUCT_OUT_OF_SCOPE")


def position(state, name):
    return next((p for p in state.positions if p.product == name), None)


def replace_product(state, p):
    return replace(
        state,
        products=tuple(
            p if old.product == p.product else old for old in state.products
        ),
    )


def replace_order(state, o):
    return replace(
        state,
        orders=tuple(o if old.order_id == o.order_id else old for old in state.orders),
    )


def has_fill(state, o):
    return any(f.order_id == o.order_id for f in state.fills)


def unsettled(state, o):
    return o.status not in TERMINAL or not o.reconciled and not has_fill(state, o)


def abandon(state, p, source=None):
    identity = source or p.signal_id
    state = replace(
        state,
        abandoned=tuple(
            sorted(set(state.abandoned) | ({identity} if identity else set()))
        ),
    )
    if identity == p.signal_id:
        state = replace_product(state, replace(p, opening_consumed=True))
    return state


def cancel_opens(state, name=None):
    return replace(
        state,
        orders=tuple(
            replace(o, cancel_required=True)
            if o.offset == "OPEN"
            and (name is None or o.product == name)
            and unsettled(state, o)
            else o
            for o in state.orders
        ),
    )


def start(account_id, products, at, readback):
    m.text(account_id)
    m.time(at)
    if (
        type(readback) is not m.Readback
        or readback.snapshot.account_id != account_id
        or not readback.at <= at < readback.valid_until
        or not readback.complete
    ):
        raise ValueError("INITIAL_READBACK_INVALID")
    if (
        type(products) is not tuple
        or not products
        or len(set(products)) != len(products)
    ):
        raise ValueError("UNIVERSE_INVALID")
    if (
        readback.snapshot.positions
        or readback.used_margin
        or readback.frozen_margin
        or readback.frozen_fee
        or readback.coverage
        or any(o.status not in TERMINAL for o in readback.snapshot.orders)
    ):
        raise ValueError("ACCOUNT_MUST_START_FLAT")
    state = m.State(
        account_id,
        at,
        readback,
        readback,
        tuple(m.Product(p) for p in products),
        clock=at,
    )
    validate(state)
    return state


def signal(state, cmd):
    p = product(state, cmd.product)
    if any(
        s.source_id == cmd.source_id
        and (s.product, s.bar_end) != (cmd.product, cmd.bar_end)
        for s in state.signals
    ):
        raise ValueError("SOURCE_IDENTITY_CONFLICT")
    if any((s.product, s.bar_end) == (cmd.product, cmd.bar_end) for s in state.signals):
        return state, "FROZEN_BAR_IGNORED"
    state = replace(state, signals=state.signals + (cmd,))
    if (
        cmd.bar_end <= state.activated_at
        or p.wait_after is not None
        and cmd.bar_end <= p.wait_after
    ):
        return state, "PRE_ACTIVATION_OR_RECOVERY_IGNORED"
    if cmd.contract != p.owner:
        return replace(
            state,
            blocked_products=tuple(sorted(set(state.blocked_products) | {p.product})),
        ), "OWNER_MISMATCH"
    if p.last_bar is not None and (
        cmd.bar_end <= p.last_bar or cmd.previous_bar_end != p.last_bar
    ):
        return replace(
            state,
            blocked_products=tuple(sorted(set(state.blocked_products) | {p.product})),
        ), "OBSERVATION_GAP"
    p = replace(p, last_bar=cmd.bar_end)
    state = replace_product(state, p)
    if state.phase != "READY" or p.product in state.blocked_products or p.rolling:
        return state, "SIGNAL_BLOCKED"
    if not cmd.directions:
        return state, "HOLD"
    if len(cmd.directions) > 1:
        held = position(state, p.product)
        state = replace_product(
            state,
            replace(
                p,
                desired=0 if p.must_close else held.quantity if held else 0,
                signal_id=cmd.source_id,
                signal_at=cmd.observed_at,
                opening_consumed=True,
            ),
        )
        return cancel_opens(state, p.product), "SIGNAL_CONFLICT"
    return replace_product(
        state,
        replace(
            p,
            desired=1 if cmd.directions == ("buy",) else -1,
            signal_id=cmd.source_id,
            signal_at=cmd.observed_at,
            opening_consumed=False,
        ),
    ), "TARGET_UPDATED"


def fill_follows_order(fill, order):
    if type(fill) is m.NativeFill:
        return (
            fill.request_started_at >= order.created_at
            and fill.filled_at + timedelta(seconds=1) > fill.request_started_at
        )
    return fill.filled_at > order.created_at


def apply_fill(state, cmd):
    if cmd.account_id != state.account_id:
        raise ValueError("FILL_ACCOUNT_MISMATCH")
    old = next((f for f in state.fills if f.trade_id == cmd.trade_id), None)
    if old:
        if old != cmd:
            raise ValueError("FILL_IDENTITY_CONFLICT")
        return state, "DUPLICATE_FILL"
    o = next((o for o in state.orders if o.order_id == cmd.order_id), None)
    if o is None:
        return cancel_opens(
            replace(
                state,
                fills=state.fills + (cmd,),
                unresolved_fill_ids=state.unresolved_fill_ids + (cmd.trade_id,),
                phase="BLOCKED",
            )
        ), "UNKNOWN_NATIVE_FILL_RETAINED"
    if (
        any(
            type(audit.command) is m.ManualBeginV1
            and audit.command.test_id == o.signal_id
            for audit in state.audit
        )
        and type(cmd) is not m.NativeFill
    ):
        raise ValueError("MANUAL_NATIVE_FILL_REQUIRED")
    if cmd.contract != o.contract or not fill_follows_order(cmd, o):
        raise ValueError("FILL_ORDER_OR_TIMING_INVALID")
    if has_fill(state, o):
        raise ValueError("FILL_CAPACITY_CONFLICT")
    p = product(state, o.product)
    held = position(state, o.product)
    conflict = (
        o.offset == "OPEN"
        and held is not None
        or o.offset == "CLOSE"
        and (
            held is None
            or held.contract != o.contract
            or held.quantity != (1 if o.side == "SELL" else -1)
        )
    )
    state = replace(state, fills=state.fills + (cmd,))
    late = o.status in ("CANCELLED", "REJECTED", "LOCAL_ABORTED")
    if late:
        state = replace(
            state,
            reservations=tuple(
                replace(r, released=False, release_source="")
                if r.order_id == o.order_id
                else r
                for r in state.reservations
            ),
        )
    state = replace_order(
        state,
        replace(o, status="FILLED", terminal_at=cmd.recorded_at, reconciled=False),
    )
    if conflict:
        return cancel_opens(
            replace(
                state,
                unresolved_fill_ids=state.unresolved_fill_ids + (cmd.trade_id,),
                phase="BLOCKED",
            )
        ), "NATIVE_FILL_PROJECTION_CONFLICT"
    positions = tuple(old for old in state.positions if old.product != o.product)
    if o.offset == "OPEN":
        positions += (m.Position(o.product, o.contract, 1 if o.side == "BUY" else -1),)
    else:
        state = replace_product(state, replace(p, must_close=False))
    state = replace(state, positions=positions)
    if late:
        state = cancel_opens(replace(state, phase="RECOVERY_REQUIRED"))
    return state, "NATIVE_FILL_RECORDED"


def order_update(state, cmd):
    if cmd.account_id != state.account_id:
        raise ValueError("ORDER_ACCOUNT_MISMATCH")
    previous = next((u for u in state.updates if u.source_id == cmd.source_id), None)
    if previous:
        if previous != cmd:
            raise ValueError("ORDER_SOURCE_CONFLICT")
        return state, "DUPLICATE_ORDER_UPDATE"
    state = replace(state, updates=state.updates + (cmd,))
    o = next((o for o in state.orders if o.order_id == cmd.order_id), None)
    if o is None:
        return cancel_opens(replace(state, phase="BLOCKED")), "UNKNOWN_EXTERNAL_ORDER"
    if (
        cmd.at < o.created_at
        or cmd.accepted_at is not None
        and cmd.accepted_at < o.created_at
    ):
        raise ValueError("ORDER_TIME_INVALID")
    if (
        o.accepted_at is not None
        and cmd.accepted_at is not None
        and o.accepted_at != cmd.accepted_at
    ):
        raise ValueError("ACCEPTANCE_IDENTITY_CONFLICT")
    accepted = o.accepted_at or cmd.accepted_at
    if has_fill(state, o):
        if cmd.status != "FILLED":
            return cancel_opens(
                replace(state, phase="RECOVERY_REQUIRED")
            ), "LATE_ORDER_REPORT_CONFLICT"
        return state, "FILLED_ORDER_ALREADY_RECORDED"
    if o.status in TERMINAL and cmd.status == "FILLED" and o.status != "FILLED":
        # A definite one-lot native fill report supersedes cancellation, but is not
        # a priced/fee-complete Fill. Relock occupancy immediately and await facts.
        state = replace_order(
            state, replace(o, status="FILLED", terminal_at=cmd.at, reconciled=False)
        )
        state = replace(
            state,
            reservations=tuple(
                replace(r, released=False, release_source="")
                if r.order_id == o.order_id
                else r
                for r in state.reservations
            ),
            phase="RECOVERY_REQUIRED",
            readback_valid=False,
        )
        return cancel_opens(state), "LATE_NATIVE_FILLED_REPORT_RETAINED"
    if o.status in TERMINAL and cmd.status != o.status:
        return cancel_opens(
            replace(state, phase="RECOVERY_REQUIRED")
        ), "TERMINAL_REPORT_CONFLICT"
    status = (
        "CANCEL_PENDING" if o.cancel_sent and cmd.status == "WORKING" else cmd.status
    )
    o = replace(
        o,
        status=status,
        accepted_at=accepted,
        terminal_at=cmd.at if status in TERMINAL else o.terminal_at,
    )
    state = replace_order(state, o)
    if status == "REJECTED":
        if o.offset == "OPEN":
            state = abandon(state, product(state, o.product), o.signal_id)
        state = replace(state, phase="RECOVERY_REQUIRED")
    elif status == "UNKNOWN":
        state = replace(state, phase="RECOVERY_REQUIRED")
    elif status == "FILLED":
        # A normal terminal order callback is a pending fill/readback, not a fault.
        # Preserve the latest target; prohibit every action until native facts reconcile.
        state = replace(state, readback_valid=False)
    return state, "ORDER_UPDATE_RECORDED"


def apply_readback(state, cmd):
    if cmd.snapshot.account_id != state.account_id:
        raise ValueError("ACCOUNT_IDENTITY_INVALID")
    if not cmd.complete:
        return replace(
            state, phase="RECOVERY_REQUIRED", readback_valid=False
        ), "READBACK_INCOMPLETE"
    baseline = state.initial_readback.snapshot.orders
    native = {r.order_id: r for r in cmd.snapshot.orders}
    known = {o.order_id: o for o in state.orders}
    if state.unresolved_fill_ids:
        return replace(
            state, phase="BLOCKED", readback_valid=False
        ), "UNRESOLVED_NATIVE_FILL"
    if (
        set(cmd.confirmed_trade_ids)
        - {f.trade_id for f in state.fills}
        - set(state.initial_readback.confirmed_trade_ids)
    ):
        return cancel_opens(
            replace(state, phase="BLOCKED", readback_valid=False)
        ), "UNEXPLAINED_EXTERNAL_TRADE"
    if sorted(cmd.snapshot.positions, key=lambda p: p.product) != sorted(
        state.positions, key=lambda p: p.product
    ) or any(
        r.order_id not in known and r not in baseline for r in cmd.snapshot.orders
    ):
        return cancel_opens(
            replace(state, phase="BLOCKED", readback_valid=False)
        ), "ACCOUNT_RECONCILIATION_MISMATCH"
    if state.positions and cmd.used_margin <= 0:
        return replace(
            state, phase="RECOVERY_REQUIRED", readback_valid=False
        ), "POSITION_MARGIN_UNPROVEN"
    for c in cmd.coverage:
        o = known.get(c.order_id)
        r = next((r for r in state.reservations if r.order_id == c.order_id), None)
        if (
            o is None
            or o.offset != "OPEN"
            or r is None
            or r.released
            or c.margin > r.margin
            or c.fee > r.fee
            or c.order_id not in native
            or native[c.order_id].status not in ("WORKING", "UNKNOWN")
        ):
            raise ValueError("COVERAGE_IDENTITY_INVALID")
    orders = []
    released = set()
    for o in state.orders:
        r = native.get(o.order_id)
        if o.reconciled and r is None:
            orders.append(o)
            continue
        if r is None:
            return replace(
                state, phase="RECOVERY_REQUIRED", readback_valid=False
            ), "ORDER_OUTCOME_MISSING"
        filled = next((f for f in state.fills if f.order_id == o.order_id), None)
        if filled:
            if (
                r.status != "FILLED"
                or filled.trade_id not in cmd.confirmed_trade_ids
                or cmd.at < filled.recorded_at
            ):
                return replace(
                    state, phase="RECOVERY_REQUIRED", readback_valid=False
                ), "FILL_READBACK_UNPROVEN"
            o = replace(o, status="FILLED", reconciled=True)
            released.add(o.order_id)
        elif r.status == "FILLED":
            return replace(
                state, phase="RECOVERY_REQUIRED", readback_valid=False
            ), "NATIVE_TRADE_MISSING"
        elif r.status in ("CANCELLED", "REJECTED"):
            if (
                o.order_id not in cmd.snapshot.settled_order_ids
                or o.terminal_at is not None
                and cmd.at < o.terminal_at
            ):
                return replace(
                    state, phase="RECOVERY_REQUIRED", readback_valid=False
                ), "CANCEL_TRADE_RECONCILIATION_REQUIRED"
            o = replace(
                o, status=r.status, reconciled=True, terminal_at=o.terminal_at or cmd.at
            )
            released.add(o.order_id)
        elif r.status == "UNKNOWN":
            return replace(
                state, phase="RECOVERY_REQUIRED", readback_valid=False
            ), "ORDER_OUTCOME_UNKNOWN"
        elif r.status == "WORKING":
            if o.status in TERMINAL:
                return replace(
                    state, phase="RECOVERY_REQUIRED", readback_valid=False
                ), "TERMINAL_ORDER_READBACK_CONFLICT"
            o = replace(o, status="CANCEL_PENDING" if o.cancel_sent else "WORKING")
        orders.append(o)
    reservations = tuple(
        replace(r, released=True, release_source=cmd.source_id)
        if r.order_id in released
        else r
        for r in state.reservations
    )
    return replace(
        state,
        readback=cmd,
        orders=tuple(orders),
        reservations=reservations,
        readback_valid=True,
    ), "READBACK_RECONCILED"


def recover(state, cmd):
    state, reason = apply_readback(state, cmd.readback)
    if not state.readback_valid or state.unresolved_fill_ids:
        return state, reason
    proofs = {p.product: p for p in cmd.inputs}
    blocked = []
    for name in proofs:
        product(state, name)
    for p in state.products:
        proof = proofs.get(p.product)
        held = position(state, p.product)
        verified = proof is not None and proof.contract == p.owner
        if not verified:
            blocked.append(p.product)
        elif (
            proof.bar_end >= cmd.at
            or p.last_bar is not None
            and proof.bar_end < p.last_bar
        ):
            raise ValueError("RECOVERY_INPUT_CUTOFF_INVALID")
        qty = held.quantity if held else 0
        close = (
            p.must_close or p.rolling or verified and proof.latest_direction * qty == -1
        )
        state = abandon(state, p)
        p = replace(
            product(state, p.product),
            desired=0 if close else qty,
            must_close=bool(qty) and close,
            opening_consumed=True,
            signal_at=cmd.at,
            signal_id="recovery:" + proof.source_id if verified else "",
            wait_after=cmd.at,
            last_bar=proof.bar_end
            if proof and p.product not in blocked
            else p.last_bar,
        )
        state = replace_product(state, p)
    return cancel_opens(
        replace(state, phase="READY", blocked_products=tuple(blocked))
    ), "RECOVERED_NO_HISTORICAL_OPEN"


def recover_product(state, cmd):
    if state.phase != "READY" or not state.readback_valid:
        raise ValueError("ACCOUNT_RECOVERY_REQUIRED")
    blocked = set(state.blocked_products)
    if set(cmd.products) - blocked:
        raise ValueError("PRODUCT_NOT_BLOCKED")
    for name in cmd.products:
        product(state, name)
    state, reason = apply_readback(state, cmd.readback)
    if state.phase != "READY" or not state.readback_valid:
        return state, reason
    proofs = {proof.product: proof for proof in cmd.inputs}
    recovered = False
    for name in cmd.products:
        p = product(state, name)
        proof = proofs.get(name)
        if proof is None or proof.contract != p.owner:
            continue
        if (
            proof.bar_end >= cmd.at
            or p.last_bar is not None
            and proof.bar_end < p.last_bar
        ):
            raise ValueError("RECOVERY_INPUT_CUTOFF_INVALID")
        held = position(state, name)
        qty = held.quantity if held else 0
        close = p.must_close or p.rolling or proof.latest_direction * qty == -1
        state = abandon(state, p)
        p = replace(
            product(state, name),
            desired=0 if close else qty,
            must_close=bool(qty) and close,
            opening_consumed=True,
            signal_at=cmd.at,
            signal_id="recovery:" + proof.source_id,
            wait_after=cmd.at,
            last_bar=proof.bar_end,
        )
        state = cancel_opens(replace_product(state, p), name)
        blocked.remove(name)
        recovered = True
    return replace(state, blocked_products=tuple(sorted(blocked))), (
        "PRODUCT_RECOVERED_NO_HISTORICAL_OPEN"
        if recovered
        else "PRODUCT_RECOVERY_PENDING"
    )


def _manual_begin(state, test_id):
    begins = [
        audit.command
        for audit in state.audit
        if type(audit.command) is m.ManualBeginV1 and audit.command.test_id == test_id
    ]
    if len(begins) != 1:
        raise ValueError("MANUAL_TEST_IDENTITY_INVALID")
    return begins[0]


def _manual_confirmed_at(state, order, fill, *, closed=False):
    """The first successful full native readback, retained in the audit."""
    accepted = {
        "READBACK_RECONCILED",
        "RECOVERED_NO_HISTORICAL_OPEN",
        "PRODUCT_RECOVERED_NO_HISTORICAL_OPEN",
    }
    for audit in state.audit:
        if audit.reason not in accepted:
            continue
        command = audit.command
        readback = (
            command
            if type(command) is m.Readback
            else (
                command.readback
                if type(command) in (m.Recover, m.ProductRecoveryV1)
                else None
            )
        )
        if readback is None or not readback.complete or readback.at < fill.recorded_at:
            continue
        native_order = next(
            (
                native
                for native in readback.snapshot.orders
                if native.order_id == order.order_id
            ),
            None,
        )
        native_position = any(
            held.product == order.product
            and held.contract == order.contract
            and held.quantity == 1
            for held in readback.snapshot.positions
        )
        if (
            native_order is not None
            and native_order.status == "FILLED"
            and fill.trade_id in readback.confirmed_trade_ids
            and (not native_position if closed else native_position)
        ):
            return readback.at
    return None


def manual_status(state, test_id):
    m.manual_test_id(test_id)
    begin = _manual_begin(state, test_id)
    opens = [o for o in state.orders if o.signal_id == test_id and o.offset == "OPEN"]
    closes = [o for o in state.orders if o.signal_id == test_id and o.offset == "CLOSE"]
    if len(opens) > 1 or any(
        o.product != begin.product or o.contract != begin.contract
        for o in opens + closes
    ):
        raise ValueError("MANUAL_ORDER_IDENTITY_INVALID")
    close_ids = tuple(o.order_id for o in closes)

    def result(
        phase, *, confirmed_at=None, due_at=None, terminal=False, complete=False
    ):
        return m.ManualStatusV1(
            phase,
            due_at,
            opens[0].order_id if opens else None,
            close_ids,
            confirmed_at,
            complete,
            terminal,
        )

    if not opens:
        if test_id in state.abandoned:
            return result("OPEN_REJECTED", terminal=True)
        if state.clock >= begin.open_until:
            return result("OPEN_EXPIRED", terminal=True)
        return result("WAIT_OPEN")
    opening = opens[0]
    open_fill = next((f for f in state.fills if f.order_id == opening.order_id), None)
    if open_fill is None:
        if opening.reconciled and opening.status in (
            "CANCELLED",
            "REJECTED",
            "LOCAL_ABORTED",
        ):
            return result("OPEN_NO_FILL", terminal=True)
        return result("OPEN_PENDING")
    if not opening.reconciled:
        return result("OPEN_UNCONFIRMED")
    confirmed_at = _manual_confirmed_at(state, opening, open_fill)
    if confirmed_at is None:
        return result("OPEN_UNCONFIRMED")
    due_at = confirmed_at + timedelta(seconds=begin.hold_seconds)
    if closes:
        for closing in closes:
            close_fill = next(
                (f for f in state.fills if f.order_id == closing.order_id), None
            )
            if (
                closing.reconciled
                and close_fill is not None
                and _manual_confirmed_at(state, closing, close_fill, closed=True)
                is not None
                and not state.positions
            ):
                return result(
                    "COMPLETE",
                    confirmed_at=confirmed_at,
                    due_at=due_at,
                    terminal=True,
                    complete=True,
                )
        return result("CLOSE_PENDING", confirmed_at=confirmed_at, due_at=due_at)
    return result(
        "CLOSE_DUE" if state.clock >= due_at else "HOLDING",
        confirmed_at=confirmed_at,
        due_at=due_at,
    )


def manual_begin(state, cmd):
    if any(type(audit.command) is m.ManualBeginV1 for audit in state.audit):
        raise ValueError("MANUAL_TEST_ALREADY_STARTED")
    p = product(state, cmd.product)
    if (
        p.owner != cmd.contract
        or state.phase != "READY"
        or not state.readback_valid
        or not state.readback.complete
        or not valid(state.readback, cmd.at)
        or state.positions
        or state.readback.snapshot.positions
        or any(order.offset == "OPEN" for order in state.orders)
        or any(not order.reconciled for order in state.orders)
        or any(not reservation.released for reservation in state.reservations)
        or state.readback.used_margin
        or state.readback.frozen_margin
        or state.readback.frozen_fee
        or state.readback.coverage
        or state.unresolved_fill_ids
        or any(
            native.status not in ("FILLED", "CANCELLED", "REJECTED")
            for native in state.readback.snapshot.orders
        )
    ):
        raise ValueError("MANUAL_ACCOUNT_NOT_FLAT_READY")
    return state, "MANUAL_TEST_BEGUN"


def manual_tick(state, cmd, key):
    begin = _manual_begin(state, cmd.test_id)
    if len(cmd.inputs) > 1 or any(
        f.instrument.contract != begin.contract for f in cmd.inputs
    ):
        raise ValueError("MANUAL_EXECUTION_SCOPE_INVALID")
    if (
        any(
            held.product != begin.product
            or held.contract != begin.contract
            or held.quantity != 1
            for held in state.positions
        )
        or any(not o.reconciled and o.signal_id != begin.test_id for o in state.orders)
        or any(
            not r.released
            and next(
                (o.signal_id for o in state.orders if o.order_id == r.order_id), None
            )
            != begin.test_id
            for r in state.reservations
        )
    ):
        raise ValueError("MANUAL_ACCOUNT_SCOPE_CHANGED")
    status = manual_status(state, cmd.test_id)
    if status.terminal:
        return state, (), "MANUAL_TEST_TERMINAL"
    if state.phase != "READY" or not state.readback_valid:
        return state, (), "MANUAL_ACCOUNT_READBACK_REQUIRED"
    if not valid(state.readback, cmd.at):
        return (
            replace(state, phase="RECOVERY_REQUIRED", readback_valid=False),
            (),
            "MANUAL_ACCOUNT_READBACK_REQUIRED",
        )
    p = product(state, begin.product)
    if p.owner != begin.contract and status.open_order_id is None:
        raise ValueError("MANUAL_OWNER_CHANGED_BEFORE_OPEN")
    if status.phase == "WAIT_OPEN" and (state.positions or cmd.at >= begin.open_until):
        return state, (), "MANUAL_OPEN_WINDOW_EXPIRED"
    opening = status.phase == "WAIT_OPEN"
    closing = status.phase == "CLOSE_PENDING" or (
        status.due_at is not None and cmd.at >= status.due_at
    )
    shadow = replace_product(
        state,
        replace(
            p,
            desired=0 if closing else 1,
            signal_id=begin.test_id,
            signal_at=status.confirmed_at or begin.at,
            opening_consumed=False
            if opening or status.phase == "OPEN_PENDING"
            else True,
            must_close=closing,
            rolling=False,
        ),
    )
    # A strategy-input block is not authority over this explicit manual test.
    # Keep the original tuple in the committed state; it must not cancel the
    # already accepted manual OPEN on the next tick.
    shadow = replace(
        shadow,
        blocked_products=tuple(
            name for name in shadow.blocked_products if name != begin.product
        ),
    )
    if status.phase == "OPEN_PENDING" and cmd.at >= begin.open_until:
        pending = next(o for o in shadow.orders if o.order_id == status.open_order_id)
        shadow = replace_order(shadow, replace(pending, cancel_required=True))
    shadow, effects, _ = tick(
        shadow,
        cmd,
        key,
        opening_allowed=opening
        or (status.phase == "OPEN_PENDING" and cmd.at < begin.open_until),
        serialized_submit=True,
        policy_version=m.MANUAL_TEST_POLICY_VERSION,
    )
    if any(
        effect.order.signal_id != begin.test_id or effect.order.product != begin.product
        for effect in effects
    ):
        raise ValueError("MANUAL_EFFECT_SCOPE_INVALID")
    return (
        replace(
            shadow, products=state.products, blocked_products=state.blocked_products
        ),
        effects,
        "MANUAL_TICK",
    )


def local_occupancy(state):
    coverage = {c.order_id: c for c in state.readback.coverage}
    margin = fee = ZERO
    for r in state.reservations:
        if r.released:
            continue
        covered = coverage.get(r.order_id)
        margin += r.margin - (covered.margin if covered else ZERO)
        fee += r.fee - (covered.fee if covered else ZERO)
    return margin, fee


def valid(fact, at):
    return fact.at <= at < fact.valid_until


def tick(
    state,
    cmd,
    key,
    *,
    opening_allowed=True,
    serialized_submit=False,
    policy_version=None,
):
    facts = {i.instrument.contract: i for i in cmd.inputs}
    effects = []
    if not valid(state.readback, cmd.at):
        state = replace(state, phase="RECOVERY_REQUIRED", readback_valid=False)
    # A reverse OPEN expires even while its CLOSE is still in flight.
    for p in state.products:
        f = facts.get(p.owner)
        if (
            p.desired
            and p.signal_id
            and f
            and valid(f.session, cmd.at)
            and cmd.at >= f.session.final_close_at - timedelta(seconds=60)
        ):
            state = abandon(state, p)
    # Cutoff / changed target / timeout cancellation precedes all submissions.
    for old in state.orders:
        o = next(o for o in state.orders if o.order_id == old.order_id)
        if not unsettled(state, o):
            continue
        p = product(state, o.product)
        f = facts.get(o.contract)
        if o.offset == "OPEN":
            if not opening_allowed:
                o = replace(o, cancel_required=True)
            if (
                f
                and valid(f.session, cmd.at)
                and cmd.at >= f.session.final_close_at - timedelta(seconds=60)
            ):
                state = abandon(state, p, o.signal_id)
                p = product(state, p.product)
                o = replace(o, cancel_required=True)
            if (
                p.opening_consumed
                or o.signal_id in state.abandoned
                or p.rolling
                or p.product in state.blocked_products
                or p.desired != (1 if o.side == "BUY" else -1)
            ):
                o = replace(o, cancel_required=True)
        if o.accepted_at is not None and cmd.at >= o.accepted_at + timedelta(
            seconds=180
        ):
            o = replace(o, cancel_required=True)
        state = replace_order(state, o)
        if (
            o.cancel_required
            and not o.cancel_sent
            and o.status not in TERMINAL
            and o.accepted_at is not None
            and state.readback_valid
            and f
            and valid(f.session, cmd.at)
            and f.session.can_cancel
        ):
            o = replace(o, cancel_sent=True, status="CANCEL_PENDING")
            state = replace_order(state, o)
            effects.append(m.Effect("CANCEL", o))
    if state.phase != "READY" or not state.readback_valid:
        return state, tuple(effects), "ACCOUNT_READBACK_REQUIRED"
    for initial in sorted(
        state.products, key=lambda p: (p.signal_at or state.activated_at, p.product)
    ):
        p = product(state, initial.product)
        held = position(state, p.product)
        active = [
            o for o in state.orders if o.product == p.product and unsettled(state, o)
        ]
        if active:
            continue
        if p.rolling and held is None:
            state = replace_product(
                state,
                replace(
                    p,
                    rolling=False,
                    desired=0,
                    must_close=False,
                    opening_consumed=True,
                    wait_after=cmd.at,
                ),
            )
            continue
        if held and (p.must_close or p.rolling or held.quantity != p.desired):
            offset, contract, order_side = (
                "CLOSE",
                held.contract,
                "SELL" if held.quantity > 0 else "BUY",
            )
        elif (
            held is None
            and p.desired
            and not p.opening_consumed
            and p.signal_id not in state.abandoned
        ):
            offset, contract, order_side = (
                "OPEN",
                p.owner,
                "BUY" if p.desired > 0 else "SELL",
            )
        else:
            continue
        if serialized_submit and any(not order.reconciled for order in state.orders):
            continue
        if p.signal_at is None or cmd.at <= p.signal_at:
            continue
        f = facts.get(contract)
        if not f or not valid(f.session, cmd.at):
            continue
        if offset == "OPEN" and cmd.at >= f.session.final_close_at - timedelta(
            seconds=60
        ):
            state = abandon(state, p)
            continue
        if not f.session.can_trade or cmd.at >= f.session.final_close_at:
            continue
        if p.product in state.blocked_products and offset == "OPEN":
            continue
        if offset == "OPEN" and not opening_allowed:
            continue
        q = f.quote
        i = f.instrument
        if not q or not valid(q, cmd.at) or not valid(i, cmd.at):
            continue
        price = q.ask if order_side == "BUY" else q.bid
        if (
            q.ask_volume if order_side == "BUY" else q.bid_volume
        ) < 1 or price % i.tick_size:
            continue
        margin = ZERO
        if offset == "OPEN":
            if not valid(state.readback, cmd.at) or any(
                f.recorded_at > state.readback.at for f in state.fills
            ):
                continue
            local, fees = local_occupancy(state)
            margin = (
                price
                * i.multiplier
                * (i.long_margin_rate if order_side == "BUY" else i.short_margin_rate)
            )
            projected = (
                state.readback.used_margin
                + state.readback.frozen_margin
                + local
                + margin
            )
            limit = max(ZERO, state.readback.snapshot.balance * m.CAP)
            available = state.readback.snapshot.available - local - fees
            reason = (
                "MINIMUM_OPEN_VOLUME"
                if i.minimum_open_volume != 1
                else "MARGIN_CAP"
                if projected > limit
                else "AVAILABLE_FUNDS"
                if available < margin + i.open_fee
                else "APPROVED"
            )
            decision = m.RiskDecision(
                p.product,
                p.signal_id,
                cmd.at,
                reason == "APPROVED",
                reason,
                margin,
                projected,
                limit,
                state.readback.source_id,
            )
            state = replace(state, risk_decisions=state.risk_decisions + (decision,))
            if reason != "APPROVED":
                state = abandon(state, p)
                continue
        previous = next(
            (
                o
                for o in reversed(state.orders)
                if o.product == p.product
                and o.contract == contract
                and o.side == order_side
                and o.offset == offset
                and o.signal_id == p.signal_id
            ),
            None,
        )
        identity = digest(
            (
                state.account_id,
                policy_version or m.POLICY_VERSION,
                m.RISK_VERSION,
                m.EXECUTION_VERSION,
                key,
                p.product,
            )
        )
        o = m.Order(
            identity,
            p.product,
            contract,
            order_side,
            offset,
            p.signal_id,
            cmd.at,
            price,
            i.source_id,
            q.source_id,
            f.session.source_id,
            previous.order_id if previous else None,
        )
        state = replace(state, orders=state.orders + (o,))
        if offset == "OPEN":
            state = replace(
                state,
                reservations=state.reservations
                + (
                    m.Reservation(
                        o.order_id, margin, i.open_fee, state.readback.source_id
                    ),
                ),
            )
        else:
            state = replace_product(state, replace(p, must_close=True))
        effects.append(m.Effect("SUBMIT", o))
    return state, tuple(effects), "ACCOUNT_TICK"


def validate(state):
    if (
        type(state) is not m.State
        or state.phase not in ("READY", "RECOVERY_REQUIRED", "BLOCKED")
        or type(state.readback_valid) is not bool
    ):
        raise ValueError("ACCOUNT_STATE_INVALID")
    m.text(state.account_id)
    m.time(state.activated_at)
    m.time(state.clock)
    collections = (
        (state.products, m.Product),
        (state.positions, m.Position),
        (state.orders, m.Order),
        (state.reservations, m.Reservation),
        (state.signals, m.Signal),
        (state.fills, (m.Fill, m.NativeFill)),
        (state.updates, m.OrderUpdate),
        (state.risk_decisions, m.RiskDecision),
        (state.audit, m.Audit),
    )
    if any(
        type(values) is not tuple
        or any(
            type(v) not in (kind if type(kind) is tuple else (kind,)) for v in values
        )
        for values, kind in collections
    ):
        raise ValueError("ACCOUNT_STATE_COLLECTION_INVALID")
    if (
        type(state.readback) is not m.Readback
        or type(state.initial_readback) is not m.Readback
        or state.readback.at > state.clock
    ):
        raise ValueError("ACCOUNT_READBACK_TIME_INVALID")
    if set(state.blocked_products) - {p.product for p in state.products} or set(
        state.unresolved_fill_ids
    ) - {f.trade_id for f in state.fills}:
        raise ValueError("ACCOUNT_STATE_SCOPE_INVALID")
    if any(
        type(v) is not tuple
        for v in (
            state.abandoned,
            state.receipts,
            state.blocked_products,
            state.unresolved_fill_ids,
        )
    ) or len(set(state.abandoned)) != len(state.abandoned):
        raise ValueError("ACCOUNT_STATE_IDENTITY_INVALID")
    if (
        state.readback.snapshot.account_id != state.account_id
        or state.initial_readback.snapshot.account_id != state.account_id
    ):
        raise ValueError("ACCOUNT_STATE_IDENTITY_INVALID")
    if (
        not state.products
        or len({p.product for p in state.products}) != len(state.products)
        or len({o.order_id for o in state.orders}) != len(state.orders)
        or len({f.trade_id for f in state.fills}) != len(state.fills)
    ):
        raise ValueError("ACCOUNT_STATE_DUPLICATE")
    if len(dict(state.receipts)) != len(state.receipts) or len(state.receipts) != len(
        state.audit
    ):
        raise ValueError("ACCOUNT_AUDIT_INVALID")
    orders = {o.order_id: o for o in state.orders}
    positions = {}
    filled = set()
    for f in state.fills:
        if f.trade_id in state.unresolved_fill_ids:
            if state.phase != "BLOCKED":
                raise ValueError("UNRESOLVED_FILL_NOT_BLOCKED")
            continue
        o = orders.get(f.order_id)
        if (
            o is None
            or f.order_id in filled
            or f.account_id != state.account_id
            or f.contract != o.contract
            or not fill_follows_order(f, o)
            or f.recorded_at > state.clock
            or o.status != "FILLED"
        ):
            raise ValueError("ACCOUNT_FILL_REPLAY_INVALID")
        old = positions.get(o.product)
        if o.offset == "OPEN":
            if old is not None:
                raise ValueError("ACCOUNT_POSITION_CAPACITY")
            positions[o.product] = (o.contract, 1 if o.side == "BUY" else -1)
        else:
            if old != (o.contract, 1 if o.side == "SELL" else -1):
                raise ValueError("ACCOUNT_CLOSE_REPLAY_INVALID")
            del positions[o.product]
        filled.add(o.order_id)
    if positions != {p.product: (p.contract, p.quantity) for p in state.positions}:
        raise ValueError("ACCOUNT_POSITION_REPLAY_INVALID")
    if len({r.order_id for r in state.reservations}) != len(state.reservations):
        raise ValueError("RESERVATION_DUPLICATE")
    for r in state.reservations:
        o = orders.get(r.order_id)
        if (
            o is None
            or o.offset != "OPEN"
            or r.released
            and (not o.reconciled or o.status not in TERMINAL)
        ):
            raise ValueError("RESERVATION_ORDER_INVALID")
    if {r.order_id for r in state.reservations} != {
        o.order_id for o in state.orders if o.offset == "OPEN"
    }:
        raise ValueError("RESERVATION_MISSING")
    for o in state.orders:
        product(state, o.product)
        if not state.activated_at < o.created_at <= state.clock:
            raise ValueError("ACCOUNT_ORDER_TIME_INVALID")
    for p in state.products:
        active = [
            o for o in state.orders if o.product == p.product and unsettled(state, o)
        ]
        if len(active) > 1:
            raise ValueError("ACCOUNT_ORDER_CAPACITY")


def apply(state, key, cmd):
    m.text(key)
    validate(state)
    if type(cmd) not in (
        m.Signal,
        m.Owner,
        m.Fill,
        m.NativeFill,
        m.OrderUpdate,
        m.Readback,
        m.Recover,
        m.ProductRecoveryV1,
        m.Disconnect,
        m.AbortUnsent,
        m.Tick,
        m.ManagedTickV1,
        m.ManualBeginV1,
        m.ManualTickV1,
    ):
        raise ValueError("ACCOUNT_COMMAND_INVALID")
    payload = digest(cmd)
    prior = dict(state.receipts).get(key)
    if prior is not None:
        if prior != payload:
            raise ValueError("COMMAND_IDENTITY_CONFLICT")
        return m.Transition(state)
    at = (
        cmd.observed_at
        if type(cmd) is m.Signal
        else cmd.recorded_at
        if type(cmd) in (m.Fill, m.NativeFill)
        else cmd.at
    )
    if type(cmd) in (m.Fill, m.NativeFill, m.OrderUpdate, m.Disconnect):
        at = max(at, state.clock)
    if type(cmd) is m.Signal and any(
        (s.product, s.bar_end) == (cmd.product, cmd.bar_end) for s in state.signals
    ):
        at = max(at, state.clock)
    if at < state.clock:
        raise ValueError("COMMAND_TIME_REGRESSION")
    if type(cmd) in (m.Tick, m.ManagedTickV1) and any(
        not manual_status(state, audit.command.test_id).terminal
        for audit in state.audit
        if type(audit.command) is m.ManualBeginV1
    ):
        raise ValueError("MANUAL_TEST_SCOPED_TICK_REQUIRED")
    effects = ()
    if type(cmd) is m.Signal:
        state, reason = signal(state, cmd)
    elif type(cmd) is m.Owner:
        p = product(state, cmd.product)
        if p.owner is not None and p.owner != cmd.contract:
            state = abandon(state, p)
            p = replace(
                product(state, p.product),
                owner=cmd.contract,
                desired=0,
                must_close=position(state, p.product) is not None,
                rolling=True,
            )
            state = cancel_opens(replace_product(state, p), p.product)
            reason = "ROLLOVER_CLOSE_OLD_CONTRACT"
        else:
            state = replace_product(state, replace(p, owner=cmd.contract))
            reason = "OWNER_VERIFIED"
    elif type(cmd) in (m.Fill, m.NativeFill):
        state, reason = apply_fill(state, cmd)
    elif type(cmd) is m.OrderUpdate:
        state, reason = order_update(state, cmd)
    elif type(cmd) is m.Readback:
        state, reason = apply_readback(state, cmd)
    elif type(cmd) is m.Recover:
        state, reason = recover(state, cmd)
    elif type(cmd) is m.ProductRecoveryV1:
        state, reason = recover_product(state, cmd)
    elif type(cmd) is m.ManualBeginV1:
        state, reason = manual_begin(state, cmd)
    elif type(cmd) is m.AbortUnsent:
        o = next((o for o in state.orders if o.order_id == cmd.order_id), None)
        if (
            cmd.account_id != state.account_id
            or o is None
            or o.status != "PROPOSED"
            or o.accepted_at is not None
            or has_fill(state, o)
        ):
            raise ValueError("UNSENT_ABORT_IDENTITY_INVALID")
        state = replace_order(
            state,
            replace(o, status="LOCAL_ABORTED", terminal_at=cmd.at, reconciled=True),
        )
        state = replace(
            state,
            reservations=tuple(
                replace(r, released=True, release_source=cmd.source_id)
                if r.order_id == o.order_id
                else r
                for r in state.reservations
            ),
        )
        if o.offset == "OPEN":
            state = abandon(state, product(state, o.product), o.signal_id)
        reason = "LOCAL_UNSENT_ABORTED"
    elif type(cmd) is m.Disconnect:
        state, reason = (
            cancel_opens(
                replace(
                    state,
                    phase="BLOCKED"
                    if state.unresolved_fill_ids
                    else "RECOVERY_REQUIRED",
                    readback_valid=False,
                )
            ),
            "DISCONNECTED",
        )
    elif type(cmd) is m.ManagedTickV1:
        state, effects, reason = tick(
            state,
            cmd,
            key,
            opening_allowed=False,
            serialized_submit=True,
            policy_version=m.MANAGED_TICK_POLICY_VERSION,
        )
    elif type(cmd) is m.ManualTickV1:
        state, effects, reason = manual_tick(state, cmd, key)
    else:
        state, effects, reason = tick(state, cmd, key)
    state = replace(
        state,
        clock=at,
        phase="BLOCKED" if state.unresolved_fill_ids else state.phase,
        receipts=state.receipts + ((key, payload),),
        audit=state.audit + (m.Audit(key, reason, cmd),),
    )
    validate(state)
    return m.Transition(state, effects)
