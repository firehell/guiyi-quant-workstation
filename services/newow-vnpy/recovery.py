"""Reconcile native facts without synthesizing capital, fills or positions."""

from gateway import SECTIONS, NativeFill, NativeOrder, OrderStatus, Snapshot, identity
from store import digest, wire


def native_key(intent, native_id):
    return f"{intent['trading_day']}:{intent['exchange']}:{native_id}"


def active(intent):
    return intent['state'] not in {'EXPIRED', 'TERMINAL'}


def clear_obligations(state, product):
    return any(item['product'] == product for item in state['clears'].values())


def open_obligations(state, product):
    positions = (state.get('native') or {}).get('positions', [])
    return (any(p['product'] == product and p['quantity'] for p in positions)
            or any(i['product'] == product and active(i) for i in state['intents'].values())
            or clear_obligations(state, product))


def invalidate(state, reason):
    state.update(status='RECONCILING', reason=reason, verified_until=None)


def order_matches(order, intent):
    return all(order[key] == intent[key] for key in ('exchange', 'contract', 'trading_day', 'quantity', 'offset'))


def record_order(state, journal, order: NativeOrder):
    row = wire(order)
    current = state['orders'].get(order.key)
    if current:
        if not order_matches(current, row):
            raise ValueError('P5_NATIVE_ORDER_CONFLICT')
        if OrderStatus(current['status']).terminal:
            if current != row and (order.status.terminal or order.filled > current['filled']):
                raise ValueError('P5_NATIVE_ORDER_CONFLICT')
            return False
        if order.filled < current['filled']:
            if order.status.terminal:
                raise ValueError('P5_NATIVE_ORDER_CONFLICT')
            return False
        if (current == row or order.status is OrderStatus.SUBMITTING
                or current['status'] == OrderStatus.PARTIAL and order.status is OrderStatus.ACTIVE
                and order.filled == current['filled']):
            return False
    state['orders'][order.key] = row
    journal.record('orders', f'{order.key}:{digest(row)}', {'kind': 'native_order', **row})
    return True


def record_fill(state, journal, fill: NativeFill):
    row = wire(fill)
    prior = state['fills'].get(fill.key)
    if prior is not None:
        if prior != row:
            raise ValueError('P5_NATIVE_FILL_CONFLICT')
        return False
    state['fills'][fill.key] = row
    journal.record('fills', fill.key, row)
    return True


