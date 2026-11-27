"""macOS stopped-world transition from legacy Market Redis to formal Tick Redis."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
import fcntl
from hashlib import sha256
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from time import monotonic, sleep

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.aggregation import expected_intraday_ends
from app.market_data.catalog import MarketCatalog
from app.market_data.market_archive import current_retained_receipt, reference_catalog_revision
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_foundation_scope import formal_tick_fingerprint, require_formal_tick_binding
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.observation_stream import ObservationStream
from app.market_data.operational_universe import load_operational_products
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import private_dependency_settings, read_only_dependency_environment
from app.reference_trading.recovery_campaign import digest
from app.runtime_cohort import continuous_services, market_source_recovery_direction, registry, require, validate
from app.runtime_cohort_errors import CohortError
from app.runtime_cohort_host import CohortHost
from app.runtime_deployment import owner_process_matches
from app.runtime_handover import _read, _write, deployment_lock, owner_lock_available, read_service_state
from app.runtime_identity import SUBING_PAPER_LABEL, command_result, read_command, read_launchd_service
from app.runtime_market_account_readback import tq_watermark
from app.runtime_market_macos import _TQ_LABEL, _paper, _private, _tq
from app.runtime_market_source_handover import (
    old_observation_snapshot,
    preserve_stopped_observations,
    read_staged_observations,
    redis_instance,
    stage_new_observations,
    verify_preserved_observations,
)
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS
from guiyi_quant.trading_universe import TRADING_PRODUCTS


_REDIS_SETTING = re.compile(rb"^\s*(?:export )?REDIS_URL=")
_TICK_MARKER = b"# guiyi-market-source: rqdata_tick"
_ACCOUNTS = {"tqkq": (_TQ_LABEL, "tqkq-simulation"), "subing": (SUBING_PAPER_LABEL, "subing-paper")}
_COMPONENT_TAG = "market-foundation/v0.1.0"


@contextmanager
def _redis(url):
    with Redis.from_url(url, socket_connect_timeout=3, socket_timeout=5,
                        retry=Retry(NoBackoff(), 0)) as client:
        yield client


def _private_configuration(path):
    content = _private(path)
    settings, identity = private_dependency_settings(path)
    require(sha256(content).hexdigest() == identity["config_sha256"], "MARKET_SOURCE_CONFIG_DRIFT")
    return content, read_only_dependency_environment(settings)


def _market_config_pair(old_path, target_path):
    old, old_settings = _private_configuration(old_path)
    target, target_settings = _private_configuration(target_path)
    def unchanged(raw):
        return [line for line in raw.splitlines() if not _REDIS_SETTING.match(line) and line != _TICK_MARKER]

    require(
        unchanged(old) == unchanged(target)
        and b"\r" not in target and b"\0" not in target and target.endswith(b"\n")
        and _TICK_MARKER not in old.splitlines()
        and target.splitlines().count(_TICK_MARKER) == 1
        and all(settings.get("REDIS_URL") for settings in (old_settings, target_settings))
        and old_settings["REDIS_URL"] != target_settings["REDIS_URL"],
        "MARKET_SOURCE_CONFIG_TRANSITION_INVALID",
    )
    return old, old_settings, target, target_settings


def _connects_to(client, pid):
    """Match the owner's OS socket to the verified local Redis endpoint."""
    entries = command_result(
        ["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:ESTABLISHED", "-Fn"],
        root=Path("/"),
    )
    if entries.returncode == 1 and not entries.stdout:
        return False
    require(entries.returncode == 0, "MARKET_SOURCE_TQ_SOCKET_UNPROVEN")
    settings = client.connection_pool.connection_kwargs
    host, port = settings.get("host"), settings.get("port")
    hosts = {"127.0.0.1", "::1"} if host == "localhost" else {host}
    require(hosts <= {"127.0.0.1", "::1"} and settings.get("db", 0) == 0,
            "MARKET_SOURCE_TQ_REDIS_ENDPOINT_UNPROVEN")
    connections = {tuple(map(_socket_address, line[1:].split("->", 1))) for line in entries.stdout.splitlines()
                   if line.startswith("n") and "->" in line}
    destinations = {(address, port) for address in hosts}
    connections = {pair for pair in connections if pair[1] in destinations}
    if not connections:
        return False
    clients = client.client_list()
    direct = [row for row in clients if _socket_address(row["laddr"]) in destinations]
    if direct:
        return any((_socket_address(row["addr"]), _socket_address(row["laddr"])) in connections
                   and int(row["db"]) == 0 and int(row["sub"]) == len(TRADING_PRODUCTS) for row in direct)
    # A local port forward rewrites the server-side TCP tuple. The helper's OS
    # endpoint still proves the connection to the independently verified server.
    subscriptions = client.pubsub_numsub(*(f"live:bar:{p}:60m" for p in TRADING_PRODUCTS))
    return len(subscriptions) == len(TRADING_PRODUCTS) and all(count > 0 for _, count in subscriptions)


def _socket_address(raw):
    host, sep, port = raw.rpartition(":")
    if not sep or not port.isdecimal():
        return None
    try:
        address = ip_address(host.strip("[]"))
    except ValueError:
        return None
    return (str(getattr(address, "ipv4_mapped", None) or address), int(port))


