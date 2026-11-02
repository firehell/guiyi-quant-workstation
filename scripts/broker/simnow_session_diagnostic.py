"""One claimed SimNow login diagnostic, using the retained host's ordinary budget.

This is an isolated reader, not a recovery host. It cannot attach an execution
adapter, confirm settlement, submit/cancel orders, or write the account journals.
An apply claim is never removed or refunded, including on unknown outcomes.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "output/simnow-preopen-20261101/simnow-v64/trade-v64-pending.private.json"
STATE = Path.home() / "Library/Application Support/GuiyiQuant/simnow-session-diagnostic-20261103"
PROBE = Path("/private/tmp/guiyi-simnow-probe-20261102/production-proof.json")
PID = 15566
RUN = "4af489cab654450db267587ee3b5c0f7"
DAY = "20261103"
BLOCK = "CONTINUOUS_RECOVERY_REQUIRED"
FAILURE_NAME = "failure-" + RUN + "-10342.json"
FAILURE_SHA = "e226869bbf4705518db57504503466330c42d126e21df998caa50e6cb27b7cf7"
DATABASES = ("account.sqlite", "dispatch.sqlite", "signals.sqlite", "native-evidence.sqlite")
METHODS = {"ReqAuthenticate": 1, "ReqUserLogin": 1, "ReqQryTradingAccount": 2,
           "ReqQryInvestorPosition": 2, "ReqQryOrder": 2, "ReqQryTrade": 2}


class DiagnosticError(ValueError):
    """Only this fixed code crosses the process boundary."""


def invalid():
    raise DiagnosticError("SESSION_DIAGNOSTIC_STOPPED")


def now():
    return datetime.now(UTC)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def private(path, *, directory=False):
    path = Path(path)
    info = path.lstat()
    if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)):
        invalid()
    return path


def read_file(path):
    path = private(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.getuid() or before.st_nlink != 1
                or before.st_size > 128 * 1024 * 1024):
            invalid()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(128 * 1024 * 1024 + 1)
        after = os.fstat(fd)
        signature = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
                                  item.st_ctime_ns, item.st_mode, item.st_uid, item.st_nlink)
        if signature(before) != signature(after) or signature(path.lstat()) != signature(after):
            invalid()
        return raw, dict(device=after.st_dev, inode=after.st_ino, size=len(raw),
                         sha256=hashlib.sha256(raw).hexdigest())
    finally:
        os.close(fd)


def read_json(path):
    raw, identity = read_file(path)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                invalid()
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    if type(value) is not dict:
        invalid()
    return value, identity


def new_file(path, raw):
    private(path.parent, directory=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


@contextmanager
def switch_lock(path):
    private(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = path.stat()
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
            invalid()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield (info.st_dev, info.st_ino)
    finally:
        os.close(fd)


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        invalid()
    return result.stdout.strip()


def process_binding(settings, config):
    expected = " ".join((str(settings.sdk_python), "-I", str(settings.project_root /
                          "scripts/broker/simnow_supervisor.py"), "--config", str(config), "--trade"))
    actual = command(["/bin/ps", "-p", str(PID), "-o", "command="])
    birth = command(["/bin/ps", "-p", str(PID), "-o", "lstart="])
    owner = command(["/bin/ps", "-p", str(PID), "-o", "uid="])
    if actual != expected or not birth or owner != str(os.getuid()):
        invalid()
    return dict(pid=PID, birth=birth, command_sha256=hashlib.sha256(actual.encode()).hexdigest(),
                process_identity=hashlib.sha256(f"{PID}:{birth}".encode()).hexdigest())


def held_by_original(path):
    private(path)
    output = command(["/usr/sbin/lsof", "-nP", "-Fpn", "--", str(path)])
    if {line for line in output.splitlines() if line.startswith("p")} != {"p" + str(PID)}:
        invalid()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (path.stat().st_dev, path.stat().st_ino):
            invalid()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        invalid()
    finally:
        os.close(fd)


def probe_binding(path, binding, at):
    value, identity = read_json(path)
    stamp = datetime.fromisoformat(value["proof_at"])
    if (stamp.tzinfo is None or not 0 <= (at - stamp).total_seconds() <= 90
            or value.get("status") != "READ_ONLY_INSPECTED" or value.get("detached") is not True
            or value.get("pid") != PID or value.get("process_identity") != binding["process_identity"]
            or value.get("target_calls") != 0 or value.get("target_writes") != 0
            or value.get("gateway_count") != 0 or value.get("portfolio_count") != 0
            or value.get("retained_portfolios") != [] or value.get("supervisor_count") != 1
            or value.get("supervisors") != [dict(driver_absent=True, expected_run=True,
                                                host_absent=True, pending=True)]):
        invalid()
    return identity


def _cell(value):
    return {"blob": value.hex()} if isinstance(value, bytes) else value


def tables(conn):
    schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    result = {}
    for kind, name, unused, definition in schema:
        if kind != "table":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = [[_cell(cell) for cell in row] for row in conn.execute("SELECT * FROM " + quoted)]
        rows.sort(key=encoded)
        result[name] = sha(rows)
    return dict(schema_sha256=sha(schema), tables=result)


def budget_rows(conn, account):
    if conn.execute("SELECT account FROM identity").fetchall() != [(account,)]:
        invalid()
    return dict(attempts=[list(row) for row in conn.execute("SELECT day,count FROM attempts ORDER BY day")],
                blocks=[list(row) for row in conn.execute("SELECT day,code FROM blocks ORDER BY day")])


def database(path, account, *, copies=None):
    private(path)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        invalid()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        result = tables(conn)
        raw, identity = read_file(path)
        if raw[:16] != b"SQLite format 3\x00" or raw[18:20] != b"\x01\x01":
            invalid()
        result["file"] = identity
        if copies is not None:
            new_file(copies / (path.name + ".before"), raw)
        if path.name == "signals.sqlite":
            result["budget"] = budget_rows(conn, account)
    return result


def spend_budget(path, account, frozen):
    """The sole production write: preserve every other row and the same-day block."""
    private(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if read_file(path)[1] != frozen["file"]:
            invalid()
        if tables(conn) != {key: frozen[key] for key in ("schema_sha256", "tables")}:
            invalid()
        before = budget_rows(conn, account)
        if (before != frozen["budget"] or dict(before["attempts"]).get(DAY) != 1
                or dict(before["blocks"]).get(DAY) != BLOCK):
            invalid()
        # Reject schema triggers or any accidental writes beyond this one column.
        def authorizer(action, arg1, arg2, database_name, trigger):
            if action == sqlite3.SQLITE_UPDATE:
                return sqlite3.SQLITE_OK if arg1 == "attempts" and arg2 == "count" and trigger is None else sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_ALTER_TABLE,
                          sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ATTACH,
                          sqlite3.SQLITE_DETACH):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorizer)
        if conn.execute("UPDATE attempts SET count=2 WHERE day=? AND count=1", (DAY,)).rowcount != 1:
            invalid()
        expected = {day: count for day, count in before["attempts"]}
        expected[DAY] = 2
        after = budget_rows(conn, account)
        if after != dict(attempts=[list(row) for row in sorted(expected.items())], blocks=before["blocks"]):
            invalid()
        current = tables(conn)
        unchanged = {name: value for name, value in current["tables"].items() if name != "attempts"}
        prior = {name: value for name, value in frozen["tables"].items() if name != "attempts"}
        if current["schema_sha256"] != frozen["schema_sha256"] or unchanged != prior:
            invalid()
        conn.execute("COMMIT")
        return dict(current, budget=after)
    finally:
        conn.close()


def authoritative_window(products, at):
    """Use the same MarketPhaseResolver as PortfolioMarket, without subscribing."""
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
    from app.market_data.operational_universe import load_operational_products
    if tuple(sorted(products)) != tuple(sorted(p.upper() for p in load_operational_products())):
        invalid()
    ends = []
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        resolver = MarketPhaseResolver(db)
        for product in products:
            phase = resolver.resolve(product.lower(), at)
            if phase.phase is MarketPhase.UNKNOWN:
                invalid()
            if phase.phase is MarketPhase.TRADING:
                if (phase.trading_day is None or phase.trading_day.strftime("%Y%m%d") != DAY
                        or phase.current_session is None):
                    invalid()
                ends.append(phase.current_session.end.astimezone(UTC))
    if not ends or min(ends) <= at:
        invalid()
    return min(ends)


class Guard:
    def __init__(self, settings, config, state, probe, switch_identity):
        self.settings, self.config, self.state, self.probe = settings, config, state, probe
        self.folder = settings.state_root / settings.account_id
        self.switch_identity = switch_identity
        self.switch_path = config.parent / "switch.lock"

    def control(self):
        value, unused = read_json(self.folder / "continuous.json")
        selected = {key: value.get(key) for key in ("schema", "run_id", "status", "trading_day",
                     "opening_enabled", "account_takeover_pending", "products")}
        if (selected["schema"] != "simnow_continuous_v2" or selected["run_id"] != RUN
                or selected["status"] != "RECOVERY_BLOCKED" or selected["trading_day"] != DAY
                or selected["opening_enabled"] is not False or selected["account_takeover_pending"] is not True):
            invalid()
        return selected

    def host(self):
        private(self.switch_path)
        info = self.switch_path.stat()
        if (info.st_dev, info.st_ino) != self.switch_identity:
            invalid()
        for path in (self.folder / "host.lock", Path.home() /
                     "Library/Application Support/GuiyiQuant/SimNowLocks" / (self.settings.account_id + ".lock")):
            held_by_original(path)
        return process_binding(self.settings, self.config)

    def snapshot(self, *, copies=None):
        config_raw, config = read_file(self.config)
        failure_raw, failure = read_file(self.folder / FAILURE_NAME)
        value = json.loads(failure_raw)
        if (failure["sha256"] != FAILURE_SHA or value.get("code") != BLOCK
                or value.get("diagnostic", {}).get("stage") != "ADAPTER_CONSTRUCTION"
                or value.get("diagnostic", {}).get("recovery_stage") != "ADAPTER_PREPARATION"):
            invalid()
        if copies is not None:
            new_file(copies / "config.before", config_raw)
            new_file(copies / "failure.before", failure_raw)
        dbs = {name: database(self.folder / name, self.settings.account_id, copies=copies) for name in DATABASES}
        return dict(config=config, failure=failure, databases=dbs, host=self.host(), control=self.control())

    def check(self, plan, *, after_budget=None, fresh=False):
        if code_binding() != plan["code"]:
            invalid()
        current = self.snapshot()
        expected = plan["before"]
        for key in ("config", "failure", "host", "control"):
            if current[key] != expected[key]:
                invalid()
        for name in DATABASES:
            actual, prior = current["databases"][name], expected["databases"][name]
            if name != "signals.sqlite" or after_budget is None:
                if actual != prior:
                    invalid()
            elif ({key: actual[key] for key in ("schema_sha256", "tables", "budget")} != after_budget
                  or any(actual["file"][key] != prior["file"][key] for key in ("device", "inode"))):
                invalid()
        at = now()
        if at >= datetime.fromisoformat(plan["operation_until"]):
            invalid()
        boundary = authoritative_window(current["control"]["products"], at)
        if boundary.isoformat() != plan["session_end"]:
            invalid()
        if fresh and probe_binding(self.probe, current["host"], at) != plan["probe"]:
            invalid()
        return current


def code_binding():
    sources = (Path(__file__), ROOT / "scripts/broker/simnow_native_gateway.py",
               ROOT / "scripts/broker/simnow_readonly.py", ROOT / "scripts/broker/simnow_controlled.py",
               ROOT / "packages/quant-core/guiyi_quant/simnow_execution/model.py")
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}


def make_plan(guard):
    private(guard.state.parent, directory=True)
    guard.state.mkdir(mode=0o700)
    private(guard.state, directory=True)
    before = guard.snapshot(copies=guard.state)
    budget = before["databases"]["signals.sqlite"]["budget"]
    if dict(budget["attempts"]).get(DAY) != 1 or dict(budget["blocks"]).get(DAY) != BLOCK:
        invalid()
    at = now()
    end = authoritative_window(before["control"]["products"], at)
    if end - at < timedelta(seconds=310):
        invalid()
    plan = dict(schema="simnow_session_diagnostic_v1", run=RUN, day=DAY, pid=PID,
                planned_at=at.isoformat(), expires_at=(at + timedelta(seconds=60)).isoformat(),
                operation_until=(at + timedelta(seconds=300)).isoformat(), session_end=end.isoformat(),
                state=str(guard.state), config=str(guard.config), before=before,
                probe=probe_binding(guard.probe, before["host"], at), code=code_binding())
    new_file(guard.state / "plan.private.json", encoded(plan))
    return plan


class ReadOnlyAPI:
    """Only the six inventory request methods exist on the gateway's facade."""
    __slots__ = ("_calls", "_counts", "_guard", "_lock")

    def __init__(self, api, guard):
        self._calls = {name: getattr(api, name) for name in METHODS}
        self._counts = {name: 0 for name in METHODS}
        self._guard, self._lock = guard, threading.RLock()

    def __getattr__(self, name):
        if name not in METHODS:
            invalid()
        def request(*args):
            with self._lock:
                if self._counts[name] >= METHODS[name]:
                    invalid()
                self._guard()
                self._counts[name] += 1
                return self._calls[name](*args)
        return request


