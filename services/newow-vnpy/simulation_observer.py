"""Headless, read-only SimNow account observer using the pinned VeighNa runtime."""

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
from importlib.metadata import version
import os
from pathlib import Path
from queue import Empty, Full, Queue
import signal
import stat
from threading import Event as Flag, Lock
from time import monotonic

import psycopg

from app.simulation_center.config import ObserverConfig, read_config
from app.simulation_center.readback import Readback, ReadbackError, SECTIONS
from app.simulation_center.store import Writer

EVENT = "eGuiyiSimulationObserver"
QUERY_METHODS = {
    "account": "reqQryTradingAccount", "positions": "reqQryInvestorPosition",
    "orders": "reqQryOrder", "fills": "reqQryTrade",
}
QUERY_INTERVAL = 1.1
QUERY_TIMEOUT = 8
SAMPLE_INTERVAL = 30


def build_gateway(messages: Queue, overflow: Flag):
    from vnpy.event import Event, EventEngine
    from vnpy.trader.engine import MainEngine
    from vnpy.trader.setting import SETTINGS
    from vnpy_ctp.gateway.ctp_gateway import CtpGateway, CtpTdApi

    class ObservationTd(CtpTdApi):
        def onFrontDisconnected(self, reason):
            self.login_status = False
            self.gateway.emit("disconnected")

        def onRspAuthenticate(self, data, error, reqid, last):
            if error.get("ErrorID"):
                self.auth_failed = True
                self.gateway.emit("login_failed")
            else:
                self.auth_status = True
                self.login()

        def onRspUserLogin(self, data, error, reqid, last):
            if (error.get("ErrorID") or not last or reqid != self.reqid
                    or data.get("BrokerID") != self.brokerid or data.get("UserID") != self.userid
                    or not data.get("TradingDay")):
                self.login_failed = True
                self.gateway.emit("login_failed")
                return
            self.login_status = True
            self.gateway.emit("login", data["TradingDay"])
            # The stock login callback would send reqSettlementInfoConfirm here.

        def onRtnOrder(self, data):
            self.gateway.emit("changed")

        def onRtnTrade(self, data):
            self.gateway.emit("changed")

        def onRspQryTradingAccount(self, data, error, reqid, last):
            self.gateway.emit("reply", "account", reqid, data, error.get("ErrorID", 0), last)

        def onRspQryInvestorPosition(self, data, error, reqid, last):
            self.gateway.emit("reply", "positions", reqid, data, error.get("ErrorID", 0), last)

        def onRspQryOrder(self, data, error, reqid, last):
            self.gateway.emit("reply", "orders", reqid, data, error.get("ErrorID", 0), last)

        def onRspQryTrade(self, data, error, reqid, last):
            self.gateway.emit("reply", "fills", reqid, data, error.get("ErrorID", 0), last)

        def send_order(self, req):
            raise ReadbackError("OBSERVER_READ_ONLY")

        def cancel_order(self, req):
            raise ReadbackError("OBSERVER_READ_ONLY")

    class ObservationGateway(CtpGateway):
        def __init__(self, event_engine, gateway_name):
            super().__init__(event_engine, gateway_name)
            self.td_api = ObservationTd(self)
            self.fence = 0
            self.fence_lock = Lock()

        def emit(self, *message):
            with self.fence_lock:
                if message[0] in {"login", "disconnected", "login_failed", "changed"}:
                    self.fence += 1
                if message[0] == "reply":
                    message = (*message, self.fence, datetime.now(UTC))
                self.event_engine.put(Event(EVENT, message))

        def publish(self, writer, snapshot, fence):
            with self.fence_lock:
                if self.fence != fence:
                    raise ReadbackError("NATIVE_FENCE_CHANGED")
            writer.publish(snapshot)
            with self.fence_lock:
                return self.fence == fence

        def connect(self, config: ObserverConfig):
            self.td_api.connect(config.front, config.user, config.password,
                                "9999", config.auth_code, config.app_id)

        def query(self, section, collect):
            if not self.td_api.login_status:
                raise ReadbackError("NOT_LOGGED_IN")
            self.td_api.reqid += 1
            request_id = self.td_api.reqid
            collect.request(section, request_id)
            arguments = {"BrokerID": self.td_api.brokerid, "InvestorID": self.td_api.userid}
            if section == "account":
                arguments["CurrencyID"] = "CNY"
            if getattr(self.td_api, QUERY_METHODS[section])(arguments, request_id) != 0:
                raise ReadbackError("NATIVE_QUERY_REJECTED")

        def write_log(self, msg):
            pass

        def send_order(self, req):
            raise ReadbackError("OBSERVER_READ_ONLY")

        def cancel_order(self, req):
            raise ReadbackError("OBSERVER_READ_ONLY")

        def close(self):
            self.td_api.close()

    def forward(event):
        try:
            messages.put_nowait(event.data)
        except Full:
            overflow.set()

    SETTINGS["log.active"] = False
    SETTINGS["log.file"] = False
    events = EventEngine()
    events.register(EVENT, forward)
    engine = MainEngine(events)
    return engine, engine.add_gateway(ObservationGateway, "SIMNOW_OBSERVER")