def _tq_market_pid(pid):
    result = command_result(["/usr/bin/pgrep", "-P", str(pid), "-f", "app.tq_simulation_market"], root=Path("/"))
    children = result.stdout.strip()
    if result.returncode == 1 and not children:
        raise CohortError("MARKET_SOURCE_TQ_HELPER_STARTING")
    require(result.returncode == 0, "MARKET_SOURCE_TQ_HELPER_UNPROVEN")
    require(re.fullmatch(r"[1-9][0-9]*", children), "MARKET_SOURCE_TQ_HELPER_UNPROVEN")
    command = read_command(["/bin/ps", "-p", children, "-o", "ppid=", "-o", "command="], root=Path("/"))
    parent, _, invocation = command.partition(" ")
    require(parent == str(pid) and invocation.endswith(" -m app.tq_simulation_market"),
            "MARKET_SOURCE_TQ_HELPER_UNPROVEN")
    return int(children)


def _pid_has_lock(pid, path):
    handles = command_result(["/usr/sbin/lsof", "-a", "-p", str(pid), "-Fn", str(path)], root=Path("/"))
    return handles.returncode == 0 and "n" + str(path) in handles.stdout.splitlines()


@contextmanager
def _account_lock(path, *, stopped):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, "MARKET_SOURCE_ACCOUNT_LOCK_INVALID")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            require(not stopped, "MARKET_SOURCE_ACCOUNT_STILL_OWNED")
        else:
            require(stopped, "MARKET_SOURCE_ACCOUNT_OWNER_UNPROVEN")
        yield
    finally:
        os.close(fd)


