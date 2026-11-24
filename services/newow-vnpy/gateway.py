"""VeighNa's offline boundary and the typed facts consumed by reconciliation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
import re
from threading import Lock

from app.market_data.domain import normalize_contract_for_symbol

SECTIONS = frozenset({'account', 'positions', 'orders', 'fills'})
EXCHANGES = frozenset({'SHFE', 'INE', 'DCE', 'CZCE', 'CFFEX', 'GFEX'})


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('P5_TIMEZONE_REQUIRED')
    return value


def money(value: Decimal, *, nonnegative: bool = True) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or nonnegative and value < 0:
        raise ValueError('P5_DECIMAL_INVALID')


def identity(exchange: str, contract: str) -> str:
    if exchange not in EXCHANGES or normalize_contract_for_symbol(contract_product(contract), contract) != contract:
        raise ValueError('P5_CONTRACT_INVALID')
    return f'{exchange}:{contract}'


def contract_product(contract: str) -> str:
    matched = re.fullmatch(r'([A-Z]+)[0-9]{3,4}', contract)
    if matched is None:
        raise ValueError('P5_CONTRACT_INVALID')
    return matched[1].lower()


def lots(value: int, *, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError('P5_LOTS_INVALID')


class OrderStatus(StrEnum):
    SUBMITTING = 'SUBMITTING'
    ACTIVE = 'ACTIVE'
    PARTIAL = 'PARTIAL'
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'
    REJECTED = 'REJECTED'

    @property
    def terminal(self):
        return self in (self.FILLED, self.CANCELLED, self.REJECTED)


@dataclass(frozen=True, slots=True)
class NativeOrder:
    exchange: str
    contract: str
    trading_day: date
    native_id: str
    quantity: int
    filled: int
    status: OrderStatus
    offset: str = 'OPEN'

    def __post_init__(self):
        identity(self.exchange, self.contract)
        lots(self.quantity, minimum=1)
        lots(self.filled)
        if (not self.native_id or type(self.trading_day) is not date or self.filled > self.quantity
                or not isinstance(self.status, OrderStatus)
                or self.offset not in {'OPEN', 'CLOSE', 'CLOSETODAY', 'CLOSEYESTERDAY'}
                or (self.status is OrderStatus.FILLED) != (self.quantity == self.filled)
                or self.status in {OrderStatus.SUBMITTING, OrderStatus.ACTIVE, OrderStatus.REJECTED}
                and self.filled or self.status is OrderStatus.PARTIAL and not self.filled):
            raise ValueError('P5_NATIVE_ORDER_INVALID')

    @property
    def key(self):
        return f'{self.trading_day}:{self.exchange}:{self.native_id}'


@dataclass(frozen=True, slots=True)
class NativeFill:
    exchange: str
    contract: str
    trading_day: date
    native_order_id: str
    native_trade_id: str
    quantity: int
    price: Decimal
    occurred_at: datetime
    offset: str = 'OPEN'

    def __post_init__(self):
        identity(self.exchange, self.contract)
        aware(self.occurred_at)
        lots(self.quantity, minimum=1)
        money(self.price)
        if (not self.native_order_id or not self.native_trade_id or not self.price
                or type(self.trading_day) is not date
                or self.offset not in {'OPEN', 'CLOSE', 'CLOSETODAY', 'CLOSEYESTERDAY'}):
            raise ValueError('P5_NATIVE_FILL_INVALID')

    @property
    def key(self):
        return f'{self.trading_day}:{self.exchange}:{self.native_trade_id}'

    @property
    def order_key(self):
        return f'{self.trading_day}:{self.exchange}:{self.native_order_id}'


@dataclass(frozen=True, slots=True)
class Position:
    exchange: str
    contract: str
    product: str
    quantity: int
    today: int
    frozen: int
    valued: bool = True
    long: bool = True

    def __post_init__(self):
        identity(self.exchange, self.contract)
        for value in (self.quantity, self.today, self.frozen):
            lots(value)
        if (self.today > self.quantity or self.frozen > self.quantity
                or self.product.lower() != contract_product(self.contract)
                or type(self.valued) is not bool or type(self.long) is not bool):
            raise ValueError('P5_NATIVE_POSITION_INVALID')
        object.__setattr__(self, 'product', self.product.lower())

    @property
    def key(self):
        return identity(self.exchange, self.contract)


@dataclass(frozen=True, slots=True)
class Account:
    balance: Decimal
    available: Decimal
    margin: Decimal
    daily_loss: Decimal

    def __post_init__(self):
        money(self.balance, nonnegative=False)
        money(self.available, nonnegative=False)
        money(self.margin)
        money(self.daily_loss)


@dataclass(frozen=True, slots=True)
class Snapshot:
    alias: str
    generation: str
    trading_day: date
    as_of: datetime
    through: int
    sections: tuple[str, ...]
    account: Account | None
    positions: tuple[Position, ...] = ()
    orders: tuple[NativeOrder, ...] = ()
    fills: tuple[NativeFill, ...] = ()
    readback_id: str | None = None

    def __post_init__(self):
        aware(self.as_of)
        lots(self.through)
        if not self.generation or type(self.trading_day) is not date:
            raise ValueError('P5_NATIVE_SNAPSHOT_INVALID')


@dataclass(frozen=True, slots=True)
class Quote:
    exchange: str
    contract: str
    trading_day: date
    generation: str
    as_of: datetime
    bid: Decimal
    ask: Decimal
    lower: Decimal
    upper: Decimal

    def __post_init__(self):
        identity(self.exchange, self.contract)
        aware(self.as_of)
        for value in (self.bid, self.ask, self.lower, self.upper):
            money(value)
        if (not self.generation or type(self.trading_day) is not date
                or not 0 < self.lower <= self.bid <= self.ask <= self.upper):
            raise ValueError('P5_QUOTE_INVALID')


class FixtureGateway:
    """Records calls. Only its explicitly injected fixture receipt can match an order."""

    def __init__(self, on_send: Callable | None = None):
        self.sends: list[dict] = []
        self.cancels: list[dict] = []
        self.on_send = on_send

    def send(self, intent: dict) -> str | None:
        self.sends.append(intent.copy())
        if self.on_send:
            return self.on_send(intent)
        return f'fixture-{len(self.sends)}'

    def cancel(self, intent: dict) -> None:
        self.cancels.append(intent.copy())

    def validate_request(self, intent: dict) -> None:
        identity(intent['exchange'], intent['contract'])
        lots(intent['quantity'], minimum=1)

    def register_contract(self, policy: dict) -> None:
        identity(policy['exchange'], policy['contract'])

    def close_legs(self, position: dict) -> tuple[tuple[str, int], ...]:
        free = position['quantity'] - position['frozen']
        if not free:
            return ()
        if position['exchange'] not in {'SHFE', 'INE'}:
            return (('CLOSE', free),)
        # A total freeze cannot prove which Shanghai close bucket remains free.
        if position['frozen']:
            return ()
        return tuple((offset, count) for offset, count in (
            ('CLOSETODAY', position['today']), ('CLOSEYESTERDAY', free - position['today']),
        ) if count)


class VeighNaOfflineGateway(FixtureGateway):
    """Headless composition. Native connect and native send/cancel are unreachable."""

    def __init__(self, *, on_event: Callable, on_error: Callable, on_completed: Callable,
                 on_send: Callable | None = None):
        super().__init__(on_send)
        from gateway_smoke import require_offline

        require_offline()
        from vnpy.event import Event, EventEngine
        from vnpy.trader.engine import MainEngine
        from vnpy.trader.object import OrderRequest
        from vnpy_ctp.gateway.ctp_gateway import CtpGateway, CtpMdApi, CtpTdApi
        from vnpy_portfoliostrategy import StrategyTemplate

        boundary = self
        event_type = 'guiyi.p5.native'

        def offline_only(*args, **kwargs):
            raise RuntimeError('P5_OFFLINE_ONLY')

        class OfflineMd(CtpMdApi):
            connect = offline_only

        class OfflineTd(CtpTdApi):
            connect = offline_only
            send_order = offline_only
            cancel_order = offline_only
            onRspUserLogin = offline_only

        class OfflineCtp(CtpGateway):
            def __init__(self, event_engine, gateway_name):
                super().__init__(event_engine, gateway_name)
                self.md_api = OfflineMd(self)
                self.td_api = OfflineTd(self)

            def connect(self, setting):
                raise RuntimeError('P5_OFFLINE_ONLY')

            def send_order(self, req):
                if not isinstance(req, OrderRequest) or not boundary._prepared:
                    raise RuntimeError('P5_UNCLAIMED_SEND')
                intent = boundary._prepared
                if req.reference != intent['id'] or list(boundary._request_facts(req)) != intent['request']:
                    raise RuntimeError('P5_UNCLAIMED_SEND')
                return FixtureGateway.send(boundary, intent) or ''

            def cancel_order(self, req):
                intent = boundary._prepared
                if (not intent or req.orderid != intent.get('native_id')
                        or req.symbol != intent['native_symbol'] or req.exchange.value != intent['exchange']):
                    raise RuntimeError('P5_UNCLAIMED_CANCEL')
                FixtureGateway.cancel(boundary, intent)

            def on_order(self, order):
                self.event_engine.put(Event(event_type, boundary._normalize(order)))
                super().on_order(order)

            def on_trade(self, trade):
                envelope = boundary._normalize(trade)
                event = envelope[0]
                self.event_engine.put(Event(event_type, envelope))
                # OffsetConverter increments on every TradeData. The durable
                # reducer sees every callback, but OMS gets each fill only once.
                if event.key not in boundary._oms_trades:
                    boundary._oms_trades.add(event.key)
                    super().on_trade(trade)

        class CompletedTemplate(StrategyTemplate):
            def on_init(self):
                self.inited = True

            def on_bars(self, bars):
                # Standard BarData lacks completed journal provenance.
                return None

            def on_completed(self, envelope, window, **proof):
                return on_completed(envelope, window, **proof)

        self._prepared = None
        self._callback = None
        self._callback_lock = Lock()
        self._on_error = on_error
        self._system_orders = {}
        self._oms_trades = set()
        self._contracts = {}
        self._name = 'P5_OFFLINE'
        self.events = EventEngine()
        self.main = MainEngine(self.events)
        self.native = self.main.add_gateway(OfflineCtp, self._name)
        self.template = CompletedTemplate(None, 'newow_p5', [], {})
        self.template.on_init()

        def receive(event):
            native, generation, sequence, known_at = event.data
            try:
                on_event(native, generation=generation, sequence=sequence, known_at=known_at)
            except Exception:
                on_error('P5_CALLBACK_CONFLICT', known_at=known_at)

        self.events.register(event_type, receive)

    def completed(self, envelope, window, **proof):
        return self.template.on_completed(envelope, window, **proof)

    def register_contract(self, policy: dict) -> None:
        super().register_contract(policy)
        scope = (policy['exchange'], policy['native_symbol'].upper())
        prior = self._contracts.setdefault(scope, policy['contract'])
        if prior != policy['contract']:
            raise ValueError('P5_NATIVE_CONTRACT_COLLISION')

    def push_ctp(self, kind: str, fields: dict, *, generation: str, sequence: int,
                 known_at: datetime) -> None:
        """Inject one raw CTP fixture row with its durable source envelope."""
        api = self.native.td_api
        with self._callback_lock:
            try:
                if kind not in ('order', 'trade') or not api.contract_inited:
                    raise ValueError('P5_CTP_CALLBACK_NOT_READY')
                lots(sequence, minimum=1)
                aware(known_at)
                if not generation or not re.fullmatch(r'[0-9]{8}', fields['TradingDay']):
                    raise ValueError('P5_CTP_CALLBACK_SCOPE_MISSING')
                day = datetime.strptime(fields['TradingDay'], '%Y%m%d').date()
                exchange = fields['ExchangeID']
                if (exchange, fields['InstrumentID'].upper()) not in self._contracts:
                    raise ValueError('P5_NATIVE_CONTRACT_MISSING')
                system_id = fields['OrderSysID']
                system_key = (day, exchange, system_id)
                native_id = None
                if kind == 'order':
                    native_id = f"{fields['FrontID']}_{fields['SessionID']}_{fields['OrderRef']}"
                    if system_id.strip():
                        previous = self._system_orders.setdefault(system_key, native_id)
                        if previous != native_id:
                            raise ValueError('P5_CTP_ORDER_ID_CONFLICT')
                elif (not system_id.strip() or not self._system_orders.get(system_key)
                        or self._system_orders[system_key] != api.sysid_orderid_map.get(system_id)):
                    raise ValueError('P5_CTP_TRADE_ORDER_UNBOUND')
                self._callback = (day, exchange, generation, sequence, native_id, known_at)
                if kind == 'order':
                    api.onRtnOrder(fields)
                else:
                    api.onRtnTrade(fields)
                if self._callback is not None:
                    raise ValueError('P5_CTP_CALLBACK_NOT_EMITTED')
            except (ValueError, TypeError, AttributeError, KeyError):
                self._on_error('P5_CTP_CALLBACK_UNVERIFIED', known_at=known_at)
                raise ValueError('P5_CTP_CALLBACK_UNVERIFIED') from None
            finally:
                self._callback = None

    def _normalize(self, row):
        from vnpy.trader.object import OrderData

        if not self._callback:
            raise ValueError('P5_CTP_CALLBACK_SCOPE_MISSING')
        day, exchange, generation, sequence, native_order_id, known_at = self._callback
        offset = row.offset.name
        if (row.exchange.value != exchange or (offset == 'OPEN') != (row.direction.name == 'LONG')
                or row.volume != int(row.volume) or isinstance(row, OrderData) and row.orderid != native_order_id):
            raise ValueError('P5_CTP_CALLBACK_FACT_CONFLICT')
        if isinstance(row, OrderData):
            status = {
                'SUBMITTING': OrderStatus.SUBMITTING, 'NOTTRADED': OrderStatus.ACTIVE,
                'PARTTRADED': OrderStatus.PARTIAL, 'ALLTRADED': OrderStatus.FILLED,
                'CANCELLED': OrderStatus.CANCELLED, 'REJECTED': OrderStatus.REJECTED,
            }[row.status.name]
            if row.traded != int(row.traded):
                raise ValueError('P5_CTP_CALLBACK_FACT_CONFLICT')
            result = NativeOrder(exchange, self._contracts[(exchange, row.symbol.upper())], day, row.orderid, int(row.volume),
                                 int(row.traded), status, offset)
        else:
            result = NativeFill(exchange, self._contracts[(exchange, row.symbol.upper())], day, row.orderid, row.tradeid, int(row.volume),
                                Decimal(str(row.price)), row.datetime, offset)
        self._callback = None
        return result, generation, sequence, known_at

    @staticmethod
    def _request_facts(req):
        return (req.symbol.upper(), req.exchange.value, req.direction.name, req.offset.name,
                format(Decimal(str(req.price)), 'f'), int(req.volume))

    def _request(self, position: dict, *, offset: str, price: Decimal, quantity: int, reference: str,
                 enforce_order_size: bool = True):
        from vnpy.trader.constant import Direction, Exchange, Offset, OrderType
        from vnpy.trader.object import OrderRequest

        contract = self.main.get_contract(f"{position['native_symbol']}.{position['exchange']}")
        if contract is None or contract.gateway_name != self._name:
            raise RuntimeError('P5_NATIVE_CONTRACT_MISSING')
        if (Decimal(str(contract.pricetick)) != Decimal(position['tick'])
                or Decimal(str(contract.size)) != Decimal(position['multiplier'])
                or enforce_order_size and (
                    contract.max_volume is None or not contract.min_volume <= quantity <= contract.max_volume
                )):
            raise ValueError('P5_NATIVE_CONTRACT_CONFLICT')
        return OrderRequest(
            symbol=contract.symbol, exchange=Exchange(position['exchange']),
            direction=Direction.LONG if offset == 'OPEN' else Direction.SHORT,
            type=OrderType.LIMIT, volume=quantity, price=float(price), offset=Offset[offset],
            reference=reference,
        )

    def _intent_request(self, intent):
        req = self._request(intent, offset=intent['offset'], price=Decimal(intent['price']),
                            quantity=intent['quantity'], reference=intent['id'])
        price = Decimal(str(req.price))
        if price != Decimal(intent['price']) or req.volume != intent['quantity']:
            raise ValueError('P5_NATIVE_CONVERSION_LOSS')
        return req

    def validate_request(self, intent: dict) -> None:
        super().validate_request(intent)
        self._intent_request(intent)

    def send(self, intent: dict) -> str | None:
        req = self._intent_request(intent)
        self._prepared = dict(intent, request=list(self._request_facts(req)))
        try:
            return self.main.send_order(req, self._name) or None
        finally:
            self._prepared = None

    def cancel(self, intent: dict) -> None:
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import CancelRequest

        self._prepared = intent
        try:
            self.main.cancel_order(CancelRequest(intent['native_id'], intent['native_symbol'],
                                                Exchange(intent['exchange'])), self._name)
        finally:
            self._prepared = None

    def close_legs(self, position: dict) -> tuple[tuple[str, int], ...]:
        from vnpy.trader.constant import Direction
        from vnpy.trader.converter import PositionHolding
        from vnpy.trader.object import PositionData

        safe = super().close_legs(position)
        if not safe or position['exchange'] not in {'SHFE', 'INE'}:
            return safe
        quantity = sum(count for _, count in safe)
        try:
            request = self._request(position, offset='CLOSE', price=Decimal(1), quantity=quantity,
                                    reference='p5-close-plan', enforce_order_size=False)
        except (ValueError, RuntimeError):
            return ()
        # Plan from the verified absolute snapshot so a cold OMS cache, delayed
        # position event or cached order cannot supply a fictional close bucket.
        holding = PositionHolding(self.main.get_contract(request.vt_symbol))
        holding.update_position(PositionData(
            gateway_name=self._name, symbol=request.symbol, exchange=request.exchange, direction=Direction.LONG,
            volume=position['quantity'], frozen=position['frozen'], yd_volume=position['quantity'] - position['today'],
        ))
        requests = holding.convert_order_request_shfe(request)
        legs = tuple((req.offset.name, int(req.volume)) for req in requests)
        return legs if dict(legs) == dict(safe) and sum(qty for _, qty in legs) == quantity else ()

    def close(self):
        self.main.close()
