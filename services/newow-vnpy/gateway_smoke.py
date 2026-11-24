r"""VeighNa P1-B native import and offline Python callback probe.

From this service directory, use a fresh cache and Apple Clang to build the
locked dependencies from public PyPI:

    UV_CACHE_DIR="$(mktemp -d /private/tmp/guiyi-vnpy-cache.XXXXXXXX)" \
        CC=/usr/bin/clang CXX=/usr/bin/clang++ uv sync --locked \
        --default-index https://pypi.org/simple --no-python-downloads \
        --python /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13

Use a fresh private directory for every offline run after installation:

    service_dir="$PWD"
    run_dir="$(mktemp -d /private/tmp/guiyi-vnpy-smoke.XXXXXXXX)"
    mkdir -m 700 "$run_dir/.vntrader"
    legacy_vntrader=~/.vntrader
    (
        cd "$run_dir" &&
        /usr/bin/env -i PATH=/usr/bin:/bin GUIYI_VNPY_PROBE_DIR="$run_dir" \
            /usr/bin/sandbox-exec -D "GUIYI_LEGACY_VNTRADER=$legacy_vntrader" \
            -p '(version 1) (allow default) (deny network*)
                (deny file-read* file-write* (subpath (param "GUIYI_LEGACY_VNTRADER")))' \
            "$service_dir/.venv/bin/python" -I -B "$service_dir/gateway_smoke.py"
    )

For pytest, add PYTHONPATH="$service_dir" and PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
to env, then use python -s -B -m pytest -q -p no:cacheprovider "$service_dir/tests".
"""

from datetime import datetime
from enum import Enum
import errno
from importlib import import_module
from importlib.machinery import ExtensionFileLoader
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import socket
import stat
import sys
from threading import Event as ThreadEvent


def require_offline() -> None:
    """Reject non-isolated paths and require denied IPv4 loopback binding."""
    runtime = (
        platform.system(),
        platform.machine(),
        platform.python_implementation(),
        platform.python_version(),
    )
    if runtime != ("Darwin", "arm64", "CPython", "3.13.3"):
        raise RuntimeError("This probe requires macOS arm64 and CPython 3.13.3")

    run_dir = Path.cwd()
    config_dir = run_dir / ".vntrader"
    expected_dir = Path(os.environ.get("GUIYI_VNPY_PROBE_DIR", ""))
    if (
        not expected_dir.is_absolute()
        or expected_dir.resolve() != run_dir
        or Path("/private/tmp") not in run_dir.parents
    ):
        raise RuntimeError("Use a private temporary working directory set by GUIYI_VNPY_PROBE_DIR")

    for path in (run_dir, config_dir):
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise RuntimeError("Precreate the private .vntrader directory") from None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise RuntimeError("The working directory and .vntrader must be private directories")

    utility = sys.modules.get("vnpy.trader.utility")
    if utility is None:
        if any(config_dir.iterdir()):
            raise RuntimeError("Start with an empty private .vntrader directory")
    elif utility.TEMP_DIR != config_dir:
        raise RuntimeError("VeighNa already initialized a different .vntrader directory")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            return
        raise
    raise RuntimeError("Use the native macOS deny-network sandbox")


def _require_version(package: str, expected: str) -> None:
    actual = version(package)
    if actual != expected:
        raise RuntimeError(f"{package} {expected} required, found {actual}")


def import_ctp():
    """Import the real gateway and both compiled extension modules."""
    require_offline()
    from vnpy_ctp import CtpGateway

    _require_version("vnpy", "4.4.0")
    _require_version("vnpy-ctp", "6.7.11.4")
    modules = tuple(import_module(f"vnpy_ctp.api.{name}") for name in ("vnctpmd", "vnctptd"))
    for module in modules:
        if not isinstance(module.__spec__.loader, ExtensionFileLoader):
            raise RuntimeError(f"{module.__name__} did not load as a native extension")
    return CtpGateway, modules


