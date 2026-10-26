"""One-shot SimNow host. Default preflight is read-only; no Runtime hooks."""

from datetime import datetime, UTC, timedelta
from decimal import Decimal
from pathlib import Path
import argparse
import fcntl
import getpass
import importlib.util
import json
import os
import platform
import sys
import tempfile
import time
import uuid
import warnings


def options(argv=None):
    p = argparse.ArgumentParser(
        description="SimNow第一套：默认只读预检；显式execute仅本次一品种一手验证"
    )
    p.add_argument("--product", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--initialize", action="store_true")
    p.add_argument("--max-seconds", type=int, default=600)
    p.add_argument("--max-submits", type=int, default=1)
    p.add_argument("--api-env", type=Path, help="可选既有API依赖venv；不安装或修改依赖")
    result = p.parse_args(argv)
    if not 10 <= result.max_seconds <= 3600 or not 1 <= result.max_submits <= 3:
        p.error("执行边界须10..3600秒、1..3次submit；每单固定一手")
    if result.initialize and not result.execute:
        p.error("initialize仅用于显式execute的首次空账户启用")
    return result


def bootstrap(root, api_env):
    from importlib.metadata import version

    if (
        platform.system() != "Darwin"
        or platform.machine() != "arm64"
        or version("openctp-ctp") != "6.7.7.1"
    ):
        raise ValueError("VERIFIED_MAC_SDK_REQUIRED")
    env = api_env or root / "services/quant-api/.venv"
    site = (
        env
        / "lib"
        / ("python" + str(sys.version_info.major) + "." + str(sys.version_info.minor))
        / "site-packages"
    )
    if not site.is_dir():
        raise ValueError("API_DEPENDENCY_ENV_REQUIRED")
    sys.path.extend(
        (str(site), str(root / "services/quant-api"), str(root / "packages/quant-core"))
    )
    spec = importlib.util.spec_from_file_location(
        "guiyi_native_gateway", root / "scripts/broker/simnow_native_gateway.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_output(root, account):
    base = root / "output/simnow-controlled"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = base / account
    folder.mkdir(exist_ok=True, mode=0o700)
    if (
        not folder.resolve().is_relative_to((root / "output").resolve())
        or folder.is_symlink()
    ):
        raise ValueError("PRIVATE_ACCOUNT_ROOT_INVALID")
    if folder.stat().st_mode & 0o077:
        raise ValueError("PRIVATE_ACCOUNT_ROOT_INVALID")
    return folder


def connect(gateway, tdapi, flow):
    gateway.api = tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi(str(flow) + "/")
    gateway.api.RegisterSpi(gateway)
    gateway.api.SubscribePrivateTopic(2)
    gateway.api.RegisterFront(gateway.front)
    gateway.api.Init()
    if not gateway.login_done.wait(25) or gateway.failed or not gateway.native_session:
        raise ValueError("FIRST_LOGIN_NOT_VERIFIED")


def run(gateway, tdapi, config, root):
    from guiyi_quant import (
        htdy_execution as h,
        htdy_account_execution as a,
        simnow_execution as b,
    )
    from guiyi_quant.simnow_execution.inventory import read_snapshot, project_readback
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.host import Host
    from guiyi_quant.simnow_execution.facts import (
        bind_contract,
        native_product_id,
        quote_from_native_batch,
        execution_input,
    )
    from guiyi_quant.htdy_account_execution.codec import digest
    from app.simnow_controlled_market import MarketBridge
    from app.htdy_execution import start_account_operational

    def now():
        return datetime.now(UTC)

    def read_book(bound, trading_day):
        rows = gateway.query("book", bound.native)
        received = now()
        matches = [r for r in rows if r["InstrumentID"] == bound.native and r["ExchangeID"] == bound.exchange]
        diagnostic = dict(
            requested_contract=bound.canonical,
            received_at=received.isoformat(),
            batch_rows=len(rows),
            native_id_matches=sum(r["InstrumentID"] == bound.native for r in rows),
            exact_identity_matches=len(matches),
        )
        if len(matches) == 1:
            row = matches[0]
            diagnostic["trading_day_matches"] = row["TradingDay"] == trading_day
            try:
                from zoneinfo import ZoneInfo
                event = datetime.strptime(row["ActionDay"] + row["UpdateTime"], "%Y%m%d%H:%M:%S").replace(
                    tzinfo=ZoneInfo("Asia/Shanghai"), microsecond=row["UpdateMillisec"] * 1000
                )
                diagnostic["event_age_seconds"] = format((received-event).total_seconds(), ".6f")
            except (ValueError, TypeError, KeyError, OverflowError):
                diagnostic["event_time_valid"] = False
        gateway.book_selection_diagnostics = diagnostic
        return quote_from_native_batch(bound, rows, trading_day, received)

    market = MarketBridge(config.product.lower())
    store = journal = evidence = None
    lock_fd = None
    final_snapshot = None
    host = None
    folder = None
    result = None
    monitor = None
    try:
        # All startup dependencies are native/authoritative reads; no default settlement write.
        first = read_snapshot(gateway.snapshot(), now=now())
        day = datetime.strptime(first.trading_day, "%Y%m%d").date()
        authority = market.authority(day, now())
        instruments = gateway.query(
            "instrument", exchange=authority.exchange,
            product=native_product_id(config.product.upper(), authority.exchange),
        )
        until = now() + timedelta(minutes=5)
        binding, metadata = bind_contract(
            authority.contract,
            authority.exchange,
            instruments,
            now(),
            until,
            first.trading_day,
        )
        settlement = gateway.query("settlement")
        confirmed = bool(
            len(settlement) == 1 and settlement[0]["ConfirmDate"] == first.trading_day
        )
        margin = gateway.query("margin", binding.native, exchange=binding.exchange)
        commission = gateway.query("commission", binding.native, exchange=binding.exchange)
        if len(margin) != 1 or len(commission) != 1:
            raise ValueError("NATIVE_RATE_FACTS_INCOMPLETE")
        quote = read_book(binding, first.trading_day)
        authority = market.authority(day, now())
        facts = execution_input(
            binding, metadata, margin[0], commission[0], quote, authority.session, now()
        )
        report = gateway.snapshot()
        snapshot = read_snapshot(report, now=now())
        final_snapshot = snapshot
        bindings = [binding]
        for position in snapshot.data["positions"]:
            if (
                position["Position"]
                or position["LongFrozen"]
                or position["ShortFrozen"]
            ):
                canonical = market.canonical_for_native(
                    position["InstrumentID"], position["ExchangeID"], instruments
                )
                if canonical not in {b.canonical for b in bindings}:
                    extra, _ = bind_contract(
                        canonical,
                        position["ExchangeID"],
                        instruments,
                        now(),
                        now() + timedelta(minutes=5),
                        snapshot.trading_day,
                    )
                    bindings.append(extra)
        execution = [facts]
        rb, _ = project_readback(
            snapshot, tuple(bindings), None, None, snapshot.at + timedelta(seconds=30)
        )
        funding = (
            snapshot.trading_day >= "20261027"
            and rb.snapshot.balance == Decimal(100000)
            and rb.snapshot.available == Decimal(100000)
            and not rb.snapshot.positions
            and not rb.used_margin
            and not rb.frozen_margin
            and not rb.frozen_fee
            and all(
                o.status in ("FILLED", "CANCELLED", "REJECTED")
                for o in rb.snapshot.orders
            )
        )
        if not config.execute:
            return dict(
                status="READ_ONLY_PREFLIGHT_COMPLETE",
                account_id=snapshot.account_id,
                trading_day=snapshot.trading_day,
                initial_100k_observed=funding,
                settlement_confirmed=confirmed,
                execution_book_qualified=True,
                execution_input_observed=dict(
                    contract=binding.canonical,
                    native_contract=binding.native,
                    exchange=binding.exchange,
                    checked_at=facts.instrument.at.isoformat(),
                    tick_size=str(facts.instrument.tick_size),
                    multiplier=str(facts.instrument.multiplier),
                    long_margin_rate=str(facts.instrument.long_margin_rate),
                    short_margin_rate=str(facts.instrument.short_margin_rate),
                    opening_fee_budget=str(facts.instrument.open_fee),
                    margin_exchange_observed=margin[0]["ExchangeID"],
                    commission_exchange_observed=commission[0]["ExchangeID"],
                    margin_exchange_binding="QUERY_SCOPE" if margin[0]["ExchangeID"] == "" else "RESPONSE_FIELD",
                    commission_exchange_binding="QUERY_SCOPE" if commission[0]["ExchangeID"] == "" else "RESPONSE_FIELD",
                    bid=str(quote.bid), ask=str(quote.ask),
                    bid_volume=quote.bid_volume, ask_volume=quote.ask_volume,
                    quote_received_at=quote.at.isoformat(),
                    quote_valid_until=quote.valid_until.isoformat(),
                    quote_source=quote.source_id,
                    scope="OBSERVED_INPUT_NOT_CURRENT_ORDER_PERMISSION",
                ),
                authority_source=authority.source_id,
                orders_sent=0,
                auto_order=False,
                broker_e2e_passed=False,
            )
        if snapshot.trading_day < "20261027":
            raise ValueError("FUNDING_EFFECTIVE_DAY_NOT_REACHED")
        folder = private_output(root, snapshot.account_id)
        lock_fd = os.open(
            folder / "host.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("ACCOUNT_HOST_ALREADY_RUNNING") from None
        path = folder / "account.sqlite"
        if path.exists():
            if config.initialize:
                raise ValueError("ACCOUNT_ALREADY_INITIALIZED")
            store = a.LocalStore(path)
        else:
            if not config.initialize or not funding:
                raise ValueError("VERIFIED_100K_FLAT_INITIALIZATION_REQUIRED")
            activated = now()
            state = start_account_operational(snapshot.account_id, activated, rb)
            state = a.apply(
                state,
                "initial-owner",
                h.Owner(
                    config.product.upper(),
                    authority.owner,
                    activated,
                    authority.source_id,
                ),
            ).state
            store = a.LocalStore(path, state)
        journal = b.Journal(folder / "dispatch.sqlite", snapshot.account_id)
        evidence = Evidence(folder / "native-evidence.sqlite", snapshot.account_id)
        if not evidence.snapshots():
            evidence.append(snapshot)
        if not confirmed:
            settlement = gateway.query("confirm")
            if len(settlement) != 1:
                raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
            confirmed = True
        session = b.Session(
            snapshot.account_id,
            "SIMNOW_FIRST",
            gateway.front,
            snapshot.trading_day,
            **gateway.native_session,
            login_source_id="native-login:"
            + digest(
                (snapshot.account_id, snapshot.trading_day, gateway.native_session)
            ),
            settlement_source_id="native-settlement:" + digest(settlement),
            at=now(),
            valid_until=now() + timedelta(seconds=config.max_seconds + 120),
        )
        adapter = b.Adapter(store, journal, tdapi, gateway.api, gateway.user, session)
        gateway.attach(adapter, snapshot)
        for prepared in store.current().orders:
            if prepared.status == "PROPOSED" and not journal.claimed(prepared.order_id):
                adapter.abort_unsent(
                    prepared.order_id, "RESTART_VERIFIED_NEVER_CLAIMED", now()
                )
        deadline = now() + timedelta(seconds=config.max_seconds)
        host = Host(
            store,
            journal,
            evidence,
            adapter,
            config.product.upper(),
            max_submits=config.max_submits,
            run_id=uuid.uuid4().hex,
            deadline=deadline,
        )
        from guiyi_quant.simnow_execution.monitor import MonitorPublisher

        monitor = MonitorPublisher(
            folder.parent, snapshot.account_id, host.run_id, config.product.upper()
        )

        def monitor_progress(status="READING", connection=None):
            # Observer errors are deliberately outside execution/account transactions.
            try:
                current = store.current()
                monitor.publish(
                    status,
                    now(),
                    connection=connection
                    or ("DISCONNECTED" if gateway.failed else "LOGGED_IN"),
                    native_source_id=current.readback.source_id,
                    ledger_hash=digest(current),
                )
            except Exception:
                monitor.failed = True

        gateway.monitor_progress = monitor_progress
        monitor_progress("STARTING")
        market.activate(now())
        while now() < deadline and not gateway.failed:
            report = gateway.snapshot()
            current = store.current()
            if any(p.product != config.product.upper() for p in current.positions):
                raise ValueError("HELD_POSITION_OUTSIDE_CONTROLLED_SCOPE")
            proofs = (
                market.recovery(current, now())
                if host.needs_recovery or current.phase != "READY"
                else ()
            )
            snapshot, state = host.reconcile(report, tuple(bindings), now(), proofs)
            final_snapshot = snapshot
            adapter.expire_unacknowledged(now())
            adapter.drain()
            current = store.current()
            if current.phase == "BLOCKED" or adapter._faulted:
                break
            if current.phase != "READY" or not current.readback_valid:
                continue
            authority = market.authority(day, now())
            owner = next(
                p for p in current.products if p.product == config.product.upper()
            ).owner
            if authority.owner != owner:
                store.execute(
                    "owner:" + authority.source_id,
                    h.Owner(
                        config.product.upper(),
                        authority.owner,
                        now(),
                        authority.source_id,
                    ),
                )
            signal = market.poll(now(), store.current().activated_at)
            if signal is not None:
                store.execute("natural:" + signal.source_id, signal)
            contracts = (
                {authority.owner}
                | {p.contract for p in store.current().positions}
                | {o.contract for o in store.current().orders if not o.reconciled}
            )
            bindings = []
            rate_facts = []
            for contract in sorted(contracts):
                auth = market.authority(day, now(), contract)
                bound, meta = bind_contract(
                    contract,
                    auth.exchange,
                    instruments,
                    now(),
                    now() + timedelta(minutes=5),
                    snapshot.trading_day,
                )
                mar = gateway.query("margin", bound.native, exchange=bound.exchange)
                com = gateway.query("commission", bound.native, exchange=bound.exchange)
                if len(mar) != 1 or len(com) != 1:
                    raise ValueError("NATIVE_RATE_FACTS_INCOMPLETE")
                bindings.append(bound)
                rate_facts.append((bound, meta, mar[0], com[0]))
            execution = []
            for bound, meta, mar, com in rate_facts:
                q = read_book(bound, snapshot.trading_day)
                auth = market.authority(day, now(), bound.canonical)
                execution.append(
                    execution_input(bound, meta, mar, com, q, auth.session, now())
                )
            adapter.drain()
            outcomes = host.tick(tuple(execution), tuple(bindings), now())
            monitor_progress("ACTIVE")
            if any(
                v in ("SEND_OUTCOME_UNKNOWN", "NOT_ACCEPTED_RECONCILE_REQUIRED")
                for v in outcomes
            ):
                break
            if host.submits >= config.max_submits and all(
                o.reconciled for o in store.current().orders
            ):
                break
            time.sleep(0.2)
        # Never force-flat on exit. Cancel only this program's unfilled opening intent.
        if not gateway.failed and any(
            o.offset == "OPEN" and o.status in ("PROPOSED", "WORKING", "CANCEL_PENDING")
            for o in store.current().orders
        ):
            store.execute("bounded-run-stop:" + host.run_id, a.Disconnect(now()))
            host.needs_recovery = True
            snapshot, state = host.reconcile(
                gateway.snapshot(), tuple(bindings or (binding,)), now(), ()
            )
            final_snapshot = snapshot
            if state is not None and state.readback_valid:
                from dataclasses import replace

                safe = []
                for f in execution:
                    auth = market.authority(day, now(), f.instrument.contract)
                    safe.append(replace(f, session=auth.session, quote=None))
                host.tick(tuple(safe), tuple(bindings), now())
                snapshot, _ = host.reconcile(
                    gateway.snapshot(), tuple(bindings), now(), ()
                )
                final_snapshot = snapshot
        result = host.summary(final_snapshot)
        unsettled = any(not o.reconciled for o in store.current().orders)
        incomplete = (
            gateway.failed
            or store.current().phase == "BLOCKED"
            or not store.current().readback_valid
            or bool(host.pending)
            or unsettled
        )
        result.update(
            status="CONTROLLED_RUN_REQUIRES_RECOVERY"
            if incomplete
            else "CONTROLLED_RUN_ENDED",
            trading_day=snapshot.trading_day,
        )
        return result
    except Exception as exc:
        if host is not None:
            try:
                host.adapter.disconnected(now())
                host.adapter.drain()
                result = host.summary(final_snapshot)
            except Exception:
                result = dict(
                    auto_order=False,
                    broker_e2e_passed=False,
                    account_id=host.adapter.session.account_id,
                )
            result.update(
                status="CONTROLLED_RUN_REQUIRES_RECOVERY",
                error_code=str(exc)
                if type(exc) is ValueError
                and str(exc).replace("_", "").isalnum()
                and str(exc).isascii()
                else "CONTROLLED_RUN_FAILED",
            )
            return result
        raise
    finally:
        # Stop native callbacks before closing either journal, then consume the tail.
        # Otherwise a callback racing Release could be lost against a closed DB.
        if gateway.api is not None:
            gateway.api.RegisterSpi(None)
            gateway.api.Release()
            gateway.api = None
        if host is not None:
            try:
                if gateway.failed:
                    host.adapter.disconnected(now())
                host.pending = host.adapter.drain()
                if result is not None:
                    previous_status = result.get("status")
                    result.update(host.summary(final_snapshot))
                    incomplete = (
                        gateway.failed
                        or host.adapter._faulted
                        or store.current().phase == "BLOCKED"
                        or not store.current().readback_valid
                        or bool(host.adapter.drain())
                        or any(not o.reconciled for o in store.current().orders)
                    )
                    if (
                        incomplete
                        or previous_status == "CONTROLLED_RUN_REQUIRES_RECOVERY"
                    ):
                        result["status"] = "CONTROLLED_RUN_REQUIRES_RECOVERY"
            except Exception:
                if result is not None:
                    result["status"] = "CONTROLLED_RUN_REQUIRES_RECOVERY"
        if monitor is not None:
            monitor_progress(
                "ERROR"
                if gateway.failed or result and result.get("error_code")
                else "STOPPED",
                "RELEASED",
            )
            if result is not None:
                result["monitor_status"] = (
                    "unavailable" if monitor.failed else "published"
                )
        market.close()
        for value in (evidence, journal, store):
            if value is not None:
                value.close()
        if lock_fd is not None:
            os.close(lock_fd)


def main(argv=None):
    config = options(argv)
    root = Path(__file__).resolve().parents[2]
    if not sys.stdin.isatty():
        raise ValueError("LOCAL_TTY_REQUIRED")
    module = bootstrap(root, config.api_env)
    if (
        not config.product.isascii()
        or not config.product.isalpha()
        or len(config.product) > 3
    ):
        raise ValueError("PRODUCT_FORMAT_INVALID")
    print(
        "SimNow第一套："
        + (
            "本次有界执行，每单一手；含必要结算确认"
            if config.execute
            else "只读预检，不报撤单、不确认结算"
        )
    )
    user = input("投资者代码：").strip()
    if not user.isascii() or not user.isdigit() or not 1 <= len(user) <= 15:
        raise ValueError("INVESTOR_FORMAT_INVALID")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("交易密码（隐藏）：")
    if not password or len(password.encode()) > 40:
        raise ValueError("PASSWORD_FORMAT_INVALID")
    gateway = module.Gateway(user, password)
    user = password = ""
    output = dict(
        status="FAILED_NO_EXECUTION_PROOF", auto_order=False, broker_e2e_passed=False
    )
    saved_out, saved_err = os.dup(1), os.dup(2)
    with tempfile.TemporaryDirectory(prefix="guiyi-controlled-flow-") as flow:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            try:
                connect(gateway, module.tdapi, flow)
                output = run(gateway, module.tdapi, config, root)
            except Exception as exc:
                # Fixed local error codes only; native/API/SQL exception text is never emitted.
                output["error_code"] = (
                    str(exc)
                    if type(exc) is ValueError
                    and str(exc).replace("_", "").isalnum()
                    and str(exc).isascii()
                    else "CONTROLLED_RUN_FAILED"
                )
                output["native_failed"] = gateway.failed
            finally:
                output["native_query_diagnostics"] = list(gateway.query_diagnostics)
                output["book_selection_diagnostics"] = getattr(gateway, "book_selection_diagnostics", None)
                try:
                    if gateway.api is not None:
                        gateway.api.RegisterSpi(None)
                        gateway.api.Release()
                finally:
                    gateway.user = gateway.password = ""
                    os.dup2(saved_out, 1)
                    os.dup2(saved_err, 2)
                    os.close(saved_out)
                    os.close(saved_err)
    target = root / "output/simnow-controlled"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.resolve().is_relative_to(root):
        raise ValueError("OUTPUT_OUTSIDE_WORKSPACE")
    path = target / ("run-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + ".json")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(output, f, ensure_ascii=False, sort_keys=True)
    print(output["status"])
    print("结果：" + str(path))
    return (
        0
        if output["status"] in ("READ_ONLY_PREFLIGHT_COMPLETE", "CONTROLLED_RUN_ENDED")
        else 1
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(
            "预检/执行未通过；未获得交易成功证明，请查看本地固定错误码。"
        ) from None