class MarketCohortHost(CohortHost):
    @property
    def project_config(self):
        return self.directory / "project.env"

    @property
    def target_config(self):
        return self.directory / "market-tick.env"

    def _configs(self):
        return _market_config_pair(self.project_config, self.target_config)

    @contextmanager
    def _catalog_session(self, settings):
        url = make_url(normalize_database_url(settings["DATABASE_URL"]))
        canonical = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
        require(url.get_backend_name() == "postgresql" and url.database == "guiyi_quant"
                and canonical.is_dir(), "MARKET_SOURCE_CATALOG_UNPROVEN")
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        try:
            with Session(engine) as session, readonly_transaction(session, timeout_seconds=20):
                yield session, canonical
        finally:
            engine.dispose()

    def _authority(self, settings, old_day):
        now = self.now()
        with self._catalog_session(settings) as (session, canonical):
            products = load_operational_products()
            require(len(products) == 60, "COHORT_SCOPE_INVALID")
            resolver = MarketPhaseResolver(session)
            market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
            phases, days, subscriptions, windows = {}, set(), {}, {}
            for product in products:
                phase = resolver.resolve(product, now)
                require(phase.phase is MarketPhase.CLOSED and phase.current_session is None
                        and phase.next_session_start is not None
                        and phase.next_session_start > now + timedelta(seconds=660),
                        "MARKET_SOURCE_FULL_CLOSE_REQUIRED")
                upcoming = resolver.resolve(product, phase.next_session_start)
                target_day = upcoming.trading_day
                require(upcoming.phase is MarketPhase.TRADING and target_day is not None
                        and target_day > old_day and upcoming.current_session is not None
                        and upcoming.current_session.start == phase.next_session_start
                        and resolver.completed_observation_trading_day(product, now) == old_day,
                        "MARKET_SOURCE_NEXT_DAY_UNPROVEN")
                last = market.session_windows(symbol=product, trading_day=old_day)
                future = market.session_windows(symbol=product, trading_day=target_day)
                require(last and future and max(w.end for w in last) + timedelta(minutes=2) <= now
                        and min(w.start for w in future) == phase.next_session_start,
                        "MARKET_SOURCE_SESSION_BOUNDARY_UNPROVEN")
                old_owner = market.dominant_segment_for_day(product, old_day)
                new_owner = market.dominant_segment_for_day(product, target_day)
                subscriptions[product] = new_owner.contract
                windows[product] = (old_owner.contract, last, new_owner.contract, future)
                days.add(target_day)
                phases[product] = {"phase": phase.phase.value,
                                   "trading_day": phase.trading_day.isoformat() if phase.trading_day else None,
                                   "next_session_start": phase.next_session_start.isoformat()}
            require(len(days) == 1, "MARKET_SOURCE_NEXT_DAY_UNPROVEN")
            day = days.pop()
            receipt = current_retained_receipt(self.directory / "market-foundation", now=now)
            if receipt is not None:
                require(receipt.trading_day <= old_day and set(receipt.revisions) == set(products)
                        and all(reference_catalog_revision(session, p, receipt.trading_day, archive_scope=True)
                                == receipt.revisions[p] for p in products),
                        "MARKET_SOURCE_REFERENCE_RECEIPT_UNQUALIFIED")
            catalog_sha = digest({
                "windows": {p: [before, [(w.start, w.end) for w in last],
                                after, [(w.start, w.end) for w in future]]
                            for p, (before, last, after, future) in windows.items()},
                "receipt": receipt.identity if receipt else None,
            })
        window = {"mode": "closed_idle", "registered_trading_day": old_day.isoformat(),
                  "products": len(products), "phases": phases}
        return window, day, subscriptions, windows, catalog_sha, receipt.identity if receipt else None

    def session_proof(self):
        # The controller still holds the old source connection while changing
        # project.env. All successor observations use explicit target clients.
        settings = getattr(self, "_old_settings", None)
        if settings is None:
            _, settings, _, _ = self._configs()
        with _redis(settings["REDIS_URL"]) as old:
            old_day = ObservationStream(old, kind="source").registered_day("live")
        require(isinstance(old_day, date), "MARKET_SOURCE_CUTOFF_UNPROVEN")
        return self._authority(settings, old_day)[0]

    @staticmethod
    def _terminals(windows, products, frequency):
        return {p: (windows[p][0], expected_intraday_ends(windows[p][1], frequency)[-1])
                for p in products}

    def _account_frontiers(self, old, old_url, day, windows):
        accounts = {}
        with ExitStack() as locks:
            for name, (_, folder) in _ACCOUNTS.items():
                locks.enter_context(_account_lock(self.directory / folder / "owner.lock", stopped=False))
            accounts["subing"] = _paper(
                self.home, self.directory, self._terminals(windows, EXPANDED_PORTFOLIO_PRODUCTS, "1m"),
                day, old_url, [redis_instance(old), ObservationStream(old, kind="completed").tail(day)],
            )
            accounts["tqkq"] = _tq(self.home, self.directory,
                                    self._terminals(windows, TRADING_PRODUCTS, "60m"), self.now())
        require(all(row.get("status") == "verified" for row in accounts.values()),
                "MARKET_SOURCE_ACCOUNT_WATERMARK_UNPROVEN")
        require(all(_pid_has_lock(row["pid"], self.directory / _ACCOUNTS[name][1] / "owner.lock")
                    for name, row in accounts.items()), "MARKET_SOURCE_ACCOUNT_LOCK_OWNER_UNPROVEN")
        tq = accounts["tqkq"]
        tq["helper_pid"] = _tq_market_pid(tq["pid"])
        require(_connects_to(old, tq["helper_pid"]),
                "MARKET_SOURCE_TQ_OLD_REDIS_UNPROVEN")
        # Freshness is verified by the readers on every sample. A moving broker
        # validity timestamp is not part of the account's frozen watermark.
        stable = {
            "tqkq": ("pid", "helper_pid", "plist_sha256", "config_sha256", "control_sha256",
                     "mode", "root", "commit", "tag", "watermarks"),
            "subing": ("pid", "plist_sha256", "root", "disk_commit", "run_id", "sequence",
                       "tail_hash", "watermarks", "registration_sha256", "database_sha256"),
        }
        return {name: {key: row[key] for key in stable[name]} for name, row in accounts.items()}

    def freeze_market_source_handover(self, old_registry, new_registry, window):
        from app.db.session import engine
        from app.market_data.composition import canonical_root
        from app.redis_connections import get_redis_connection

        old_config, old_settings, target_config, target_settings = self._configs()
        require(engine.url == make_url(normalize_database_url(old_settings["DATABASE_URL"]))
                and canonical_root() == Path(old_settings["GUIYI_CANONICAL_DATA_ROOT"]),
                "MARKET_SOURCE_CONTROLLER_CATALOG_UNPROVEN")
        candidate = Path(new_registry.services["api"].root)
        git = ["/usr/bin/git", "-c", "core.fsmonitor=false"]
        require(read_command([*git, "cat-file", "-t", "refs/tags/" + _COMPONENT_TAG], root=candidate) == "tag",
                "MARKET_SOURCE_COMPONENT_TAG_UNPROVEN")
        read_command([*git, "merge-base", "--is-ancestor", _COMPONENT_TAG + "^{commit}", "HEAD"],
                     root=candidate)
        with (_redis(old_settings["REDIS_URL"]) as old, _redis(target_settings["REDIS_URL"]) as target,
              get_redis_connection() as controller):
            old_id, target_id = redis_instance(old), redis_instance(target)
            require(redis_instance(controller) == old_id and old_id != target_id,
                    "MARKET_SOURCE_CONTROLLER_REDIS_UNPROVEN")
            canonical = Path(target_settings["GUIYI_CANONICAL_DATA_ROOT"])
            database = make_url(normalize_database_url(target_settings["DATABASE_URL"]))
            formal_tick_fingerprint(target, database, canonical)
            require(not target.info("keyspace") and len(target.client_list()) == 1,
                    "MARKET_SOURCE_TARGET_NOT_EMPTY")
            old_day = date.fromisoformat(window["registered_trading_day"])
            current, target_day, _, windows, catalog_sha, _receipt = self._authority(old_settings, old_day)
            require(current == window, "COHORT_SESSION_CHANGED")
            until = monotonic() + 60

            def budget():
                require(monotonic() < until, "MARKET_SOURCE_OLD_SNAPSHOT_TIMEOUT")

            old_journal = old_observation_snapshot(
                old, old_day, alert_enabled=old_registry.services["alert"].enabled, check_budget=budget,
                terminals=self._terminals(windows, load_operational_products(), "1m"),
            )
            accounts = self._account_frontiers(old, old_settings["REDIS_URL"], old_day, windows)
        self._old_settings, self._accounts, self._old_journal = old_settings, accounts, old_journal
        self._old_windows = windows
        self._old_terminals = self._terminals(windows, load_operational_products(), "1m")
        self._target_config_sha = sha256(target_config).hexdigest()
        return {
            "old_instance": old_id, "target_instance": target_id,
            "old_day": old_day.isoformat(), "target_day": target_day.isoformat(), "catalog_sha256": catalog_sha,
            "tqkq_sha256": digest(accounts["tqkq"]), "subing_sha256": digest(accounts["subing"]),
            "host_sha256": digest({
                "old_config": sha256(old_config).hexdigest(), "target_config": self._target_config_sha,
                "journals": old_journal,
            }),
        }

    def check_market_source_plan(self, plan):
        require(
            self.freeze_market_source_handover(registry(plan["old"]), registry(plan["new"]), plan["window"])
            == plan["market_source_handover"],
            "MARKET_SOURCE_PLAN_DRIFT",
        )

    def prewarm(self, plan):
        result = super().prewarm(plan)
        self.check_market_source_plan(plan)
        return result

    @contextmanager
    def guards(self, plan):
        with super().guards(plan), ExitStack() as account_guards:
            self._account_guards = account_guards
            yield

    def _account_root(self, name):
        return Path(self._accounts[name]["root"])

    def _account_absent(self, name):
        return read_launchd_service(_ACCOUNTS[name][0], root=self._account_root(name)) is None

    @staticmethod
    def _pid_absent(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False

    def stop_old(self, plan, proof):
        stopped = super().stop_old(plan, proof)
        old_day = date.fromisoformat(plan["market_source_handover"]["old_day"])
        _, _, _, windows, _, _ = self._authority(self._old_settings, old_day)
        with _redis(self._old_settings["REDIS_URL"]) as old:
            accounts = self._account_frontiers(old, self._old_settings["REDIS_URL"], old_day, windows)
        require(accounts == self._accounts, "MARKET_SOURCE_STOP_ACCOUNT_DRIFT")
        self._stopped_accounts = []
        requests = {}
        for name, (label, folder) in _ACCOUNTS.items():
            target = f"gui/{os.getuid()}/{label}"
            row = accounts[name]
            requests[name] = {"label": label, "pid": row["pid"], "helper_pid": row.get("helper_pid")}
            _write(self._attempt(plan) / "market-account-stop.json", {
                "plan_sha256": plan["plan_sha256"], "requests": requests,
            })
            self._pending_account_stop = name
            self.launch("disable", target)
            self.launch("bootout", target)
            pids = [row["pid"], *([row["helper_pid"]] if name == "tqkq" else [])]
            deadline = min(self.deadline, monotonic() + 30)
            while monotonic() < deadline:
                if self._account_absent(name) and all(self._pid_absent(pid) for pid in pids):
                    break
                sleep(0.1)
            else:
                require(False, "MARKET_SOURCE_ACCOUNT_STOP_UNPROVEN")
            self._account_guards.enter_context(_account_lock(self.directory / folder / "owner.lock", stopped=True))
            self._stopped_accounts.append(name)
            self._pending_account_stop = None
        self._verify_stopped_accounts(plan, windows)
        return {**stopped, "accounts": accounts}

    def _verify_stopped_accounts(self, plan, windows):
        intent = plan["market_source_handover"]
        old_day = date.fromisoformat(intent["old_day"])
        old_url = self._old_settings["REDIS_URL"]
        with _redis(old_url) as old:
            paper = _paper(self.home, self.directory, self._terminals(windows, EXPANDED_PORTFOLIO_PRODUCTS, "1m"),
                           old_day, old_url, [intent["old_instance"], ObservationStream(old, kind="completed").tail(old_day)],
                           stopped=True)
        previous = self._accounts["subing"]
        require(paper["status"] == "verified" and all(paper[k] == v for k, v in previous.items() if k != "pid"),
                "MARKET_SOURCE_STOPPED_SUBING_DRIFT")
        base = self.directory / _ACCOUNTS["tqkq"][1]
        raw = _private(base / "config.json")
        previous = self._accounts["tqkq"]
        require(sha256(raw).hexdigest() == previous["config_sha256"]
                and sha256(_private(base / "control.json")).hexdigest() == previous["control_sha256"]
                and not os.path.lexists(base / "hold.json"), "MARKET_SOURCE_STOPPED_TQ_CONFIG_DRIFT")
        account = json.loads(raw)["account_id"]
        tq = tq_watermark(base / "accounts" / account / "account.sqlite", account,
                          self._terminals(windows, TRADING_PRODUCTS, "60m"), self.now())
        require(tq["status"] == "verified" and tq["watermarks"] == previous["watermarks"],
                "MARKET_SOURCE_STOPPED_TQ_WATERMARK_DRIFT")

    def _before_deadline(self):
        require(monotonic() < self.deadline, "COHORT_DOWNTIME_EXCEEDED")

    def _assert_stopped(self, plan):
        require(all(self.definition_absent(b) for b in registry(plan["old"]).services.values())
                and all(self._account_absent(name) for name in _ACCOUNTS),
                "MARKET_SOURCE_STOP_UNPROVEN")
        self._before_deadline()

    def preserve_market_source(self, plan, proof, attempt):
        self._assert_stopped(plan)
        intent = plan["market_source_handover"]
        with _redis(self._old_settings["REDIS_URL"]) as old:
            retained = preserve_stopped_observations(
                old, date.fromisoformat(intent["old_day"]), alert_enabled=registry(plan["old"]).services["alert"].enabled,
                attempt=attempt, check_budget=self._before_deadline, terminals=self._old_terminals,
            )
        require({k: v for k, v in retained.items() if k != "archive_sha256"} == self._old_journal,
                "MARKET_SOURCE_STOPPED_FRONTIER_DRIFT")
        return retained

    def _target_arguments(self, plan, settings):
        intent = plan["market_source_handover"]
        window, day, subscriptions, _, catalog_sha, _ = self._authority(settings, date.fromisoformat(intent["old_day"]))
        require(window == plan["window"] and catalog_sha == intent["catalog_sha256"]
                and day.isoformat() == intent["target_day"], "MARKET_SOURCE_CATALOG_DRIFT")
        return {
            "database": make_url(normalize_database_url(settings["DATABASE_URL"])),
            "canonical": Path(settings["GUIYI_CANONICAL_DATA_ROOT"]), "day": day,
            "subscriptions": subscriptions, "expected_instance": intent["target_instance"],
            "alert_enabled": registry(plan["old"]).services["alert"].enabled,
        }

    def stage_market_source(self, plan, proof, retained):
        self._assert_stopped(plan)
        original, _, target_config, target = self._configs()
        require(sha256(original).hexdigest() == plan["protected"]["files"][str(self.project_config)]
                and sha256(target_config).hexdigest() == self._target_config_sha,
                "MARKET_SOURCE_CONFIG_DRIFT")
        args = self._target_arguments(plan, target)
        with _redis(target["REDIS_URL"]) as redis:
            require(len(redis.client_list()) == 1, "MARKET_SOURCE_TARGET_HAS_CLIENTS")
            binding = stage_new_observations(redis, old_instance=retained["instance"], **args)
        self._staged_arguments = args
        return {"binding": binding, "config_sha256": self._target_config_sha}

    def install(self, plan, attempt):
        self._assert_stopped(plan)
        before, _, target, settings = self._configs()
        require(sha256(before).hexdigest() == plan["protected"]["files"][str(self.project_config)]
                and sha256(target).hexdigest() == self._target_config_sha,
                "MARKET_SOURCE_CONFIG_DRIFT")
        warmup = self._prewarm_staged(plan, settings)
        result = super().install(plan, attempt)
        self._assert_stopped(plan)
        require(_private(self.project_config) == before and _private(self.target_config) == target,
                "MARKET_SOURCE_CONFIG_DRIFT")
        self._replace_plist(self.project_config, target)
        require(_private(self.project_config) == target, "MARKET_SOURCE_CONFIG_ACTIVATION_UNKNOWN")
        return {**result, "market_config_sha256": self._target_config_sha, "market_warmup": warmup}

    def _prewarm_staged(self, plan, settings):
        candidate = registry(plan["new"]).services["market-feed"]
        root = Path(candidate.root)
        env = {**os.environ, **settings, "GUIYI_MARKET_SOURCE": "rqdata_tick",
               "GUIYI_PROJECT_ROOT": candidate.root, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [str(root / "services/quant-api/.venv/bin/python"), "-m", "app.runtime_cohort", "warmup", "market-source-staged"],
            cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False, timeout=min(60, max(1, self.deadline - monotonic())),
        )
        proof = json.loads(result.stdout.strip().splitlines()[-1])
        staged = _read(self._attempt(plan) / "state.json")["effects"]["market_source_stage"]
        require(result.returncode == 0 and proof.get("status") == "ready"
                and proof.get("service") == "market-source-staged" and self._candidate_sources(proof, root, candidate.tag)
                and proof.get("proof", {}).get("receipt_only") is True
                and proof["proof"].get("binding") == staged["binding"], "MARKET_SOURCE_STAGED_WARMUP_UNPROVEN")
        return proof["proof"]

    def check_staged_market_source(self, plan, proof, retained, staged):
        self.check_commit(plan)
        self._assert_stopped(plan)
        active, target = _private_configuration(self.project_config)
        require(sha256(active).hexdigest() == staged["config_sha256"] and active == _private(self.target_config),
                "MARKET_SOURCE_CONFIG_DRIFT")
        self._verify_stopped_namespaces(plan, retained, staged, target)

    def commit(self, plan):
        from app.runtime_bindings import write_bindings

        self._assert_stopped(plan)
        self._active_target(plan)
        return write_bindings(registry(plan["new"]), expected_sha256=plan["registry_sha256"])

    def _verify_stopped_namespaces(self, plan, retained, staged, target, *, restore_budget=None):
        if restore_budget is None:
            args = self._target_arguments(plan, target)
            check_budget = self._before_deadline
        else:
            args = self._staged_arguments
            def check_budget():
                require(monotonic() < restore_budget, "MARKET_SOURCE_RESTORE_BUDGET_EXCEEDED")
        intent = plan["market_source_handover"]
        verify_preserved_observations(self._attempt(plan), retained["archive_sha256"],
                                      check_budget=check_budget)
        with (_redis(self._old_settings["REDIS_URL"]) as old, _redis(target["REDIS_URL"]) as redis):
            legacy = old_observation_snapshot(
                old, date.fromisoformat(intent["old_day"]), alert_enabled=args["alert_enabled"],
                check_budget=check_budget, terminals=self._old_terminals,
            )
            require(legacy == {k: v for k, v in retained.items() if k != "archive_sha256"},
                    "MARKET_SOURCE_STOPPED_FRONTIER_DRIFT")
            require(read_staged_observations(redis, **args) == staged["binding"],
                    "MARKET_SOURCE_STAGED_BASELINE_UNPROVEN")

    def verify_market_source_restore(self, plan, effects):
        require(getattr(self, "_pending_account_stop", None) is None, "MARKET_SOURCE_ACCOUNT_STOP_UNKNOWN")
        for name in getattr(self, "_stopped_accounts", ()):
            require(self._account_absent(name), "MARKET_SOURCE_ACCOUNT_STOP_UNKNOWN")
            _, folder = _ACCOUNTS[name]
            with _account_lock(self.directory / folder / "owner.lock", stopped=True):
                pass
        staged = effects.get("market_source_stage")
        active = _private(self.project_config)
        old_sha = plan["protected"]["files"][str(self.project_config)]
        if staged is not None:
            _, target = _private_configuration(self.target_config)
            require(sha256(_private(self.target_config)).hexdigest() == staged["config_sha256"],
                    "MARKET_SOURCE_CONFIG_DRIFT")
            self._verify_stopped_namespaces(plan, effects["market_source_preserve"], staged, target,
                                            restore_budget=monotonic() + 60)
        if sha256(active).hexdigest() != old_sha:
            require(staged is not None and sha256(active).hexdigest() == staged["config_sha256"],
                    "MARKET_SOURCE_CONFIG_RESTORE_UNPROVEN")
            originals = self._attempt(plan) / "originals"
            index = json.loads(_private(originals / "index.json"))
            rows = [row for row in index["files"] if row["source"] == str(self.project_config)]
            require(len(rows) == 1 and re.fullmatch(r"[0-9]{3}\.bin", rows[0]["file"]),
                    "MARKET_SOURCE_CONFIG_RESTORE_UNPROVEN")
            previous = _private(originals / rows[0]["file"])
            require(sha256(previous).hexdigest() == old_sha, "MARKET_SOURCE_CONFIG_RESTORE_UNPROVEN")
            self._replace_plist(self.project_config, previous)
            require(_private(self.project_config) == previous, "MARKET_SOURCE_CONFIG_RESTORE_UNKNOWN")

    def _start_accounts(self, names, *, track_successor=False):
        if track_successor:
            self._successor_start_requests = []
        for name in names:
            label, _ = _ACCOUNTS[name]
            require(self._account_absent(name), "MARKET_SOURCE_ACCOUNT_ALREADY_LOADED")
            path = self.home / "Library/LaunchAgents" / (label + ".plist")
            require(sha256(self.bytes(path)).hexdigest() == self._accounts[name]["plist_sha256"],
                    "MARKET_SOURCE_ACCOUNT_PLIST_DRIFT")
            if track_successor:
                self._successor_start_requests.append(name)
            self.launch("enable", f"gui/{os.getuid()}/{label}")
            self.launch("bootstrap", f"gui/{os.getuid()}", str(path))

    def restore_old(self, plan):
        super().restore_old(plan)
        stopped = getattr(self, "_stopped_accounts", ())
        self._start_accounts(stopped)
        if stopped:
            deadline = monotonic() + 60
            day = date.fromisoformat(plan["market_source_handover"]["old_day"])
            old_url = self._old_settings["REDIS_URL"]
            while monotonic() < deadline:
                try:
                    with _redis(old_url) as old:
                        restored = self._account_frontiers(old, old_url, day, self._old_windows)
                except CohortError as exc:
                    if not _account_starting(exc):
                        raise
                else:
                    require(all(restored[name] == before or name in stopped and all(
                        restored[name][key] == value for key, value in before.items() if key not in {"pid", "helper_pid"}
                    ) for name, before in self._accounts.items()), "MARKET_SOURCE_OLD_ACCOUNT_RESTORE_DRIFT")
                    return
                sleep(0.5)
            require(False, "MARKET_SOURCE_OLD_ACCOUNT_RESTORE_UNPROVEN")

    def assert_protected(self, plan):
        require(_TICK_MARKER in _private(self.project_config).splitlines(), "MARKET_SOURCE_CONFIG_DRIFT")
        current = self.protected(registry(plan["old"]))
        observed = current["files"].pop(str(self.project_config))
        expected = dict(plan["protected"]["files"])
        expected.pop(str(self.project_config))
        require(observed == self._target_config_sha and current["files"] == expected
                and current["db_scope_policy_identity_sha256"] == plan["protected"]["db_scope_policy_identity_sha256"],
                "COHORT_PROTECTED_FACT_DRIFT")

    def _attempt(self, plan):
        return self.directory / "cohort-attempts" / plan["plan_sha256"]

    def _active_target(self, plan):
        raw, settings = _private_configuration(self.project_config)
        require(sha256(raw).hexdigest() == self._target_config_sha
                and _TICK_MARKER in raw.splitlines(), "MARKET_SOURCE_CONFIG_DRIFT")
        return settings

    def _ready_on_target(self, plan, settings, args, *, feed):
        new = registry(plan["new"])
        intent = plan["market_source_handover"]
        with _redis(settings["REDIS_URL"]) as target:
            require(redis_instance(target) == intent["target_instance"], "MARKET_SOURCE_INSTANCE_DRIFT")
            require_formal_tick_binding(target, args["database"], args["canonical"])
            source = ObservationStream(target, kind="source")
            completed = ObservationStream(target, kind="completed")
            day = args["day"]
            require(source.registered_day("live") == day and source.cursor("live", day) == source.tail(day) == "0-0"
                    and completed.tail(day) == "0-0", "MARKET_SOURCE_CLOSED_BASELINE_DRIFT")
            if args["alert_enabled"]:
                require(completed.registered_day("alert") == day and completed.cursor("alert", day) == "0-0",
                        "MARKET_SOURCE_ALERT_CURSOR_DRIFT")
            modes = {}
            for name in continuous_services(new):
                if name == "market-feed" and not feed:
                    continue
                binding = new.services[name]
                if not binding.enabled:
                    continue
                state = read_service_state(name)
                if not (
                    state and state.get("phase") == "active" and state.get("ready") is True
                    and state.get("generation") == binding.generation
                    and owner_process_matches(state, binding)
                    and not owner_lock_available(name, runtime_dir=self.directory)
                    and 0 <= (self.now() - datetime.fromisoformat(state["at"])).total_seconds() <= 30
                ):
                    return None
                if name == "market-feed" and not self._feed_closed_healthy(binding, state, plan["window"], redis=target):
                    return None
                if name in {"live", "alert"}:
                    pulse = json.loads(target.get(f"{name}:heartbeat") or b"{}")
                    if not (pulse.get("available") is True and pulse.get("runtime_commit") == binding.commit
                            and pulse.get("runtime_generation") == binding.generation
                            and 0 <= (self.now() - datetime.fromisoformat(pulse["generated_at"])).total_seconds() <= 30):
                        return None
                    if name == "alert":
                        journal = pulse.get("observation_journal")
                        if not isinstance(journal, dict) or any(journal.get(key) != value for key, value in {
                            "trading_day": str(day), "cursor": "0-0", "tail": "0-0",
                        }.items()):
                            return None
                mode = "closed_idle" if name == "market-feed" else "active"
                if name == "reference-worker":
                    mode = state.get("proof", {}).get("reference_receipts")
                    if mode not in {"waiting_archive", "current"}:
                        return None
                modes[name] = mode
            return modes

    def _await_target(self, plan, *, feed, seconds):
        deadline = min(self.deadline, monotonic() + seconds)
        settings = self._active_target(plan)
        args = self._target_arguments(plan, settings)
        while monotonic() < deadline:
            modes = self._ready_on_target(plan, settings, args, feed=feed)
            if modes is not None:
                return modes
            sleep(0.2)
        require(False, "MARKET_SOURCE_TARGET_OWNERS_NOT_READY")

    def _resumed_accounts(self, plan):
        intent = plan["market_source_handover"]
        old_day = date.fromisoformat(intent["old_day"])
        _, _, _, windows, _, _ = self._authority(self._old_settings, old_day)
        settings = self._active_target(plan)
        old_url = self._old_settings["REDIS_URL"]

        tq = _tq(self.home, self.directory, self._terminals(windows, TRADING_PRODUCTS, "60m"), self.now())
        if tq["status"] != "verified":
            return None
        helper = _tq_market_pid(tq["pid"])
        with _redis(settings["REDIS_URL"]) as target, _redis(old_url) as old:
            require(redis_instance(target) == intent["target_instance"] and redis_instance(old) == intent["old_instance"],
                    "MARKET_SOURCE_INSTANCE_DRIFT")
            if not _connects_to(target, helper):
                return None
            paper = _paper(
                self.home, self.directory, self._terminals(windows, EXPANDED_PORTFOLIO_PRODUCTS, "1m"),
                old_day, old_url, [intent["old_instance"], ObservationStream(old, kind="completed").tail(old_day)],
                active_instance=intent["target_instance"],
            )
        if paper["status"] != "verified" or paper["heartbeat_status"] != "SESSION_CLOSED":
            return None
        for name, row in {"tqkq": tq, "subing": paper}.items():
            path = self.directory / _ACCOUNTS[name][1] / "owner.lock"
            if not _pid_has_lock(row["pid"], path):
                return None
            with _account_lock(path, stopped=False):
                pass
            previous = self._accounts[name]
            require(row["pid"] != previous["pid"]
                    and all(row[key] == value for key, value in previous.items() if key not in {"pid", "helper_pid"}),
                    "MARKET_SOURCE_ACCOUNT_RESUME_IDENTITY_DRIFT")
        return {
            "tqkq": {"pid": tq["pid"], "helper_pid": helper, "target_instance": intent["target_instance"],
                     "native_watermarks": tq["watermarks"]},
            "subing": {"pid": paper["pid"], "run_id": paper["run_id"],
                       "prefix_sequence": paper["sequence"], "prefix_tail_hash": paper["tail_hash"],
                       "target_ledger_acceptance": "pending_natural_minutes"},
        }

    def market_source_consumers_ready(self, plan, proof):
        modes = self._await_target(plan, feed=False, seconds=240)
        self._start_accounts(_ACCOUNTS, track_successor=True)
        deadline = min(self.deadline, monotonic() + 120)
        while monotonic() < deadline:
            try:
                accounts = self._resumed_accounts(plan)
            except CohortError as exc:
                if not _account_starting(exc):
                    raise
                accounts = None  # A new owner may still be publishing its first sample.
            if accounts is not None:
                return {"continuous_modes": modes, "accounts": accounts}
            sleep(0.5)
        require(False, "MARKET_SOURCE_TARGET_ACCOUNTS_NOT_READY")

    def verify_market_source(self, plan, proof):
        modes = self._await_target(plan, feed=True, seconds=120)
        self.verify_continuous_identity(plan)
        accounts = self._resumed_accounts(plan)
        require(accounts is not None, "MARKET_SOURCE_TARGET_ACCOUNTS_NOT_READY")
        return {"continuous_modes": modes, "continuous_identity": "matched", "accounts": accounts,
                "natural_acceptance": "pending"}

    def halt_unknown(self, plan):
        if self.bindings() != registry(plan["new"]):
            return
        try:
            super().halt_unknown(plan)
        finally:
            for name in getattr(self, "_successor_start_requests", ()):
                label = _ACCOUNTS[name][0]
                target = f"gui/{os.getuid()}/{label}"
                self.launch("disable", target)
                if not self._account_absent(name):
                    self.launch("bootout", target)

    def _evidence(self, supplied):
        from app.runtime_cohort import _resolution_source

        _, plan = _resolution_source(supplied)
        sha = plan.get("plan_sha256")
        require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha),
                "COHORT_MARKET_SOURCE_PLAN_INVALID")
        validate(plan, datetime.fromisoformat(plan["created_at"]), allow_market_source=True)
        attempt = self._attempt(plan)
        require(_resolution_source(attempt / "plan.json")[1] == plan,
                "MARKET_SOURCE_PLAN_ORIGINAL_DRIFT")
        state = _read(attempt / "state.json")
        require(state is not None and state.get("plan_sha256") == sha, "MARKET_SOURCE_STATE_UNPROVEN")
        return plan, state

    def read_market_source_recovery(self, supplied):
        with deployment_lock(runtime_dir=self.directory):
            plan, state = self._evidence(supplied)
            pointer = _read(self.directory / "cohort-release.json")
            require(pointer is not None and pointer.get("plan_sha256") == plan["plan_sha256"],
                    "MARKET_SOURCE_STATE_DRIFT")
            bindings = self.bindings()
            direction = market_source_recovery_direction(plan, state, bindings)
            raw, settings = _private_configuration(self.project_config)
            active = sha256(raw).hexdigest()
            staged = state["effects"].get("market_source_stage")
            old, new = registry(plan["old"]), registry(plan["new"])
            binding_side = "target" if bindings == new else "legacy" if bindings == old else "unproven"
            if binding_side == "legacy" and self.binding_hash() != plan["registry_sha256"]:
                binding_side, direction = "unproven", "binding_readback_required"
            name = "unproven"
            if active == plan["protected"]["files"][str(self.project_config)]:
                name = "legacy"
            elif staged is not None and active == staged["config_sha256"]:
                try:
                    with _redis(settings["REDIS_URL"]) as redis:
                        url = make_url(normalize_database_url(settings["DATABASE_URL"]))
                        if (redis_instance(redis) == plan["market_source_handover"]["target_instance"]
                                and require_formal_tick_binding(redis, url, Path(settings["GUIYI_CANONICAL_DATA_ROOT"]))
                                == staged["binding"]):
                            name = "target"
                except (ValueError, CohortError, RedisError):
                    pass  # Redis availability cannot change the independently observed CAS side.
            require(self.bindings() == bindings and _private(self.project_config) == raw, "COHORT_BINDING_DRIFT")
            return {"status": "readback", "direction": direction, "active_configuration": name,
                    "registry": binding_side, "private_phase": state["phase"], "pointer_phase": pointer.get("phase"),
                    "plan_sha256": plan["plan_sha256"]}

    def read_market_source_accounts(self, supplied):
        plan, state = self._evidence(supplied)
        new = registry(plan["new"])
        require(state["phase"] == "switched" and self.bindings() == new,
                "MARKET_SOURCE_ACCOUNT_ACCEPTANCE_NOT_RECORDED")
        intent = plan["market_source_handover"]
        old = state["effects"]["old_exited"]["accounts"]["subing"]
        old_tq = state["effects"]["old_exited"]["accounts"]["tqkq"]
        day = date.fromisoformat(intent["target_day"])
        staged = state["effects"]["market_source_stage"]
        self._target_config_sha = staged["config_sha256"]
        settings = self._active_target(plan)
        with self._catalog_session(settings) as (session, canonical):
            market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
            def expected(products, frequency):
                result = {}
                for product in products:
                    end = expected_intraday_ends(market.session_windows(symbol=product, trading_day=day), frequency)[-1]
                    require(end <= self.now(), "MARKET_SOURCE_NEW_DAY_NOT_COMPLETE")
                    result[product] = (market.dominant_segment_for_day(product, day).contract, end)
                return result
            with _redis(settings["REDIS_URL"]) as redis:
                require(redis_instance(redis) == intent["target_instance"], "MARKET_SOURCE_INSTANCE_DRIFT")
                require(require_formal_tick_binding(redis, session.get_bind().url, canonical) == staged["binding"],
                        "MARKET_SOURCE_FORMAL_BINDING_DRIFT")
                frontier = [intent["target_instance"], ObservationStream(redis, kind="completed").tail(day)]
                result = _paper(
                    self.home, self.directory, expected(EXPANDED_PORTFOLIO_PRODUCTS, "1m"), day, settings["REDIS_URL"], frontier,
                    generation_prefix="rqdata-tick:", prefix=[old["sequence"], old["tail_hash"]],
                    active_instance=intent["target_instance"],
                )
                tq = _tq(self.home, self.directory, expected(TRADING_PRODUCTS, "60m"), self.now())
                require(tq["status"] == "verified" and _connects_to(redis, _tq_market_pid(tq["pid"]))
                        and all(tq[key] == old_tq[key] for key in ("root", "commit", "config_sha256", "control_sha256")),
                        "MARKET_SOURCE_TQ_TAKEOVER_UNPROVEN")
        require(result["status"] == "verified" and self.bindings() == new
                and all(result[key] == old[key] for key in ("root", "disk_commit", "run_id",
                        "registration_sha256", "database_sha256")),
                "MARKET_SOURCE_SUBING_TAKEOVER_UNPROVEN")
        require(self._active_target(plan) == settings, "MARKET_SOURCE_CONFIG_DRIFT")
        return {"status": "target_ledger_verified", "subing": result, "tqkq": tq, "trading_day": day.isoformat()}


def _account_starting(error):
    return str(error) in {"MARKET_HANDOFF_ACCOUNT_NOT_LOADED", "MARKET_HANDOFF_ACCOUNT_STARTING",
                          "MARKET_HANDOFF_TQ_MONITOR_IDENTITY_CHANGED", "MARKET_SOURCE_ACCOUNT_WATERMARK_UNPROVEN",
                          "MARKET_SOURCE_TQ_HELPER_STARTING", "MARKET_SOURCE_ACCOUNT_OWNER_UNPROVEN"}