def import_portfolio_strategy():
    require_offline()
    from vnpy_portfoliostrategy import PortfolioStrategyApp

    _require_version("vnpy", "4.4.0")
    _require_version("vnpy-portfoliostrategy", "1.3.0")
    return PortfolioStrategyApp


def capture_gateway_callbacks() -> list[tuple[str, object]]:
    """Inject deterministic fixture dictionaries at the concrete callback methods."""
    gateway_type, _ = import_ctp()
    from vnpy.event import Event, EventEngine
    from vnpy.trader.event import (
        EVENT_ACCOUNT,
        EVENT_CONTRACT,
        EVENT_ORDER,
        EVENT_POSITION,
        EVENT_TICK,
        EVENT_TRADE,
    )
    from vnpy_ctp import api
    from vnpy_ctp.gateway.ctp_gateway import symbol_contract_map

    symbol = "rb9911"
    if symbol in symbol_contract_map:
        raise RuntimeError("The fixture instrument is already present in the gateway")

    engine = EventEngine()
    gateway = gateway_type(engine, "CTP_FIXTURE")
    event_names = {
        EVENT_CONTRACT: "contract",
        EVENT_TICK: "tick",
        EVENT_ORDER: "order",
        EVENT_TRADE: "trade",
        EVENT_ACCOUNT: "account",
        EVENT_POSITION: "position",
    }
    received: list[tuple[str, object]] = []
    drained = ThreadEvent()
    barrier = "guiyi-fixture-drained"

    def record(event: Event) -> None:
        received.append((event_names[event.type], event.data))

    for event_type in event_names:
        engine.register(event_type, record)
    engine.register(barrier, lambda event: drained.set())
    engine.start()
    try:
        td = gateway.td_api
        td.onRspQryInstrument({
            "InstrumentID": symbol,
            "ExchangeID": "SHFE",
            "InstrumentName": "Fixture future",
            "ProductClass": api.THOST_FTDC_PC_Futures,
            "VolumeMultiple": 10,
            "PriceTick": 0.5,
            "MinLimitOrderVolume": 1,
            "MaxLimitOrderVolume": 10,
        }, {"ErrorID": 0, "ErrorMsg": ""}, 1, True)
        gateway.md_api.onRtnDepthMarketData({
            "InstrumentID": symbol,
            "ActionDay": "20261124",
            "UpdateTime": "09:30:01",
            "UpdateMillisec": 125,
            "Volume": 154,
            "Turnover": 150000,
            "OpenInterest": 220,
            "LastPrice": 103.5,
            "UpperLimitPrice": 110,
            "LowerLimitPrice": 90,
            "OpenPrice": 101,
            "HighestPrice": 104,
            "LowestPrice": 99,
            "PreClosePrice": 102,
            "BidPrice1": 103,
            "AskPrice1": 104,
            "BidVolume1": 5,
            "AskVolume1": 8,
            "BidVolume2": 0,
            "AskVolume2": 0,
        })

        order = {
            "InstrumentID": symbol,
            "FrontID": 7,
            "SessionID": 13,
            "OrderRef": "000042",
            "OrderSysID": " 000089",
            "OrderStatus": api.THOST_FTDC_OST_PartTradedQueueing,
            "InsertDate": "20261124",
            "InsertTime": "09:30:02",
            "OrderPriceType": api.THOST_FTDC_OPT_LimitPrice,
            "TimeCondition": api.THOST_FTDC_TC_GFD,
            "VolumeCondition": api.THOST_FTDC_VC_AV,
            "Direction": api.THOST_FTDC_D_Sell,
            "CombOffsetFlag": api.THOST_FTDC_OFEN_CloseToday,
            "LimitPrice": 103.5,
            "VolumeTotalOriginal": 3,
            "VolumeTraded": 2,
            "OrderSubmitStatus": api.THOST_FTDC_OSS_Accepted,
            "StatusMsg": "",
        }
        td.onRtnOrder(order)

        trade = {
            "InstrumentID": symbol,
            "OrderSysID": " 000089",
            "TradeID": "000101",
            "TradeDate": "20261124",
            "TradeTime": "09:30:03",
            "Direction": api.THOST_FTDC_D_Sell,
            "OffsetFlag": api.THOST_FTDC_OFEN_CloseToday,
            "Price": 103.5,
            "Volume": 1,
        }
        td.onRtnTrade(trade)
        td.onRtnTrade(trade.copy())
        td.onRtnTrade(dict(trade, TradeID="000102"))
        td.onRtnOrder(dict(order, OrderStatus=api.THOST_FTDC_OST_Canceled, StatusMsg="已撤单"))

        td.onRspQryTradingAccount({
            "AccountID": "FIXTURE",
            "Balance": 1000,
            "FrozenMargin": 0,
            "FrozenCash": 0,
            "FrozenCommission": 0,
            "Available": 900,
        }, {"ErrorID": 0, "ErrorMsg": ""}, 2, True)
        td.onRspQryInvestorPosition({
            "InstrumentID": symbol,
            "PosiDirection": api.THOST_FTDC_PD_Long,
            "Position": 1,
            "TodayPosition": 1,
            "YdPosition": 0,
            "PositionCost": 990,
            "PositionProfit": 45,
            "ShortFrozen": 0,
        }, {"ErrorID": 0, "ErrorMsg": ""}, 3, True)

        engine.put(Event(barrier))
        if not drained.wait(timeout=5):
            raise RuntimeError("VeighNa EventEngine did not drain the fixture callbacks")
        observed = [kind for kind, _ in received]
        expected = [
            "contract", "tick", "order", "trade", "trade", "trade", "order",
            "account", "position",
        ]
        if observed != expected:
            raise RuntimeError(f"Unexpected VeighNa fixture event sequence: {observed}")
        return received
    finally:
        try:
            gateway.close()
        finally:
            engine.stop()
            symbol_contract_map.pop(symbol, None)


