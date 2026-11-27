"""Read the independent macOS account owners before changing Market sources."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.aggregation import expected_intraday_ends
from app.market_data.catalog import MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_foundation_scope import require_bar_writer_namespace
from app.market_data.observation_stream import ObservationStream
from app.private_settings import (
    load_private_readonly_settings,
    read_only_dependency_environment,
)
from app.runtime_bindings import read_bindings
from app.runtime_cohort_errors import CohortError
from app.runtime_identity import (
    SUBING_PAPER_LABEL,
    file_snapshot,
    launchd_arguments,
    launchd_environments,
    read_command,
    read_launchd_service,
)
from app import runtime_market_account_readback
from app.runtime_market_account_readback import tq_watermark
from app.runtime_market_source_handover import redis_instance
from guiyi_quant.trading_universe import TRADING_PRODUCTS
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS


_TQ_LABEL = "com.guiyi.quant-tqkq-simulation"


def _private(path):
    return file_snapshot(path, private=True)[0]


def _job(home, label, args, root, *, tq=False):
    path = home / "Library/LaunchAgents" / f"{label}.plist"
    raw, _ = file_snapshot(path)
    installed = plistlib.loads(raw)
    if (
        installed.get("Label") != label or tuple(installed["ProgramArguments"]) != args
        or installed.get("Program", "/bin/bash") != "/bin/bash"
        or installed.get("WorkingDirectory") != str(home)
    ):
        raise CohortError("MARKET_HANDOFF_ACCOUNT_LAUNCHER_MISMATCH")
    output = read_launchd_service(label, root=root)
    if output is None:
        raise CohortError("MARKET_HANDOFF_ACCOUNT_NOT_LOADED")
    pids = re.findall(r"^\tpid = ([1-9][0-9]*)$", output, re.MULTILINE)
    states = re.findall(r"^\tstate = (.+)$", output, re.MULTILINE)
    environment = installed.get("EnvironmentVariables", {})
    if (
        launchd_arguments(output) != args
        or re.findall(r"^\tprogram = (.+)$", output, re.MULTILINE) != ["/bin/bash"]
        or re.findall(r"^\tworking directory = (.+)$", output, re.MULTILINE) != [str(home)]
        or (tq and environment.get("GUIYI_PROJECT_ROOT") != str(root))
        or any(
            values.keys() & {"REDIS_URL", "GUIYI_RUNTIME_ENV", "GUIYI_RUNTIME_DIR"}
            for values in [environment, *launchd_environments(output)]
        )
    ):
        raise CohortError("MARKET_HANDOFF_ACCOUNT_LAUNCHER_MISMATCH")
    if tq and {
        values["GUIYI_PROJECT_ROOT"] for values in launchd_environments(output)
        if "GUIYI_PROJECT_ROOT" in values
    } != {str(root)}:
        raise CohortError("MARKET_HANDOFF_TQ_ROOT_UNPROVEN")
    if not pids and states in (["waiting"], ["spawn scheduled"], ["not running"]):
        raise CohortError("MARKET_HANDOFF_ACCOUNT_STARTING")
    if len(pids) != 1 or states != ["running"]:
        raise CohortError("MARKET_HANDOFF_ACCOUNT_LAUNCHER_MISMATCH")
    return {"pid": int(pids[0]), "plist_sha256": sha256(raw).hexdigest()}


def _account_terminals(session, root, day, products, frequency, now):
    if not root.is_dir():
        raise CohortError("MARKET_HANDOFF_CANONICAL_ROOT_UNPROVEN")
    market = MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))
    expected = {}
    for product in products:
        owner = market.dominant_segment_for_day(product, day)
        windows = market.session_windows(symbol=product, trading_day=day)
        end = expected_intraday_ends(windows, frequency)[-1]
        if end > now:
            raise CohortError("MARKET_HANDOFF_DAY_STILL_OPEN")
        expected[product] = (owner.contract, end)
    return expected


def _tq(home, runtime, expected, now):
    from guiyi_quant.tq_simulation.worker import verify_config

    base = runtime / "tqkq-simulation"
    configuration = _private(base / "config.json")
    config = json.loads(configuration)
    root = verify_config(config)
    launcher = runtime / "run-tq-simulation.sh"
    if file_snapshot(launcher)[0] != file_snapshot(root / "scripts/ops/macos/run-tq-simulation.sh")[0]:
        raise CohortError("MARKET_HANDOFF_TQ_LAUNCHER_MISMATCH")
    args = ("/bin/bash", str(launcher))
    job = _job(home, _TQ_LABEL, args, root, tq=True)
    control = _private(base / "control.json")
    monitor = json.loads(file_snapshot(base / "monitor.json", private=True, limit=8 * 1024 * 1024)[0])
    if (
        monitor.get("pid") != job["pid"] or monitor.get("runtime_root") != str(root)
        or monitor.get("runtime_commit") != config["commit"] or monitor.get("runtime_tag") != config["tag"]
    ):
        raise CohortError("MARKET_HANDOFF_TQ_MONITOR_IDENTITY_CHANGED")
    result = tq_watermark(base / "accounts" / config["account_id"] / "account.sqlite",
                          config["account_id"], expected, now)
    if (_private(base / "config.json") != configuration
            or _private(base / "control.json") != control
            or _job(home, _TQ_LABEL, args, root, tq=True) != job):
        raise CohortError("MARKET_HANDOFF_TQ_OWNER_CHANGED")
    mode = json.loads(control)["mode"]
    if mode not in {"trade", "observe", "pause", "stop"}:
        raise CohortError("MARKET_HANDOFF_TQ_CONTROL_UNKNOWN")
    overview = monitor["overview"]
    observer = overview["observer"]
    if overview.get("account", {}).get("key") != config["account_id"]:
        raise CohortError("MARKET_HANDOFF_TQ_MONITOR_ACCOUNT_MISMATCH")
    native_scope = overview.get("trading_scope", {})
    published_at = datetime.fromisoformat(observer["published_at"])
    fresh = timedelta(0) <= datetime.now(UTC) - published_at <= timedelta(seconds=60)
    if (
        mode not in {"trade", "observe"} or os.path.lexists(base / "hold.json")
        or observer.get("mode") != mode or observer.get("connection") != "LOGGED_IN"
        or observer.get("host_status") == "RECOVERY_REQUIRED" or not fresh
        or overview.get("readback_status") != "verified"
        or native_scope.get("native_readback_verified") is not True
        or native_scope.get("status") != "ACTIVE"
        or datetime.now(UTC) >= datetime.fromisoformat(result["readback_valid_until"])
    ):
        result["status"] = "blocked"
    return {
        **result, **job, "commit": config["commit"], "tag": config["tag"], "mode": mode,
        "root": str(root),
        "config_sha256": sha256(configuration).hexdigest(),
        "control_sha256": sha256(control).hexdigest(),
        "monitor_fresh": fresh, "monitor_readback_status": overview.get("readback_status"),
    }


def _paper_identity(home, runtime, *, stopped=False):
    base = runtime / "subing-paper"
    installed = home / "Library/LaunchAgents" / f"{SUBING_PAPER_LABEL}.plist"
    arguments = plistlib.loads(file_snapshot(installed)[0])["ProgramArguments"]
    root = Path(arguments[-1])
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise CohortError("MARKET_HANDOFF_SUBING_ROOT_UNPROVEN")
    args = ("/bin/bash", str(root / "scripts/ops/macos/run-subing-paper.sh"), str(root))
    if stopped:
        if tuple(arguments) != args or read_launchd_service(SUBING_PAPER_LABEL, root=root) is not None:
            raise CohortError("MARKET_HANDOFF_SUBING_STOP_UNPROVEN")
        job = {"plist_sha256": sha256(file_snapshot(installed)[0]).hexdigest()}
    else:
        job = _job(home, SUBING_PAPER_LABEL, args, root)
    commit = read_command(["/usr/bin/git", "rev-parse", "HEAD"], root=root)
    active = base / "subing-portfolio-active.json"
    registration = _private(active)
    run_id = json.loads(registration)["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", run_id):
        raise CohortError("MARKET_HANDOFF_SUBING_RUN_UNPROVEN")
    database_path = base / "subing-model-database.url"
    database_bound = _private(database_path)
    if read_command(["/usr/bin/git", "-c", "core.fsmonitor=false", "status", "--porcelain"], root=root):
        raise CohortError("MARKET_HANDOFF_SUBING_WORKTREE_DIRTY")
    return root, job, commit, run_id, registration, database_bound


def _paper(home, runtime, expected, day, redis_url, redis_frontier, *,
           generation_prefix=None, prefix=None, stopped=False, active_instance=None):
    base = runtime / "subing-paper"
    identity = _paper_identity(home, runtime, stopped=stopped)
    root, job, commit, run_id, registration, database_bound = identity
    adapter = Path(runtime_market_account_readback.__file__).resolve(strict=True)
    completed = subprocess.run(
        [str(root / "services/quant-api/.venv/bin/python"), str(adapter)],
        input=json.dumps({
            "root": str(root), "database_url": database_bound.decode().strip(),
            "redis_url": redis_url, "run_id": run_id, "trading_day": day.isoformat(),
            "redis_frontier": redis_frontier,
            "generation_prefix": generation_prefix, "prefix": prefix,
            "active_instance": active_instance,
            "expected": {product: (contract, at.isoformat()) for product, (contract, at) in expected.items()},
        }),
        cwd=root, env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home),
            "PYTHONDONTWRITEBYTECODE": "1", "PGOPTIONS": "-c statement_timeout=20000",
            "PYTHONPATH": os.pathsep.join(str(root / part)
                                         for part in (".", "services/quant-api", "packages/quant-core")),
        },
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=60, check=False,
    )
    if completed.returncode:
        raise CohortError("MARKET_HANDOFF_SUBING_PINNED_PROCESS_FAILED")
    result = json.loads(completed.stdout)
    if result.get("code"):
        return result
    if result.get("run_id") != run_id or result.get("redis_frontier") != redis_frontier:
        raise CohortError("MARKET_HANDOFF_SUBING_FRONTIER_CHANGED")
    if _paper_identity(home, runtime, stopped=stopped) != identity:
        raise CohortError("MARKET_HANDOFF_SUBING_OWNER_CHANGED")
    stable = {**result, **job, "disk_commit": commit, "root": str(root),
              "registration_sha256": sha256(registration).hexdigest(),
              "database_sha256": sha256(database_bound).hexdigest()}
    if stopped:
        return stable
    pulse = json.loads(_private(base / "subing-portfolio-heartbeat.json"))
    elapsed = datetime.now(UTC) - datetime.fromisoformat(pulse["at"])
    fresh = timedelta(0) <= elapsed <= timedelta(seconds=60)
    allowed = {"SESSION_COMPLETE", "SESSION_CLOSED"} if prefix is None else {
        "RUNNING", "SESSION_BREAK", "SESSION_COMPLETE", "SESSION_CLOSED",
    }
    if not fresh or pulse.get("run_id") != run_id or pulse.get("status") not in allowed:
        stable["status"] = "blocked"
    return {**stable, "heartbeat_fresh": fresh, "heartbeat_status": pulse.get("status")}


def _read_account(reader):
    try:
        return reader()
    except CohortError as exc:
        return {"status": "blocked", "code": str(exc)}
    except Exception:
        return {"status": "blocked", "code": "MARKET_HANDOFF_ACCOUNT_READBACK_UNAVAILABLE"}


def read_current(home, day, now, *, consumer="all"):
    runtime = home / "Library/Application Support/GuiyiQuant"
    settings, identity = load_private_readonly_settings(runtime / "project.env")
    values = read_only_dependency_environment(settings)
    bindings = read_bindings(home=home)
    if bindings is None:
        raise CohortError("MARKET_HANDOFF_BINDINGS_UNPROVEN")
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    database = create_engine(normalize_database_url(settings["DATABASE_URL"]),
                             connect_args={"connect_timeout": 5})
    try:
        with (
            closing(Redis.from_url(values["REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)) as redis,
            Session(database) as session,
            readonly_transaction(session, timeout_seconds=20),
        ):
            if session.get_bind().url.database != "guiyi_quant":
                raise CohortError("MARKET_HANDOFF_FORMAL_CATALOG_REQUIRED")
            require_bar_writer_namespace(redis)
            source = ObservationStream(redis, kind="source")
            stream = ObservationStream(redis, kind="completed")
            instance = redis_instance(redis)
            source_tail, completed_tail = source.tail(day), stream.tail(day)
            if source.registered_day("live") != day or "0-0" in (source_tail, completed_tail):
                raise CohortError("MARKET_HANDOFF_OLD_DAY_UNPROVEN")
            reports = {}
            if consumer in {"all", "subing"}:
                reports["subing"] = _read_account(lambda: _paper(
                    home, runtime, _account_terminals(session, root, day, EXPANDED_PORTFOLIO_PRODUCTS, "1m", now),
                    day, values["REDIS_URL"], [instance, completed_tail],
                ))
            if consumer in {"all", "tqkq"}:
                reports["tqkq"] = _read_account(lambda: _tq(
                    home, runtime, _account_terminals(session, root, day, TRADING_PRODUCTS, "60m", now),
                    datetime.now(UTC),
                ))
            if (
                redis_instance(redis) != instance or source.registered_day("live") != day
                or source.tail(day) != source_tail or stream.tail(day) != completed_tail
                or read_bindings(home=home) != bindings
                or sha256(_private(runtime / "project.env")).hexdigest() != identity["config_sha256"]
            ):
                raise CohortError("MARKET_HANDOFF_HOST_CHANGED")
    finally:
        database.dispose()
    return {
        "status": "watermarks_verified" if reports and all(
            result["status"] == "verified" for result in reports.values()
        ) else "blocked",
        "mode": "read_only_account_preflight", "takeover": "not_executed",
        "source_binding_basis": "private_project_settings_and_registry",
        "trading_day": day.isoformat(), **identity, "redis_instance": instance,
        "source_tail": source_tail, "completed_tail": completed_tail,
        "registered_feed_commit": bindings.services["market-feed"].commit,
        "registered_live_commit": bindings.services["live"].commit,
        **reports,
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"cohort-market-plan", "cohort-market-apply", "cohort-market-recovery", "cohort-market-accounts"}:
        return _cohort_main(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trading-day", required=True, type=date.fromisoformat)
    parser.add_argument("--consumer", choices=("all", "tqkq", "subing"), default="all")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "darwin":
            raise CohortError("MARKET_HANDOFF_MACOS_REQUIRED")
        result = read_current(Path.home(), args.trading_day, datetime.now(UTC), consumer=args.consumer)
    except CohortError as exc:
        result = {"status": "blocked", "code": str(exc)}
    except (OSError, ValueError, KeyError):
        result = {"status": "blocked", "code": "MARKET_HANDOFF_HOST_READBACK_UNAVAILABLE"}
    except Exception:
        result = {"status": "blocked", "code": "MARKET_HANDOFF_DEPENDENCIES_UNAVAILABLE"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "watermarks_verified" else 1


def _cohort_main(argv):
    from app.runtime_cohort import _resolution_source, apply_cohort, freeze_cohort, require
    from app.runtime_market_cohort_host import MarketCohortHost

    mode, *arguments = argv
    parser = argparse.ArgumentParser(prog=mode)
    if mode == "cohort-market-plan":
        parser.add_argument("--candidate-root", type=Path, required=True)
        parser.add_argument("--tag", required=True)
        parser.add_argument("--commit", required=True)
    else:
        parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        require(sys.platform == "darwin", "MARKET_HANDOFF_MACOS_REQUIRED")
        host = MarketCohortHost()
        if mode == "cohort-market-plan":
            result = freeze_cohort(host, candidate_root=args.candidate_root, tag=args.tag,
                                   commit=args.commit, market_source=True)
        elif mode == "cohort-market-recovery":
            result = host.read_market_source_recovery(args.plan)
        elif mode == "cohort-market-accounts":
            result = host.read_market_source_accounts(args.plan)
        else:
            _, plan = _resolution_source(args.plan)
            intent = plan.get("market_source_handover")
            require(isinstance(intent, dict) and "host_sha256" in intent,
                    "COHORT_MARKET_SOURCE_PLAN_INVALID")
            result = apply_cohort(host, plan)
    except Exception as exc:
        code = str(exc) if isinstance(exc, CohortError) else "MARKET_SOURCE_OPERATION_BLOCKED"
        result = {"status": "blocked", "code": code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code)
                  else "MARKET_SOURCE_OPERATION_BLOCKED"}
    print(json.dumps(result, sort_keys=True))
    return int(result.get("status") == "blocked")


if __name__ == "__main__":
    raise SystemExit(main())