def structural_fields(native, day, front):
    """Existing Session integer conditions only; no fabricated settlement source."""
    from guiyi_quant.simnow_execution.model import integer, FRONT
    fields, accepted = {}, True
    exact = type(native) is dict and set(native) == {"front_id", "session_id", "max_order_ref"}
    for name in ("front_id", "session_id", "max_order_ref"):
        value = native.get(name) if type(native) is dict else None
        fields[name] = dict(present=type(native) is dict and name in native, integer=type(value) is int,
                            positive=type(value) is int and value > 0,
                            nonnegative=type(value) is int and value >= 0,
                            signed_int32=type(value) is int and -(2 ** 31) <= value < 2 ** 31)
        try:
            integer(value, 0 if name == "max_order_ref" else 1)
        except ValueError:
            accepted = False
    valid_day = type(day) is str and re.fullmatch(r"\d{8}", day) is not None and day == DAY
    if valid_day:
        try:
            datetime.strptime(day, "%Y%m%d")
        except ValueError:
            valid_day = False
    passed = exact and accepted and valid_day and front == FRONT
    return dict(fields=fields, exact_fields=exact, trading_day_matches=bool(valid_day), front_matches=front == FRONT,
                session_integer_rules_passed=accepted and exact,
                structural_passed=passed, structural_error=None if passed else "LOGIN_FIELDS_STRUCTURAL_REJECTED",
                login_fields_structural_only=True, execution_permitted=False, ledger_reconciled=False)