def _blocked(exc: Exception) -> dict[str, str]:
    return {"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}


def _event_value(value: datetime | Enum) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    raise TypeError(f"Unsupported fixture field: {type(value).__name__}")


def main() -> int:
    report = {"machine": platform.machine(), "python": platform.python_version()}
    try:
        require_offline()
    except (RuntimeError, OSError) as exc:
        report["offline_guard"] = _blocked(exc)
        print(json.dumps(report, indent=2))
        return 1

    report["offline_guard"] = {"status": "PASSED", "loopback_bind_denied": True}
    try:
        app = import_portfolio_strategy()
        report["portfolio_strategy_import"] = {
            "status": "PASSED",
            "app": app.app_name,
            "version": version("vnpy-portfoliostrategy"),
            "vnpy_version": version("vnpy"),
        }
    except Exception as exc:
        report["portfolio_strategy_import"] = _blocked(exc)

    try:
        gateway, modules = import_ctp()
        report["ctp_native_import"] = {
            "status": "PASSED",
            "gateway": gateway.__name__,
            "version": version("vnpy-ctp"),
            "extensions": {module.__name__: module.__file__ for module in modules},
        }
    except Exception as exc:
        report["ctp_native_import"] = _blocked(exc)
        report["ctp_gateway_callbacks"] = {
            "status": "BLOCKED",
            "reason": "CTP native import is required",
        }
    else:
        try:
            callbacks = capture_gateway_callbacks()
            report["ctp_gateway_callbacks"] = {
                "status": "CAPTURED",
                "events": [{"kind": kind, **vars(payload)} for kind, payload in callbacks],
            }
        except Exception as exc:
            report["ctp_gateway_callbacks"] = _blocked(exc)

    print(json.dumps(report, default=_event_value, indent=2, ensure_ascii=False))
    return int(any(
        item.get("status") == "BLOCKED" for item in report.values() if isinstance(item, dict)
    ))


if __name__ == "__main__":
    raise SystemExit(main())
