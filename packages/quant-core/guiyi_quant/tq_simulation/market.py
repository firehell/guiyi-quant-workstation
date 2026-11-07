"""Bounded local IPC to the existing API environment's sole market authority."""

from pathlib import Path
from datetime import date, datetime, UTC, timedelta
from zoneinfo import ZoneInfo
import subprocess
import json
import selectors
import os
from uuid import uuid4
from ..htdy_account_execution import codec, model as m
from .gateway import decimal, quantity
from .journal import digest

EXCHANGES = {
    "XSGE": "SHFE",
    "SHFE": "SHFE",
    "XZCE": "CZCE",
    "CZCE": "CZCE",
    "XDCE": "DCE",
    "DCE": "DCE",
    "XINE": "INE",
    "INE": "INE",
    "XSIE": "INE",
    "CCFX": "CFFEX",
    "CFFEX": "CFFEX",
    "GFEX": "GFEX",
    "XGFE": "GFEX",
}


class Market:
    def __init__(self, root, api_python, environment=None):
        root = Path(root).resolve(strict=True)
        python = Path(api_python).absolute()
        if python != root / "services/quant-api/.venv/bin/python":
            raise ValueError("TQ_MARKET_INTERPRETER_INVALID")
        self.process = subprocess.Popen(
            [str(python), "-m", "app.tq_simulation_market"],
            cwd=root,
            env={**(os.environ if environment is None else environment), "GUIYI_PROJECT_ROOT": str(root)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.pump = None
        self.buffer = b""
        self.failed = False
        self.products = tuple(self.request({"mode": "hello"})["products"])

    def request(self, payload):
        import time

        if self.failed:
            raise ValueError("TQ_MARKET_CHANNEL_FAILED")
        request_id = uuid4().hex
        raw = (
            json.dumps({**payload, "request_id": request_id}, separators=(",", ":"))
            + "\n"
        ).encode()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("TQ_MARKET_REQUEST_TOO_LARGE")
        end = time.monotonic() + 20
        deferred = None

        def drive():
            nonlocal deferred
            if deferred is None and self.pump is not None:
                try:
                    self.pump()
                except Exception as error:
                    # Consume this response before surfacing continuity failure.
                    # Its signals are discarded; the next request cannot see its ID.
                    deferred = error
        fd = self.process.stdin.fileno()
        os.set_blocking(fd, False)
        sent = 0
        with selectors.DefaultSelector() as writer:
            writer.register(fd, selectors.EVENT_WRITE)
            while sent < len(raw):
                if time.monotonic() >= end:
                    self.failed = True
                    raise ValueError("TQ_MARKET_TIMEOUT")
                drive()
                if writer.select(min(0.05, max(0, end - time.monotonic()))):
                    try:
                        sent += os.write(fd, raw[sent:sent + 65536])
                    except BlockingIOError:
                        pass
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                if time.monotonic() >= end:
                    self.failed = True
                    raise ValueError("TQ_MARKET_TIMEOUT")
                drive()
                if not selector.select(min(0.05, max(0, end - time.monotonic()))):
                    continue
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    self.failed = True
                    raise ValueError("TQ_MARKET_UNAVAILABLE")
                self.buffer += chunk
                if len(self.buffer) > 32 * 1024 * 1024:
                    self.failed = True
                    raise ValueError("TQ_MARKET_RESPONSE_TOO_LARGE")
        line, self.buffer = self.buffer.split(b"\n", 1)
        result = json.loads(line)
        if result.get("request_id") != request_id:
            self.failed = True
            raise ValueError("TQ_MARKET_RESPONSE_IDENTITY_INVALID")
        if deferred is not None:
            raise deferred
        if result.get("status") != "ok":
            raise ValueError("TQ_MARKET_AUTHORITY_UNAVAILABLE")
        return result

    def poll(self, state=None, contracts=(), *, inspect=False):
        return self.request(
            {
                "mode": "inspect" if inspect else "poll",
                "state": market_state(state) if state else None,
                "contracts": [
                    {"product": p, "contract": c} for p, c in sorted(set(contracts))
                ],
            }
        )

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


def bind_symbol(gateway, controller, authority):
    exchange = EXCHANGES.get(authority["exchange"])
    if exchange is None:
        raise ValueError("TQ_EXCHANGE_UNSUPPORTED")
    contract = authority["contract"]
    product = authority["product"]
    # RQData supplies the actual exchange trading code. For missing codes, query
    # the provider's listed contracts and require a unique exact expiry match.
    code = authority.get("trading_code")
    candidates = []
    if code and "." not in code:
        candidates = [exchange + "." + code]
    else:
        symbols = gateway.api.query_quotes(
            ins_class="FUTURE",
            exchange_id=exchange,
            product_id=product if exchange == "CZCE" else product.lower(),
            expired=False,
        )
        if not authority.get("maturity_date"):
            raise ValueError("TQ_CONTRACT_EXPIRY_UNAVAILABLE")
        maturity = date.fromisoformat(authority["maturity_date"])
        for symbol in symbols:
            q = gateway.quote(symbol)
            if (
                q.get("delivery_year") == maturity.year
                and q.get("delivery_month") == maturity.month
            ):
                candidates.append(symbol)
    if len(candidates) != 1:
        raise ValueError("TQ_SYMBOL_MAPPING_UNPROVEN")
    symbol = candidates[0]
    q = gateway.quote(symbol)
    if (
        q.get("instrument_id") != symbol
        or q.get("ins_class") != "FUTURE"
        or q.get("expired") is not False
        or decimal(q.get("volume_multiple"), positive=True)
        != decimal(authority["multiplier"], positive=True)
    ):
        raise ValueError("TQ_CONTRACT_METADATA_MISMATCH")
    controller.bind_symbol(symbol, product, contract)
    return symbol


def execution_input(gateway, authority, symbol, side, *, opening, cancelling=False):
    q = gateway.quote(symbol)
    now = datetime.now(UTC)
    session = codec.decode(authority["session"])
    if not session.at <= now < session.valid_until:
        raise ValueError("TQ_SESSION_STALE")
    margin = fee = None
    source = {"source": "TQKQ_QUOTE_METADATA"}
    if opening:
        margin, fee, source = gateway.margin(symbol, side)
    now = datetime.now(UTC)
    if not session.at <= now < session.valid_until:
        raise ValueError("TQ_SESSION_STALE")
    stamp = None
    if not cancelling:
        stamp = datetime.fromisoformat(q["datetime"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        stamp = stamp.astimezone(UTC)
        if stamp > now or now - stamp > timedelta(seconds=5):
            raise ValueError("TQ_QUOTE_STALE")
    instrument = m.TqKqInstrument(
        authority["product"],
        authority["contract"],
        now,
        now + timedelta(seconds=5),
        "tq-instrument:" + digest(source),
        decimal(q["price_tick"], positive=True),
        decimal(q["volume_multiple"], positive=True),
        margin,
        fee,
        quantity(q.get("min_limit_order_volume")),
    )
    if cancelling:
        return m.TqKqExecutionInput(instrument, session, None)
    quote = m.Quote(
        authority["contract"],
        stamp,
        stamp + timedelta(seconds=5),
        "tq-quote:"
        + digest(
            {
                "symbol": symbol,
                "at": q["datetime"],
                "bid": str(q["bid_price1"]),
                "ask": str(q["ask_price1"]),
            }
        ),
        decimal(q["bid_price1"], positive=True),
        decimal(q["ask_price1"], positive=True),
        quantity(q["bid_volume1"]),
        quantity(q["ask_volume1"]),
        decimal(q["lower_limit"], positive=True),
        decimal(q["upper_limit"], positive=True),
    )
    return m.TqKqExecutionInput(instrument, session, quote)


def market_state(state):
    """Private market request v2: bounded by scope, never by account history."""
    return dict(version="tq_market_state_v2", phase=state.phase,
                activated_at=codec.encode(state.activated_at),
                blocked_products=list(state.blocked_products),
                products=[dict(product=p.product, owner=p.owner, desired=p.desired,
                               signal_id=bool(p.signal_id), last_bar=codec.encode(p.last_bar))
                          for p in state.products],
                positions=[dict(product=p.product, quantity=p.quantity) for p in state.positions])


def load_market_state(packet):
    from types import SimpleNamespace as NS
    if (type(packet) is not dict or set(packet) != {
            "version", "phase", "activated_at", "blocked_products", "products", "positions"}
            or packet["version"] != "tq_market_state_v2"
            or packet["phase"] not in {"READY", "RECOVERY_REQUIRED", "BLOCKED"}
            or not 1 <= len(packet["products"]) <= 60):
        raise ValueError("TQ_MARKET_STATE_INVALID")
    products = []
    for p in packet["products"]:
        if (set(p) != {"product", "owner", "desired", "signal_id", "last_bar"}
                or type(p["signal_id"]) is not bool or p["desired"] not in (-1, 0, 1)):
            raise ValueError("TQ_MARKET_STATE_INVALID")
        products.append(NS(**{**p, "last_bar": codec.decode(p["last_bar"])}))
    names = {p.product for p in products}
    if len(names) != len(products) or set(packet["blocked_products"]) - names:
        raise ValueError("TQ_MARKET_STATE_INVALID")
    positions = []
    for p in packet["positions"]:
        if set(p) != {"product", "quantity"} or p["product"] not in names or p["quantity"] not in (-1, 1):
            raise ValueError("TQ_MARKET_STATE_INVALID")
        positions.append(NS(**p))
    return NS(phase=packet["phase"], activated_at=codec.decode(packet["activated_at"]),
              blocked_products=tuple(packet["blocked_products"]),
              products=tuple(products), positions=tuple(positions))