@contextmanager
def silence_native():
    saved = os.dup(1), os.dup(2)
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            yield
    finally:
        for source, target in zip(saved, (1, 2)):
            os.dup2(source, target)
            os.close(source)


def load_gateway(settings):
    """Called only after the durable budget debit, while native output is muted."""
    from guiyi_quant.simnow_execution.credentials import CredentialStore
    spec = importlib.util.spec_from_file_location("diagnostic_controlled", ROOT / "scripts/broker/simnow_controlled.py")
    bounded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bounded)
    module = bounded.bootstrap(ROOT, settings.api_env)
    credentials = CredentialStore().load(settings.account_id)
    try:
        gateway = module.Gateway(credentials.user, credentials.password, initial_funds_timeout=45)
    finally:
        del credentials
    return gateway, module


def apply(guard):
    plan, plan_identity = read_json(guard.state / "plan.private.json")
    at = now()
    if (plan.get("schema") != "simnow_session_diagnostic_v1" or plan.get("run") != RUN
            or plan.get("day") != DAY or plan.get("pid") != PID or plan.get("state") != str(guard.state)
            or plan.get("config") != str(guard.config) or plan.get("code") != code_binding()
            or not datetime.fromisoformat(plan["planned_at"]) <= at < datetime.fromisoformat(plan["expires_at"])
            or (datetime.fromisoformat(plan["expires_at"]) - datetime.fromisoformat(plan["planned_at"])).total_seconds() != 60):
        invalid()
    # Claim first. Even failed revalidation cannot turn an apply into a retry.
    new_file(guard.state / "claim.private.json", encoded(dict(plan_sha256=plan_identity["sha256"], at=at.isoformat())))
    guard.check(plan, fresh=True)
    post = spend_budget(guard.folder / "signals.sqlite", guard.settings.account_id,
                        plan["before"]["databases"]["signals.sqlite"])
    new_file(guard.state / "budget.private.json", encoded(post))
    gate = lambda: guard.check(plan, after_budget=post)
    guard.check(plan, after_budget=post, fresh=True)
    gateway = raw_api = None
    snapshot = None
    completed = released = spi_detached = False
    classification = structural_fields(None, None, None)
    with silence_native(), tempfile.TemporaryDirectory(prefix="guiyi-session-diagnostic-") as flow:
        try:
            gateway, module = load_gateway(guard.settings)
            gate()
            raw_api = module.tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi(flow + "/")
            gateway.api = ReadOnlyAPI(raw_api, gate)
            raw_api.RegisterSpi(gateway)
            raw_api.RegisterFront(gateway.front)
            gate()
            raw_api.Init()
            if not gateway.login_done.wait(25) or gateway.failed or not gateway.native_session:
                invalid()
            if gateway.day != DAY:
                invalid()
            classification = structural_fields(gateway.native_session, gateway.day, gateway.front)
            snapshot = gateway.snapshot()
            from guiyi_quant.simnow_execution.inventory import read_snapshot
            inventory = read_snapshot(snapshot, now=now())
            if inventory.account_id != guard.settings.account_id or inventory.trading_day != DAY:
                invalid()
            gate()
            completed = True
        except Exception:
            completed = False
        finally:
            # The immutable diagnostic fact precedes native release, even on partial login/query failure.
            try:
                new_file(guard.state / "native-fact.private.json", encoded(dict(
                    schema="simnow_independent_session_diagnostic_v1", at=now().isoformat(),
                    plan_sha256=plan_identity["sha256"], old_run=RUN, old_failure_sha256=FAILURE_SHA,
                    old_session_reconstructed=False, snapshot=snapshot,
                    partial_snapshot=gateway.result if gateway is not None and snapshot is None else None,
                    native_session=gateway.native_session if gateway is not None else None,
                    classification=classification, readback_complete=completed)))
            finally:
                if gateway is not None:
                    gateway.user = gateway.password = ""
                if raw_api is not None:
                    try:
                        raw_api.RegisterSpi(None)
                        spi_detached = True
                    except Exception:
                        spi_detached = False
                    try:
                        raw_api.Release()
                        released = True
                    except Exception:
                        released = False
            if completed and spi_detached and released:
                gate()
                fact_identity = read_file(guard.state / "native-fact.private.json")[1]
                new_file(guard.state / "release.private.json", encoded(dict(
                    status="READ_ONLY_DIAGNOSTIC_COMPLETE", plan_sha256=plan_identity["sha256"],
                    fact_sha256=fact_identity["sha256"], at=now().isoformat(), native_released=True,
                    spi_detached=True, guard_after_release_passed=True)))
    if not completed or not spi_detached or not released:
        invalid()
    return classification


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    options = parser.parse_args(argv)
    try:
        # Private-settings imports can transitively initialize the application engine.
        # Enforce read-only connections before those imports, then re-exec if the
        # validated dependencies differ from the environment used by that engine.
        os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
        sys.path[:0] = [str(ROOT / "packages/quant-core"), str(ROOT / "services/quant-api")]
        from guiyi_quant.simnow_execution.settings import load_settings
        settings = load_settings(CONFIG)
        if (settings.schema != 2 or settings.mode != "trade" or not settings.enabled
                or not settings.account_takeover_pending or settings.project_root != ROOT / ".worktrees/release-v1.16.64"
                or Path(sys.executable).resolve() != settings.sdk_python.resolve()):
            invalid()
        from app.private_settings import private_dependency_settings
        environment, unused = private_dependency_settings(Path.home() / "Library/Application Support/GuiyiQuant/project.env")
        environment["PGOPTIONS"] = "-c default_transaction_read_only=on"
        changed = any(os.environ.get(key) != value for key, value in environment.items())
        os.environ.update(environment)
        if changed:
            os.execv(sys.executable, [sys.executable, "-I", str(Path(__file__).resolve()), options.action])
        from app.runtime_handover import deployment_lock
        with deployment_lock(), switch_lock(CONFIG.parent / "switch.lock") as identity:
            guard = Guard(settings, CONFIG, STATE, PROBE, identity)
            if options.action == "plan":
                make_plan(guard)
                result = dict(status="PLANNED_NO_BROKER_IO")
            else:
                result = apply(guard)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('{"status":"SESSION_DIAGNOSTIC_STOPPED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
