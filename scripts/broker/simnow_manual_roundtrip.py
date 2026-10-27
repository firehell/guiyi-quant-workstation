"""Explicit owner manual RB long-one-lot acceptance; never an automatic service."""

import argparse
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def write_status(folder, test_id, value, *, recovery=False):
    target = None
    try:
        from guiyi_quant.htdy_account_execution.model import manual_test_id

        manual_test_id(test_id)
        if type(recovery) is not bool:
            return False
        fd, target = tempfile.mkstemp(prefix=".manual-", dir=folder)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        suffix = "-recovery-status.json" if recovery else "-status.json"
        os.replace(target, folder / (test_id.replace(":", "-") + suffix))
        return True
    except Exception:
        return False  # Observability failure never cancels the closing obligation.
    finally:
        if target is not None and os.path.exists(target):
            try:
                os.unlink(target)
            except OSError:
                pass


def run(
    settings,
    module,
    connector,
    test_id,
    *,
    clock=None,
    sleep=None,
    recover_preflight=False,
):
    from guiyi_quant.htdy_account_execution.model import manual_test_id

    manual_test_id(test_id)
    if type(recover_preflight) is not bool:
        raise ValueError("MANUAL_RECOVERY_MODE_INVALID")
    from app.simnow_portfolio_market import PortfolioMarket
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.htdy_execution import Owner
    from guiyi_quant.htdy_account_execution.codec import digest
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.host import Host
    from guiyi_quant.simnow_execution.inventory import project_readback
    from guiyi_quant.simnow_execution.journal import Journal
    from guiyi_quant.simnow_execution.manual_host import (
        admission,
        claim_login,
        manual_effects,
        acceptance,
    )
    from guiyi_quant.simnow_execution.monitor import MonitorPublisher
    from guiyi_quant.simnow_execution.native_portfolio import NativePortfolio
    from guiyi_quant.simnow_execution.supervisor import (
        account_lock,
        verify_recovery_ownership,
    )

    def now():
        return clock() if clock else datetime.now(UTC)

    pause = sleep or time.sleep

    market = PortfolioMarket(("RB",))
    driver = store = journal = evidence = None
    stage = "SESSION_ADMISSION"
    snapshot = None
    host = None
    outcome = 2
    close_attempted = released = False
    result = None
    with account_lock(settings) as folder:

        def publish(value):
            return write_status(folder, test_id, value, recovery=recover_preflight)

        monitor = MonitorPublisher(
            settings.state_root, settings.account_id, test_id, "RB"
        )
        try:
            plan = market.plan(now())
            if not plan.active or plan.trading_day is None:
                raise ValueError("MANUAL_CONTIGUOUS_SESSION_REQUIRED")
            authority = market.authority("RB", plan.trading_day, now())
            admission(authority, now())
            initial = a.LocalStore.inspect(folder / "account.sqlite")
            if any(type(item.command) is a.ManualBeginV1 for item in initial.audit):
                raise ValueError("MANUAL_TEST_ALREADY_STARTED")
            if (
                initial.positions
                or any(not o.reconciled for o in initial.orders)
                or any(not r.released for r in initial.reservations)
            ):
                raise ValueError("MANUAL_EMPTY_ACCOUNT_REQUIRED")
            stage = "LOGIN_ONCE"
            if recover_preflight:
                from guiyi_quant.simnow_execution.manual_recovery import claim_recovery

                claim_recovery(
                    folder,
                    test_id,
                    settings.account_id,
                    now(),
                    trading_day=plan.trading_day.strftime("%Y%m%d"),
                )
            else:
                claim_login(folder, test_id, now(), settings.account_id)
            driver = NativePortfolio(
                settings, folder, module, connector, now=now, initial_funds_timeout=45
            )
            driver.connect()
            stage = "NATIVE_ACCOUNT_PREFLIGHT"
            snapshot = driver.snapshot()
            if (
                snapshot.trading_day != plan.trading_day.strftime("%Y%m%d")
                or snapshot.account_id != settings.account_id
            ):
                raise ValueError("NATIVE_SESSION_IDENTITY_MISMATCH")
            binding, facts = driver.facts(
                "RB", authority.contract, market, snapshot.trading_day
            )
            verify_recovery_ownership(
                snapshot, (binding,), driver.read_journal, initial
            )
            rb, _ = project_readback(
                snapshot,
                (binding,),
                driver.read_journal,
                initial,
                snapshot.at + timedelta(seconds=30),
            )
            checked = a.apply(
                initial, "manual-preflight:" + snapshot.source_id, a.Recover(rb, ())
            ).state
            owner = Owner("RB", authority.contract, now(), authority.source_id)
            checked = a.apply(checked, test_id + ":dry-owner", owner).state
            begin = a.ManualBeginV1(
                test_id, "RB", authority.contract, now(), now() + timedelta(seconds=180)
            )
            # Dry evaluation must pass risk before settlement confirmation or ledger mutation.
            trial = a.apply(checked, test_id + ":dry-begin", begin).state
            trial_tick = a.apply(
                trial, test_id + ":dry-tick", a.ManualTickV1(now(), (facts,), test_id)
            )
            if (
                len(trial_tick.effects) != 1
                or trial_tick.effects[0].order.offset != "OPEN"
            ):
                raise ValueError("MANUAL_FINANCIAL_PREFLIGHT_REQUIRED")
            stage = "SETTLEMENT_AND_RECOVERY"
            store = a.LocalStore(folder / "account.sqlite")
            journal = Journal(folder / "dispatch.sqlite", settings.account_id)
            evidence = Evidence(folder / "native-evidence.sqlite", settings.account_id)
            adapter = driver.adapter(store, journal, snapshot, now())
            host = Host(
                store,
                journal,
                evidence,
                adapter,
                "RB",
                max_submits=1,
                run_id=test_id,
                deadline=begin.open_until,
                manual_test_id=test_id,
            )
            host.baseline = snapshot
            host.reconcile(driver.report, (binding,), now())
            if host.pending or host.needs_recovery:
                raise ValueError("MANUAL_ACCOUNT_RECONCILIATION_REQUIRED")
            store.execute(test_id + ":owner", owner)
            store.execute(test_id + ":begin", begin)
            stop_at = now() + timedelta(minutes=40)
            stage = "MANUAL_EXECUTION"
            while now() < stop_at:
                if driver.transport_failed:
                    raise ValueError("NATIVE_TRANSPORT_FAILED")
                authority_now = market.authority(
                    "RB", plan.trading_day, now(), authority.contract
                )
                # Before the first opening claim, recheck current main/window.
                if not any(
                    o.signal_id == test_id and o.offset == "OPEN"
                    for o in store.current().orders
                ):
                    admission(authority_now, now())
                status = a.manual_status(store.current(), test_id)
                holding = status.due_at is not None and now() < status.due_at
                host.adapter.expire_unacknowledged(now())
                pending = host.adapter.drain()
                if not holding and not pending:
                    try:
                        binding, facts = driver.facts(
                            "RB", authority.contract, market, snapshot.trading_day
                        )
                    except ValueError as exc:
                        if str(exc) != "NATIVE_BOOK_STALE" or driver.transport_failed:
                            raise
                        # A later quote is a new input, never a retry of an unknown order.
                        facts = None
                        cached = driver.last_facts.get(authority.contract)
                        if (
                            cached is not None
                            and now() < cached.instrument.valid_until
                            and any(
                                o.signal_id == test_id and not o.reconciled
                                for o in store.current().orders
                            )
                        ):
                            # Cancellation needs the proven instrument and a current
                            # Session, never a stale replacement order price.
                            fresh = market.authority(
                                "RB", plan.trading_day, now(), authority.contract
                            )
                            binding = driver.binding(
                                "RB",
                                authority.contract,
                                market,
                                now(),
                                snapshot.trading_day,
                            )[0]
                            facts = replace(cached, session=fresh.session, quote=None)
                    if facts is not None:
                        pending = host.adapter.drain()
                        if not pending:
                            outcomes = manual_effects(
                                host, (facts,), (binding,), now(), test_id
                            )
                            if any(
                                value
                                in (
                                    "SEND_OUTCOME_UNKNOWN",
                                    "NOT_ACCEPTED_RECONCILE_REQUIRED",
                                )
                                for value in outcomes
                            ):
                                stage = "UNKNOWN_SEND_READBACK_REQUIRED"
                monitor.publish(
                    "READING",
                    now(),
                    connection="LOGGED_IN",
                    native_source_id=snapshot.source_id,
                    ledger_hash=digest(store.current()),
                )
                try:
                    snapshot = driver.snapshot()
                except ValueError as exc:
                    if (
                        str(exc) == "NATIVE_SNAPSHOT_CHANGED"
                        and not driver.transport_failed
                    ):
                        publish(
                            dict(
                                stage="NATIVE_SNAPSHOT_CHANGED_WAIT",
                                at=now().isoformat(),
                                passed=False,
                            ),
                        )
                        continue
                    raise
                host.reconcile(driver.report, (binding,), now())
                status = a.manual_status(store.current(), test_id)
                result = acceptance(
                    store.current(), snapshot, test_id, baseline=host.baseline
                )
                result.update(stage=status.phase, at=now().isoformat())
                execution_complete = result["broker_roundtrip_passed"]
                result["broker_roundtrip_passed"] = False
                result["cleanup_pending"] = True
                publish(result)
                monitor.publish(
                    "ACTIVE",
                    now(),
                    connection="LOGGED_IN",
                    native_source_id=snapshot.source_id,
                    ledger_hash=digest(store.current()),
                )
                if execution_complete or status.terminal:
                    break
                # During confirmed holding no order/quote is needed. Keep real account reads.
                if status.due_at is not None and now() < status.due_at:
                    pause(min(5, max(0, (status.due_at - now()).total_seconds())))
                else:
                    pause(1)
            else:
                raise ValueError("MANUAL_EXECUTION_WINDOW_ENDED")
            stage = "NATIVE_RELEASE_AND_FINAL_DRAIN"
            close_attempted = True
            driver.close()
            released = True
            pending = host.adapter.drain()
            result = acceptance(
                store.current(), snapshot, test_id, baseline=host.baseline
            )
            result.update(
                cleanup_pending=False, native_released=True, tail_pending=bool(pending)
            )
            if pending:
                result["broker_roundtrip_passed"] = False
            outcome = 0 if result["broker_roundtrip_passed"] else 2
            publish(result)
        except Exception:
            try:
                diagnostic = driver.failure_diagnostics() if driver else None
            except Exception:
                diagnostic = {"stage": "DIAGNOSTICS_UNAVAILABLE"}
            value = dict(
                stage=stage,
                at=now().isoformat(),
                passed=False,
                outcome="BLOCKED_RECONCILIATION_REQUIRED",
                diagnostics=diagnostic,
            )
            if (
                host is not None
                and snapshot is not None
                and any(
                    type(item.command) is a.ManualBeginV1
                    and item.command.test_id == test_id
                    for item in store.current().audit
                )
            ):
                try:
                    value["last_verified"] = acceptance(
                        store.current(), snapshot, test_id, baseline=host.baseline
                    )
                except Exception:
                    value["last_verified"] = None
            publish(value)
            monitor.publish("ERROR", now(), connection="UNKNOWN")
            result = value
            outcome = 2
        finally:
            if driver and not close_attempted:
                close_attempted = True
                try:
                    driver.close()
                    released = True
                    if host:
                        host.adapter.drain()
                except Exception:
                    outcome = 2
            final_source = final_hash = None
            try:
                if evidence is not None and evidence.latest() is not None:
                    final_source = evidence.latest().source_id
                if store is not None:
                    final_hash = digest(store.current())
            except Exception:
                outcome = 2
            for resource in (evidence, journal, store, market):
                if resource:
                    try:
                        resource.close()
                    except Exception:
                        outcome = 2
            monitor.publish(
                "STOPPED" if released else "ERROR",
                now(),
                connection="RELEASED" if released else "UNKNOWN",
                native_source_id=final_source,
                ledger_hash=final_hash,
            )
            if outcome != 0 and result is not None:
                result.update(broker_roundtrip_passed=False, native_released=released)
                publish(result)
        return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="人工验收：RB权威主力开多1手，确认成交600秒后平仓"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--test-id", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recover-preflight", action="store_true")
    args = parser.parse_args(argv)
    if args.recover_preflight and not args.execute:
        parser.error("recover-preflight requires explicit execute")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages/quant-core"))
    from guiyi_quant.simnow_execution.settings import load_settings
    from guiyi_quant.htdy_account_execution.model import manual_test_id

    manual_test_id(args.test_id)
    settings = load_settings(args.config)
    if settings.project_root != root:
        raise ValueError("MANUAL_SOURCE_IDENTITY_INVALID")
    for name in ("simnow_controlled", "simnow_supervisor"):
        spec = importlib.util.spec_from_file_location(
            name, root / ("scripts/broker/" + name + ".py")
        )
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        if name == "simnow_controlled":
            bounded = value
        else:
            supervisor = value
    module = bounded.bootstrap(root, settings.api_env)
    if not args.execute:
        print("MANUAL_PLAN_ONLY_RB_LONG1_HOLD600_NO_BROKER_IO")
        return 0
    from app.private_settings import private_dependency_settings

    env, _ = private_dependency_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    os.environ.update(supervisor.dependency_environment(env))
    if os.environ.get("GUIYI_SIMNOW_DEPENDENCIES_READY") != "1":
        os.environ["GUIYI_SIMNOW_DEPENDENCIES_READY"] = "1"
        os.execv(
            sys.executable,
            [sys.executable, "-I", str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    saved = os.dup(1), os.dup(2)
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            result = run(
                settings,
                module,
                bounded.connect,
                args.test_id,
                recover_preflight=args.recover_preflight,
            )
    finally:
        for source, target in zip(saved, (1, 2)):
            os.dup2(source, target)
            os.close(source)
    print(
        "MANUAL_ROUNDTRIP_PASSED"
        if result == 0
        else "MANUAL_BLOCKED_CHECK_PRIVATE_STATUS"
    )
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit("MANUAL_STARTUP_BLOCKED_NO_ORDER_PROOF") from None