def reconcile_snapshot(state, journal, snapshot: Snapshot):
    """Validate the complete query and order/fill prefix before changing trusted state."""
    if (set(snapshot.sections) != SECTIONS or len(snapshot.sections) != len(SECTIONS)
            or snapshot.account is None or snapshot.through != state['watermark']):
        raise ValueError('P5_READBACK_INCOMPLETE')
    expected_day = snapshot.trading_day.isoformat()
    positions = {position.key + (':long' if position.long else ':short'): position for position in snapshot.positions}
    orders = {order.key: order for order in snapshot.orders}
    fills = {fill.key: fill for fill in snapshot.fills}
    if (len(positions) != len(snapshot.positions) or len(orders) != len(snapshot.orders)
            or len(fills) != len(snapshot.fills)
            or any(row.trading_day != snapshot.trading_day for row in (*orders.values(), *fills.values()))
            or any(row.occurred_at > snapshot.as_of for row in fills.values())):
        raise ValueError('P5_READBACK_CONFLICT')
    if (any(value['trading_day'] == expected_day and key not in orders for key, value in state['orders'].items())
            or any(value['trading_day'] == expected_day and key not in fills for key, value in state['fills'].items())):
        raise ValueError('P5_READBACK_MISSING_CALLBACK')
    for key, fill in fills.items():
        order = orders.get(fill.order_key)
        if not order or (fill.contract, fill.offset) != (order.contract, order.offset):
            raise ValueError('P5_FILL_ORDER_MISMATCH')
        if key in state['fills'] and wire(fill) != state['fills'][key]:
            raise ValueError('P5_NATIVE_FILL_CONFLICT')
    traded = dict.fromkeys(orders, 0)
    for fill in fills.values():
        traded[fill.order_key] += fill.quantity
    for key, order in orders.items():
        if order.status is OrderStatus.SUBMITTING or traded[key] != order.filled:
            raise ValueError('P5_ORDER_FILL_TOTAL_UNVERIFIED')
        current = state['orders'].get(key)
        if current and (not order_matches(current, wire(order)) or current['filled'] > order.filled
                        or OrderStatus(current['status']).terminal and current != wire(order)):
            raise ValueError('P5_ORDER_READBACK_REGRESSION')

    # Positions are absolute native facts. Verify deltas whenever a prior same-day
    # readback establishes a baseline, including fills first seen in the query.
    previous = state.get('native')
    if previous and previous['trading_day'] == expected_day:
        position_delta = {}
        for key, fill in fills.items():
            if key not in previous['fill_keys']:
                contract = identity(fill.exchange, fill.contract)
                change = fill.quantity if fill.offset == 'OPEN' else -fill.quantity
                position_delta[contract] = position_delta.get(contract, 0) + change
        before = {identity(p['exchange'], p['contract']): p['quantity'] for p in previous['positions'] if p['long']}
        after = {identity(p.exchange, p.contract): p.quantity for p in positions.values() if p.long}
        if any(before.get(k, 0) + position_delta.get(k, 0) != after.get(k, 0)
               for k in before.keys() | after.keys() | position_delta.keys()):
            raise ValueError('P5_POSITION_READBACK_MISMATCH')

    matched = set()
    for intent in state['intents'].values():
        if active(intent) and intent.get('native_id'):
            key = native_key(intent, intent['native_id'])
            if key in matched:
                raise ValueError('P5_NATIVE_ID_NOT_UNIQUE')
            matched.add(key)
            if key in orders and not order_matches(wire(orders[key]), intent):
                raise ValueError('P5_NATIVE_INTENT_CONFLICT')
    for order in orders.values():
        record_order(state, journal, order)
    for fill in fills.values():
        record_fill(state, journal, fill)
    for intent in state['intents'].values():
        if not active(intent) or not intent.get('native_id'):
            continue
        order = orders.get(native_key(intent, intent['native_id']))
        if order and order.status.terminal:
            intent.update(state='TERMINAL', reserved='0', close_outcome=order.status)
            journal.record('orders', f"{intent['id']}:terminal", {'kind': 'intent_terminal', **intent})
        elif order and intent['state'] in {'SUBMITTED', 'NATIVE_ACTIVE'}:
            intent.update(state='NATIVE_ACTIVE', native_filled=order.filled)

    # The snapshot proves that its margin/availability includes the filled lots.
    # The unfilled reservation is still retained until reconciliation of a terminal order.
    for intent in state['intents'].values():
        if intent['state'] == 'NATIVE_ACTIVE' and intent['offset'] == 'OPEN':
            from decimal import Decimal

            intent['reserved'] = wire(Decimal(intent['unit_reserve']) * (intent['quantity'] - intent['native_filled']))

    record = {**wire(snapshot), 'fill_keys': sorted(fills)}
    record.pop('orders')
    record.pop('fills')
    record.pop('sections')
    journal.record('readbacks', digest(record), record)
    state['native'] = record
    if any((not p.long or not p.valued or p.product not in state['owners']) and p.quantity for p in positions.values()):
        return 'P5_POSITION_RISK_UNVERIFIED'
    if any(not order.status.terminal and order.key not in matched for order in orders.values()):
        return 'P5_UNATTRIBUTED_NATIVE_ORDER'
    if any(active(intent) and (
        intent['state'] in {'CLAIMED', 'UNKNOWN', 'CANCEL_CLAIMED', 'CANCEL_UNKNOWN'}
        or intent.get('native_id') and native_key(intent, intent['native_id']) not in orders
    ) for intent in state['intents'].values()):
        return 'P5_ORDER_UNRESOLVED'
    return None
