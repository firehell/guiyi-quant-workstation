"""Durable scope derived from its journal command; historical model stays exact."""
from dataclasses import fields, replace
from . import model as m


def trading_scope(state):
    return state.scope_command if type(state) is m.TqKqScopedStateV1 else None


def enforce_scope(state, command=None):
    scope = command or trading_scope(state)
    if scope is None:
        return state
    if type(state) is m.State:
        state = m.TqKqScopedStateV1(**{f.name: getattr(state, f.name) for f in fields(state)},
                                  scope_command=scope)
    allowed = set(scope.products)
    held = {p.product for p in state.positions}
    products = tuple(p if p.product in allowed else replace(
        p, desired=0, opening_consumed=True, must_close=p.product in held,
        signal_id="scope:" + scope.scope_version + ":" + p.product,
        signal_at=scope.at) for p in state.products)
    orders = tuple(replace(o, cancel_required=True)
        if o.product not in allowed and o.offset == "OPEN" and not o.reconciled
        else o for o in state.orders)
    return replace(state, products=products, orders=orders)


def scope_status(state, now=None):
    scope = trading_scope(state)
    if scope is None:
        return {"status": "NOT_APPLIED", "version": None}
    allowed = set(scope.products)
    positions = [p for p in state.positions if p.product not in allowed]
    pending = [o for o in state.orders if o.product not in allowed and not o.reconciled]
    order_products = {o.order_id: o.product for o in state.orders}
    reservations = [r for r in state.reservations if not r.released
                    and order_products[r.order_id] not in allowed]
    now = state.clock if now is None else now
    verified = (state.readback.at <= now < state.readback.valid_until
                and state.readback_valid and state.phase == "READY"
                and state.readback.at >= scope.at and not state.unresolved_fill_ids)
    return {"status": "ACTIVE" if not (positions or pending or reservations) and verified
            else "FLATTEN_PENDING", "version": scope.scope_version,
            "products": list(scope.products),
            "pending_positions": [{"product": p.product, "contract": p.contract,
                                   "quantity": p.quantity} for p in positions],
            "pending_order_ids": [o.order_id for o in pending],
            "pending_reservation_ids": [r.order_id for r in reservations],
            "native_readback_verified": verified}