def observe(config: ObserverConfig, writer: Writer, stop: Flag):
    messages = Queue(maxsize=8192)
    overflow = Flag()
    engine, gateway = build_gateway(messages, overflow)
    state = Readback()
    next_action = monotonic()
    last_query = float("-inf")
    up_to_date = False

    try:
        gateway.connect(config)
        while not stop.is_set():
            try:
                message = messages.get(timeout=0.25)
            except Empty:
                message = ()
            if overflow.is_set():
                raise ReadbackError("NATIVE_EVENT_OVERFLOW")

            match message:
                case ("login", day):
                    state.login(state.generation + 1, day)
                    writer.status("RECONCILING")
                    up_to_date = False
                    next_action = monotonic()
                case ("login_failed",):
                    raise ReadbackError("NATIVE_LOGIN_FAILED")
                case ("disconnected",):
                    state.disconnect()
                    writer.status("DISCONNECTED")
                    up_to_date = False
                case ("changed",):
                    state.changed()
                    if up_to_date:
                        writer.status("RECONCILING")
                        up_to_date = False
                    if state.started is None:
                        next_action = monotonic()
                case ("reply", section, reqid, data, code, last, fence, observed_at):
                    try:
                        complete = state.reply(section, reqid, data, code, last)
                        if complete and section == "fills":
                            snapshot = state.complete(config.user, observed_at)
                            up_to_date = gateway.publish(writer, snapshot, fence)
                            if not up_to_date:
                                writer.status("RECONCILING")
                            state.discard()
                            next_action = monotonic() + SAMPLE_INTERVAL
                        elif complete:
                            next_action = last_query + QUERY_INTERVAL
                    except ReadbackError:
                        writer.status("READBACK_FAILED")
                        up_to_date = False
                        state.discard()
                        next_action = monotonic() + SAMPLE_INTERVAL

            if state.day is None or monotonic() < next_action or not messages.empty():
                continue
            if state.pending:
                writer.status("READBACK_FAILED")
                up_to_date = False
                state.discard()
                next_action = monotonic() + SAMPLE_INTERVAL
                continue
            if monotonic() < last_query + QUERY_INTERVAL:
                continue
            if state.started is None:
                state.begin(datetime.now(UTC))
            try:
                last_query = monotonic()
                gateway.query(SECTIONS[len(state.rows)], state)
                next_action = last_query + QUERY_TIMEOUT
            except ReadbackError:
                writer.status("READBACK_FAILED")
                up_to_date = False
                state.discard()
                next_action = monotonic() + SAMPLE_INTERVAL
    except (ReadbackError, ValueError):
        writer.status("OBSERVER_FAILED")
        raise
    else:
        writer.status("STOPPED")
    finally:
        engine.close()


def _private_directory(path: Path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("PRIVATE_WORKDIR_REQUIRED")


@contextmanager
def claim_workdir(path: Path, alias: str):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("PRIVATE_WORKDIR_REQUIRED")
    _private_directory(path)
    lock = path / ".simulation-owner"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("PRIVATE_WORKDIR_REQUIRED")
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner = file.read(64).strip()
        if owner and owner != alias:
            raise ReadbackError("WORKDIR_ACCOUNT_CONFLICT")
        if not owner:
            file.seek(0)
            file.write(alias + "\n")
            file.flush()
            os.fsync(file.fileno())
        vntrader = path / ".vntrader"
        flow = vntrader / "simnow_observer"
        for directory in (vntrader, flow):
            directory.mkdir(mode=0o700, exist_ok=True)
            _private_directory(directory)
        previous = Path.cwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(previous)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe", action="store_true", required=True)
    parser.add_argument("--account-config", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = read_config(args.account_config)
        if version("vnpy") != "4.4.0" or version("vnpy-ctp") != "6.7.7.2":
            raise ReadbackError("NATIVE_RUNTIME_VERSION_MISMATCH")
        dsn = os.environ["GUIYI_SIMULATION_WRITER_DSN"]
        stop = Flag()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        with claim_workdir(args.workdir, config.alias), Writer.claim(dsn, config) as writer:
            observe(config, writer, stop)
    except (ImportError, KeyError, OSError, ValueError, psycopg.Error):
        parser.exit(1, "SIMULATION_OBSERVER_UNAVAILABLE\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
