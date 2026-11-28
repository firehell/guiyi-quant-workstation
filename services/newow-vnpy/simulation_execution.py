"""Offline fire drill for the HTDY account reducer and VeighNa order preparation."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from types import MappingProxyType

from app.simulation_center.facts import normalize
from app.simulation_center.execution_store import REHEARSAL_SOURCE
from app.simulation_center.store import check_order_prefix
from guiyi_quant import htdy_account_execution as account, htdy_execution as htdy
from guiyi_quant.htdy_account_execution.codec import digest, json_text
from guiyi_quant.simnow_execution.model import Contract, Inventory, close_offset

FIXTURE_ACCOUNT = "OFFLINE"
GATEWAY = "SIMULATION_OFFLINE"
SOURCE = REHEARSAL_SOURCE
OFFSETS = {"3": "CLOSETODAY", "4": "CLOSEYESTERDAY", "1": "CLOSE"}
ORDER_STATES = {"0": "FILLED", "3": "WORKING", "5": "CANCELLED"}


class RehearsalError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise RehearsalError(code)


@dataclass(frozen=True)
class ExecutionSession:
    trading_day: date
    front: int
    session: int
    max_order_ref: int = 0

    def __post_init__(self):
        _require(type(self.trading_day) is date and type(self.front) is int and self.front > 0
                 and type(self.session) is int and self.session != 0
                 and type(self.max_order_ref) is int and 0 <= self.max_order_ref < 10**12,
                 "OFFLINE_SESSION_INVALID")


@dataclass(frozen=True, init=False)
class CabinetProof:
    session: ExecutionSession
    first_at: datetime
    observed_at: datetime
    _payload: str

    @property
    def facts(self):
        return json.loads(self._payload)

    @property
    def valid_until(self):
        return self.observed_at + timedelta(seconds=60)

    @property
    def source_id(self):
        session = self.session
        identity = digest((SOURCE, session.trading_day.isoformat(), session.front, session.session,
                           session.max_order_ref, self.first_at, self.observed_at, self._payload))
        return f"{SOURCE}:{identity}"

    @classmethod
    def compare(cls, session, first, second, first_at, second_at):
        from guiyi_quant.htdy_account_execution.model import time

        time(first_at)
        time(second_at)
        _require(timedelta(seconds=1) <= second_at - first_at <= timedelta(seconds=30), "OFFLINE_ROUND_WINDOW")
        day = session.trading_day.strftime("%Y%m%d")

        def extract(rows):
            _require(set(rows) == {"account", "positions", "orders", "fills"}, "OFFLINE_SECTIONS_INCOMPLETE")
            result = normalize(rows, FIXTURE_ACCOUNT, day)
            capital = rows["account"][0]
            for key, field in (("frozen_margin", "FrozenMargin"), ("frozen_fee", "FrozenCommission")):
                value = Decimal(str(capital[field]))
                _require(value.is_finite() and value >= 0, "OFFLINE_FUNDS_INVALID")
                result["account"][key] = format(value, "f")
            for kind in ("positions", "orders", "fills"):
                result[kind].sort(key=lambda row: row["id"])
            return result

        previous, current = extract(first), extract(second)
        _require(previous == current, "OFFLINE_ROUNDS_DIFFER")
        proof = object.__new__(cls)
        object.__setattr__(proof, "session", session)
        object.__setattr__(proof, "first_at", first_at)
        object.__setattr__(proof, "observed_at", second_at)
        object.__setattr__(proof, "_payload", json_text(current))
        return proof


@dataclass(frozen=True)
class FeeEvidence:
    amount: Decimal
    source_id: str

    def __post_init__(self):
        _require(type(self.amount) is Decimal and self.amount.is_finite() and self.amount >= 0
                 and type(self.source_id) is str and self.source_id.startswith("fixture:") and len(self.source_id) > 8,
                 "OFFLINE_FILL_FEE_UNPROVEN")


@dataclass(frozen=True)
class PreparedAction:
    kind: str
    order_id: str
    cabinet_id: str
    request: object


@dataclass(frozen=True)
class RealizedTrade:
    contract: str
    entry_id: str
    exit_id: str
    gross: Decimal
    fees: Decimal
    net: Decimal
    source: str = SOURCE


def _direction(side):
    return "LONG" if side == "BUY" else "SHORT"


class OfflineExecution:
    """The only side effect is storage in the isolated offline execution journal."""

    def __init__(self, store, bindings: tuple[Contract, ...]):
        self.store = store
        self.bindings = MappingProxyType({item.canonical: item for item in bindings})
        self.native_bindings = MappingProxyType({(item.exchange, item.native.upper()): item for item in bindings})
        _require(len(self.bindings) == len(self.native_bindings) == len(bindings) and bindings, "OFFLINE_SCOPE_INVALID")
        self.binding_hash = digest(tuple(sorted(bindings, key=lambda item: item.canonical)))

    def create(self, products: tuple[str, ...], proof: CabinetProof):
        _require(not any(proof.facts[key] for key in ("positions", "orders", "fills")), "OFFLINE_INITIAL_ACCOUNT_NOT_FLAT")
        self.store.create(account.start(self.store.account_id, products, proof.observed_at,
                                        self._readback(proof, (), (), ())), binding_hash=self.binding_hash)

    def owner(self, command: htdy.Owner):
        self.store.verify_binding(self.binding_hash)
        binding = self.bindings.get(command.contract)
        _require(binding and binding.at <= command.at < binding.valid_until, "OFFLINE_CONTRACT_UNVERIFIED")
        return self.store.transact(lambda _: (("owner:" + command.source_id, command),))

    def signal(self, signal: htdy.Signal):
        self.store.verify_binding(self.binding_hash)
        _require(signal.contract in self.bindings, "OFFLINE_CONTRACT_UNVERIFIED")
        return self.store.transact(lambda _: (("signal:" + signal.source_id, signal),))

    def on_completed(self, market_read, window, *, source_id, observed_at):
        from app.htdy_execution import signal_from_window

        return self.signal(signal_from_window(market_read, window, source_id=source_id, observed_at=observed_at))

    def tick(self, key: str, at: datetime, inputs: tuple[account.ExecutionInput, ...]):
        self.store.verify_binding(self.binding_hash)
        for item in inputs:
            binding = self.bindings.get(item.instrument.contract)
            _require(binding and binding.at <= at < binding.valid_until, "OFFLINE_CONTRACT_UNVERIFIED")
        tick = account.ContinuousTradeTickV1(at, inputs)
        return self.store.transact(lambda _: (("tick:" + key, tick),))

    def disconnect(self, key: str, at: datetime):
        self.store.verify_binding(self.binding_hash)
        return self.store.transact(lambda _: (("disconnect:" + key, account.Disconnect(at)),))

    def realized_trades(self) -> tuple[RealizedTrade, ...]:
        self.store.verify_binding(self.binding_hash)
        state = self.store.replay()
        orders = {order.order_id: order for order in state.orders if order.reconciled}
        entry_fills, closed = {}, []
        for fill in state.fills:
            order = orders.get(fill.order_id)
            if order is None:
                continue
            if order.offset == "OPEN":
                _require(order.product not in entry_fills, "OFFLINE_REALIZED_POSITION_CONFLICT")
                entry_fills[order.product] = fill
                continue
            entry = entry_fills.pop(order.product, None)
            _require(entry is not None and entry.contract == fill.contract, "OFFLINE_REALIZED_CONTRACT_CONFLICT")
            opening = orders[entry.order_id]
            multiplier = self._order_input(opening).instrument.multiplier
            _require(multiplier == self._order_input(order).instrument.multiplier,
                     "OFFLINE_REALIZED_MULTIPLIER_CONFLICT")
            delta = fill.price - entry.price if opening.side == "BUY" else entry.price - fill.price
            gross = delta * multiplier * fill.quantity
            fees = entry.fee + fill.fee
            closed.append(RealizedTrade(fill.contract, entry.trade_id, fill.trade_id, gross, fees, gross - fees))
        return tuple(closed)

    def prepare(self, effect: account.Effect, proof: CabinetProof, now: datetime):
        """Build and claim a VeighNa request. The rehearsal has no send method."""
        self.store.verify_binding(self.binding_hash)
        state = self.store.current()
        original = next((row for row in state.orders if row.order_id == effect.order.order_id), None)
        _require(effect.kind in ("SUBMIT", "CANCEL") and original == effect.order, "OFFLINE_EFFECT_STALE")
        _require(state.phase == "READY" and state.readback_valid and state.readback.source_id == proof.source_id
                 and proof.observed_at <= now < proof.valid_until and state.clock <= now and original.created_at <= now,
                 "OFFLINE_READBACK_REQUIRED")
        binding = self.bindings[original.contract]
        _require(binding.at <= now < binding.valid_until, "OFFLINE_CONTRACT_EXPIRED")
        claims = self.store.claims()
        submit = claims.get((original.order_id, "SUBMIT"))
        if effect.kind == "SUBMIT" and submit:
            return None
        if effect.kind == "CANCEL" and (original.order_id, "CANCEL") in claims:
            return None
        native_id, request = self._build_request(original, effect.kind, state, binding, proof, now, submit)
        payload = {
            "order_id": original.order_id, "native_id": native_id, "contract": binding.native.upper(),
            "exchange": binding.exchange, "direction": _direction(original.side),
            "offset": request.offset.name if effect.kind == "SUBMIT" else submit["offset"],
            "quantity": original.quantity, "price": format(original.price, "f"),
            "proof": proof.source_id, "source": SOURCE, "state_hash": digest(state), "claimed_at": now.isoformat(),
        }
        if not self.store.claim(original.order_id, effect.kind, payload):
            return None
        return PreparedAction(effect.kind, original.order_id, native_id, request)

    def _order_input(self, order):
        origin = self.store.origin_command(order.order_id, "SUBMIT")
        _require(type(origin) is account.ContinuousTradeTickV1 and origin.at == order.created_at,
                 "OFFLINE_EXECUTION_ORIGIN_MISMATCH")
        inputs = next((item for item in origin.inputs if (item.instrument.contract, item.instrument.source_id,
            item.quote.source_id if item.quote else None, item.session.source_id)
            == (order.contract, order.instrument_source, order.quote_source, order.session_source)), None)
        _require(inputs is not None, "OFFLINE_EXECUTION_INPUT_MISSING")
        return inputs

    def _build_request(self, order, kind, state, binding, proof, now, submit):
        from vnpy.event import Event, EventEngine
        from vnpy.trader.constant import Direction, Exchange, Offset, OrderType, Product, Status
        from vnpy.trader.engine import OmsEngine
        from vnpy.trader.event import EVENT_CONTRACT, EVENT_ORDER, EVENT_POSITION
        from vnpy.trader.object import ContractData, OrderRequest, PositionData

        exchange = Exchange(binding.exchange)
        native = binding.native
        oms = OmsEngine(None, EventEngine())
        inputs = self._order_input(order)
        if kind == "SUBMIT":
            _require(now < min(inputs.instrument.valid_until, inputs.session.valid_until, inputs.quote.valid_until,
                               inputs.session.final_close_at), "OFFLINE_ORDER_EXPIRED")
        else:
            cancel_tick = self.store.origin_command(order.order_id, "CANCEL")
            _require(type(cancel_tick) is account.ContinuousTradeTickV1, "OFFLINE_CANCEL_ORIGIN_MISMATCH")
            cancel_input = next((item for item in cancel_tick.inputs if item.instrument.contract == order.contract), None)
            _require(cancel_input and cancel_input.session.can_cancel
                     and cancel_input.session.at <= now < cancel_input.session.valid_until, "OFFLINE_CANCEL_EXPIRED")
        instrument = inputs.instrument
        contract = ContractData(gateway_name=GATEWAY, symbol=native, exchange=exchange, name=native,
                                product=Product.FUTURES, size=float(instrument.multiplier),
                                pricetick=float(instrument.tick_size), min_volume=instrument.minimum_open_volume)
        oms.process_contract_event(Event(EVENT_CONTRACT, contract))
        for row in proof.facts["positions"]:
            if (row["exchange"], row["contract"]) != (binding.exchange, native.upper()) or not row["quantity"]:
                continue
            native_position = PositionData(
                gateway_name=GATEWAY, symbol=native, exchange=exchange, direction=Direction[row["direction"]],
                volume=row["quantity"], yd_volume=row["yesterday"], frozen=row["frozen"],
            )
            oms.process_position_event(Event(EVENT_POSITION, native_position))

        if kind == "CANCEL":
            _require(submit is not None, "OFFLINE_SUBMIT_CLAIM_MISSING")
            native_order = next((row for row in proof.facts["orders"] if row["id"] == submit["native_id"]), None)
            _require(native_order and ORDER_STATES.get(native_order["status"]) == "WORKING", "OFFLINE_CANCEL_ORDER_UNKNOWN")
            self._match(native_order, submit)
            from vnpy.trader.object import OrderData

            vt_order = OrderData(
                gateway_name=GATEWAY, symbol=native, exchange=exchange, orderid="_".join(native_order["id"].split(":")[2:]),
                direction=Direction[native_order["direction"]], offset=Offset[native_order["offset"]],
                price=float(Decimal(native_order["price"])), volume=native_order["quantity"], status=Status.NOTTRADED,
            )
            oms.process_order_event(Event(EVENT_ORDER, vt_order))
            return native_order["id"], oms.get_order(vt_order.vt_orderid).create_cancel_request()

        direction = Direction[_direction(order.side)]
        price = float(order.price)
        _require(Decimal(str(price)) == order.price, "OFFLINE_PRICE_PRECISION_LOSS")
        request = OrderRequest(
            symbol=native, exchange=exchange, direction=direction, offset=Offset[order.offset],
            type=OrderType.LIMIT, price=price, volume=order.quantity, reference=order.order_id,
        )
        converted = oms.convert_order_request(request, GATEWAY, lock=False, net=False)
        _require(len(converted) == 1 and converted[0].volume == 1, "OFFLINE_VEIGHNA_OFFSET_UNAVAILABLE")
        if order.offset == "CLOSE":
            held_side = "SHORT" if order.side == "BUY" else "LONG"
            held = [row for row in proof.facts["positions"] if
                    (row["exchange"], row["contract"], row["direction"])
                    == (binding.exchange, native.upper(), held_side) and row["quantity"]]
            _require(len(held) == 1 and not held[0]["frozen"], "OFFLINE_CLOSE_INVENTORY_UNAVAILABLE")
            inventory = Inventory(order.contract, 1 if held_side == "LONG" else -1, held[0]["today"],
                                  held[0]["yesterday"], proof.source_id, proof.observed_at, proof.valid_until)
            _require(OFFSETS[close_offset(binding, inventory, order.side, now)] == converted[0].offset.name,
                     "OFFLINE_OFFSET_CONFLICT")
        index = next(index for index, item in enumerate(state.orders, 1) if item.order_id == order.order_id)
        reference = index + proof.session.max_order_ref
        _require(reference < 10**12, "OFFLINE_ORDER_REF_EXHAUSTED")
        return (f"{proof.session.trading_day}:{binding.exchange}:{proof.session.front}:{proof.session.session}:{reference}",
                converted[0])

    @staticmethod
    def _match(row, claim):
        _require(all(row[field] == claim[field] for field in ("exchange", "contract", "direction", "offset", "quantity"))
                 and Decimal(row["price"]) == Decimal(claim["price"]), "OFFLINE_ORDER_FACTS_CONFLICT")

    def _readback(self, proof, positions, reports, settled, trade_ids=()):
        funds = proof.facts["account"]
        return account.Readback(
            htdy.AccountSnapshot(self.store.account_id, proof.observed_at, Decimal(funds["equity"]),
                                 Decimal(funds["available"]), positions, reports, settled),
            Decimal(funds["margin"]), Decimal(funds["frozen_margin"]), Decimal(funds["frozen_fee"]),
            (), trade_ids, proof.source_id, proof.valid_until, True,
        )

    def _account_commands(self, state, proof, facts, fees, recovery):
        claims = {claim["native_id"]: claim for (_, kind), claim in self.store.claims().items() if kind == "SUBMIT"}
        previous = {fill.trade_id: fill for fill in state.fills}
        known = {order.order_id: order for order in state.orders}
        positions = []
        for row in facts["positions"]:
            if not row["quantity"]:
                continue
            binding = self.native_bindings.get((row["exchange"], row["contract"]))
            _require(binding and row["hedge_flag"] == "1" and row["quantity"] == 1, "OFFLINE_POSITION_UNOWNED")
            product = next((item.product for item in state.products if binding.canonical.startswith(item.product)
                            and binding.canonical[len(item.product)].isdigit()), None)
            _require(product, "OFFLINE_POSITION_UNOWNED")
            positions.append(htdy.Position(product, binding.canonical, 1 if row["direction"] == "LONG" else -1))
        reports, settled, commands = [], [], []
        for row in facts["orders"]:
            claim = claims.get(row["id"])
            _require(claim and claim["order_id"] in known, "OFFLINE_UNKNOWN_NATIVE_ORDER")
            self._match(row, claim)
            status = ORDER_STATES.get(row["status"])
            _require(status is not None, "OFFLINE_NATIVE_ORDER_STATE_UNPROVEN")
            identity = claim["order_id"]
            reports.append(htdy.OrderReport(identity, status))
            if status in ("CANCELLED", "REJECTED"):
                settled.append(identity)
            order = known[identity]
            if status == "WORKING" and order.accepted_at is None:
                commands.append(("order:" + row["id"], account.OrderUpdate(
                    state.account_id, identity, proof.observed_at, row["id"], status, proof.observed_at,
                )))

        for row in sorted(facts["fills"], key=lambda report: (report["occurred_at"], report["id"])):
            claim = claims[row["order_id"]]
            order = known[claim["order_id"]]
            price = Decimal(row["price"])
            _require((price <= order.price if order.side == "BUY" else price >= order.price), "OFFLINE_FILL_PRICE_CONFLICT")
            happened = datetime.fromisoformat(row["occurred_at"])
            session = self._order_input(order).session
            _require(order.created_at < happened <= proof.observed_at
                     and datetime.fromisoformat(claim["claimed_at"]) <= happened < session.final_close_at,
                     "OFFLINE_FILL_TIME_CONFLICT")
            if row["id"] in previous:
                retained = previous[row["id"]]
                _require((retained.order_id, retained.filled_at, retained.price) == (order.order_id, happened, price),
                         "OFFLINE_FILL_IDENTITY_CONFLICT")
                if row["id"] in fees:
                    _require(fees[row["id"]].amount == retained.fee, "OFFLINE_FEE_CONFLICT")
                continue
            fee = fees.get(row["id"])
            _require(type(fee) is FeeEvidence, "OFFLINE_FILL_FEE_UNPROVEN")
            commands.append(("fill:" + row["id"], htdy.Fill(
                row["id"], order.order_id, state.account_id, order.contract, happened, proof.observed_at,
                price, fee.amount, row["quantity"],
            )))

        readback = self._readback(proof, tuple(positions), tuple(reports), tuple(settled),
                                  tuple(row["id"] for row in facts["fills"]))
        commands.append((proof.source_id, account.Recover(readback, recovery) if recovery is not None else readback))
        return commands

    def reconcile(self, proof: CabinetProof, *, fees=None, recovery=None):
        self.store.verify_binding(self.binding_hash)
        fees = fees or {}
        facts = {**proof.facts, "observed_at": proof.observed_at.isoformat()}
        _require(all(type(fee) is FeeEvidence for fee in fees.values())
                 and fees.keys() <= {row["id"] for row in facts["fills"]}, "OFFLINE_FILL_FEE_UNPROVEN")
        evidence = {**facts, "fees": {key: {"amount": str(fee.amount), "source_id": fee.source_id}
                                    for key, fee in fees.items()},
                    "recovery_hash": digest(recovery) if recovery is not None else None}

        def apply(state):
            if proof.source_id in dict(state.receipts):
                retained = self.store.evidence(proof.source_id)
                _require(retained is not None and all(retained["fees"].get(key) == fee
                         for key, fee in evidence["fees"].items()) and (recovery is None or
                         retained["recovery_hash"] == evidence["recovery_hash"]), "OFFLINE_EVIDENCE_RETRY_CONFLICT")
                return ()
            _require(state.clock <= proof.observed_at, "OFFLINE_READBACK_TIME_REGRESSION")
            previous = self.store.evidence(state.readback.source_id)
            if previous:
                check_order_prefix(previous, facts)
                if previous["trading_day"] == facts["trading_day"]:
                    current = {row["id"]: row for row in facts["fills"]}
                    _require(all(current.get(row["id"]) == row for row in previous["fills"]),
                             "OFFLINE_NATIVE_FILL_PREFIX_CONFLICT")
            commands = self._account_commands(state, proof, facts, fees, recovery)
            sample_state = state
            for key, command in commands:
                sample_state = account.apply(sample_state, key, command).state
            _require(sample_state.readback_valid and not sample_state.unresolved_fill_ids,
                     sample_state.audit[-1].reason)
            return commands

        try:
            return self.store.transact(apply, evidence=(proof.source_id, evidence))
        except ValueError:
            key = f"block:{proof.source_id}"
            self.store.transact(lambda state: () if key in dict(state.receipts) else ((key, account.Disconnect(
                max(proof.observed_at, state.clock),
            )),))
            raise
