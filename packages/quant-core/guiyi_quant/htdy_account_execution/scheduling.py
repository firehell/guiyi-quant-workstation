"""One deterministic order of strategy targets, shared by policy and native I/O."""

from dataclasses import dataclass


def ordered_products(state):
    return tuple(
        sorted(
            state.products,
            key=lambda p: (
                p.signal_at or state.activated_at,
                p.product,
                p.signal_id or "",
            ),
        )
    )


def desired_action(state, product):
    held = next((p for p in state.positions if p.product == product.product), None)
    if held and (
        product.must_close or product.rolling or held.quantity != product.desired
    ):
        return "CLOSE", held.contract, "SELL" if held.quantity > 0 else "BUY"
    if (
        held is None
        and not product.rolling
        and product.desired
        and not product.opening_consumed
        and product.signal_id not in state.abandoned
    ):
        return "OPEN", product.owner, "BUY" if product.desired > 0 else "SELL"
    return None


@dataclass(frozen=True)
class ExecutionCandidate:
    product: str
    contract: str
    offset: str


def execution_candidates(state, *, opening_allowed=False):
    # No other submission can proceed until a claimed/pending order is fully
    # reconciled; retain its input priority even if it currently lacks a quote.
    pending = sorted(
        (o for o in state.orders if not o.reconciled),
        key=lambda o: (o.created_at, o.product, o.order_id),
    )
    if pending:
        return tuple(
            ExecutionCandidate(o.product, o.contract, o.offset) for o in pending
        )
    result = []
    for product in ordered_products(state):
        action = desired_action(state, product)
        if action is None:
            continue
        offset, contract, _ = action
        if offset == "OPEN" and (
            not opening_allowed or product.product in state.blocked_products
        ):
            continue
        result.append(ExecutionCandidate(product.product, contract, offset))
    return tuple(result)


def executable_price(fact, side, at):
    """Shared temporary execution eligibility, without consuming any target."""
    session, quote, instrument = fact.session, fact.quote, fact.instrument
    if (
        not session.at <= at < session.valid_until
        or not session.can_trade
        or at >= session.final_close_at
        or quote is None
        or not quote.at <= at < quote.valid_until
        or not instrument.at <= at < instrument.valid_until
    ):
        return None
    price = quote.ask if side == "BUY" else quote.bid
    volume = quote.ask_volume if side == "BUY" else quote.bid_volume
    return price if volume >= 1 and price % instrument.tick_size == 0 else None
