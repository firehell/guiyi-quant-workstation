"""Single-account continuous TqKq host; source authority remains in the API helper."""

from pathlib import Path
from datetime import datetime, UTC, timedelta
import argparse
import contextlib
import json
import logging
import os
import re
import signal
import subprocess
import time
from .runtime import (
    read_private,
    write_private,
    private_folder,
    owner_lock,
    directory,
    verify_launcher,
)
from .credentials import CredentialStore
from .gateway import Gateway
from .controller import Controller, TERMINAL
from .market import Market, bind_symbol, execution_input
from .monitor import projection, blank
from ..htdy_account_execution import codec, model as m
from ..htdy_account_execution.scheduling import execution_candidates


def verify_config(config):
    if (
        set(config) != {"schema", "provider", "account_id", "root", "commit", "tag"}
        or config["schema"] != 1
        or config["provider"] != "TQKQ"
    ):
        raise ValueError("TQ_CONFIG_INVALID")
    if (
        not re.fullmatch("[0-9a-f]{64}", config["account_id"])
        or not re.fullmatch("[0-9a-f]{40}", config["commit"])
        or not re.fullmatch(r"v\d+\.\d+\.\d+", config["tag"])
    ):
        raise ValueError("TQ_CONFIG_IDENTITY_INVALID")
    root = Path(config["root"])
    if root.resolve(strict=True) != root:
        raise ValueError("TQ_CONFIG_ROOT_INVALID")

    def git(*args):
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    if (
        git("rev-parse", "HEAD") != config["commit"]
        or git("rev-parse", config["tag"] + "^{commit}") != config["commit"]
        or git("cat-file", "-t", "refs/tags/" + config["tag"]) != "tag"
        or git("status", "--porcelain", "--untracked-files=normal")
    ):
        raise ValueError("TQ_EXACT_RELEASE_REQUIRED")
    return root


def should_tick(state, now, *, stopping=False, opening_allowed=True, facts=None):
    pending = [o for o in state.orders if not o.reconciled]
    if not pending:
        return bool(execution_candidates(state, opening_allowed=True))
    return any(
        o.accepted_at is not None
        and (
            o.cancel_required
            or stopping
            or o.offset == "OPEN"
            and (
                not opening_allowed
                or any(
                    f["contract"] == o.contract
                    and (
                        lambda s: s.at <= now < s.valid_until
                        and now >= s.final_close_at - timedelta(seconds=60)
                    )(codec.decode(f["session"]))
                    for f in (facts or {}).values()
                )
                or any(
                    p.product == o.product
                    and (
                        p.opening_consumed
                        or p.rolling
                        or p.product in state.blocked_products
                        or p.desired != (1 if o.side == "BUY" else -1)
                    )
                    for p in state.products
                )
                or o.signal_id in state.abandoned
            )
            or now >= o.accepted_at + timedelta(seconds=180)
        )
        and not o.cancel_sent
        and o.status not in TERMINAL
        for o in pending
    )


def preflight_ready(controller, snapshot, issues, mappings, products, now):
    if issues or set(mappings) != set(products):
        return False
    if controller.store is None:
        return not snapshot["positions"] and not any(
            o["state"] not in TERMINAL for o in snapshot["orders"]
        )
    state = controller.store.current()
    return (
        state.phase == "READY"
        and state.readback_valid
        and state.readback.at <= now < state.readback.valid_until
        and not state.unresolved_fill_ids
    )


def recover_blocked_products(controller, gateway, packets):
    state = controller.store.current()
    owners = {p.product: p.owner for p in state.products}
    selected = tuple(
        proof for proof in (codec.decode(packet) for packet in packets)
        if proof.product in state.blocked_products
        and proof.contract == owners[proof.product]
    )
    if not selected:
        return False
    current = datetime.now(UTC)
    snapshot = gateway.snapshot(current)
    rb = controller.synchronize(snapshot, current)
    products = tuple(sorted({proof.product for proof in selected}))
    cmd = m.ProductRecoveryV1(rb, selected, products)
    controller.store.execute("tq-product-recovery:" + codec.digest(cmd), cmd)
    return True


def require_recovery(controller, at):
    if controller.store is not None and controller.store.current().phase == "READY":
        controller.store.execute(
            "tq-continuity-break:" + at.isoformat(), m.Disconnect(at)
        )


def run(config_path, *, inspect=False):
    logging.disable(
        logging.CRITICAL
    )  # SDK errors can include authentication responses; never publish raw text.
    config = read_private(config_path, limit=8192)
    root = verify_config(config)
    verify_launcher(root)
    credentials = CredentialStore().load()
    if credentials.account_id != config["account_id"]:
        raise ValueError("TQ_CREDENTIAL_ACCOUNT_MISMATCH")
    base = private_folder(directory())
    accounts = private_folder(base / "accounts")
    folder = private_folder(accounts / config["account_id"])
    control_path = base / "control.json"
    monitor_path = base / "monitor.json"
    stopped = False

    def request_stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with owner_lock(base / "owner.lock"):
        gateway = market = controller = None
        snapshot = None
        last_equity = None
        last_publish = 0
        last_native = None
        last_market = 0
        issues = {}
        mode = "observe"
        day = None
        held = None
        last_recovery = 0
        facts = {}
        try:
            with (
                open(os.devnull, "w") as sink,
                contextlib.redirect_stdout(sink),
                contextlib.redirect_stderr(sink),
            ):
                gateway = Gateway(credentials)
            market = Market(root, root / "services/quant-api/.venv/bin/python")
            controller = Controller(
                folder, config["account_id"], market.products, gateway
            )
            while True:
                now = datetime.now(UTC)
                control = (
                    read_private(control_path, limit=1024)
                    if control_path.exists()
                    else {"mode": "observe"}
                )
                if set(control) != {"mode"} or control["mode"] not in {
                    "observe",
                    "trade",
                    "pause",
                    "stop",
                }:
                    raise ValueError("TQ_CONTROL_INVALID")
                action = "stop" if stopped else control["mode"]
                if inspect:
                    action = "observe"
                if (base / "hold.json").exists() and action != "stop":
                    action = "pause"
                mode = "trade" if action in {"trade", "pause", "stop"} else "observe"
                gateway.execution_allowed = action != "observe" and not inspect
                try:
                    gateway.update(0.5)
                    now = datetime.now(UTC)
                    snapshot = gateway.snapshot(now)
                    if action == "trade" and controller.store is None:
                        controller.bootstrap(snapshot, now)
                    if gateway.reconnection_required:
                        require_recovery(controller, now)
                    state = controller.store.current() if controller.store else None
                    native = digest_native(snapshot)
                    due = bool(
                        state
                        and should_tick(
                            state,
                            now,
                            stopping=action == "stop",
                            opening_allowed=action == "trade",
                            facts=facts,
                        )
                    )
                    if state and (
                        native != last_native or due or gateway.reconnection_required
                    ):
                        rb = controller.synchronize(snapshot, now)
                        last_native = native
                    else:
                        rb = None
                    if action == "stop" and controller.store is not None:
                        # A broken signal channel must not prevent a safe stop.
                        # Read the entire native account first; any pending or
                        # uncertain obligation still takes the normal stop path.
                        controller.synchronize(snapshot, now)
                        stopped_state = controller.store.current()
                        if (
                            stopped_state.phase == "READY"
                            and stopped_state.readback_valid
                            and not stopped_state.unresolved_fill_ids
                            and all(o.reconciled for o in stopped_state.orders)
                            and all(o["state"] in TERMINAL for o in snapshot["orders"])
                        ):
                            break
                    if (
                        state
                        and rb is not None
                        and state.phase != "READY"
                        and not (base / "hold.json").exists()
                        and controller.resume_never_active(rb, datetime.now(UTC))
                    ):
                        gateway.reconnection_required = False
                        state = controller.store.current()
                    contracts = ()
                    if state:
                        contracts = tuple(
                            (c.product, c.contract)
                            for c in execution_candidates(
                                state, opening_allowed=action == "trade"
                            )
                        )
                    if time.monotonic() - last_market >= 1 or inspect:
                        reply = market.poll(
                            controller.store.current() if controller.store else None,
                            contracts,
                            inspect=inspect,
                        )
                        last_market = time.monotonic()
                        issues = reply["issues"]
                        facts = {
                            (f["product"], f["contract"]): f for f in reply["facts"]
                        }
                        days = {
                            f["trading_day"]
                            for f in reply["facts"]
                            if codec.decode(f["session"]).can_trade
                        }
                        if len(days) > 1:
                            raise ValueError("TQ_TRADING_DAY_CONFLICT")
                        day = next(iter(days)) if days else day
                        current_mappings = set()
                        for fact in reply["facts"]:
                            try:
                                bind_symbol(gateway, controller, fact)
                                current_mappings.add(fact["product"])
                            except Exception:
                                issues[fact["product"]] = "TQ_SYMBOL_MAPPING_UNPROVEN"
                        recovered_batch = False
                        if (
                            state
                            and (
                                state.phase != "READY" or gateway.reconnection_required
                            )
                            and time.monotonic() - last_recovery >= 5
                        ):
                            now = datetime.now(UTC)
                            snapshot = gateway.snapshot(now)
                            rb = controller.synchronize(snapshot, now)
                            controller.recover(
                                rb, [codec.decode(p) for p in reply["recovery"]]
                            )
                            gateway.reconnection_required = False
                            recovered_batch = True
                            last_recovery = time.monotonic()
                        if (
                            state
                            and not recovered_batch
                            and action in {"trade", "pause"}
                        ):
                            for packet in reply["signals"]:
                                s = codec.decode(packet)
                                fact = facts.get((s.product, s.contract))
                                if fact is None or s.product in issues:
                                    continue
                                # Authority/owner precedes this exact observed signal; no fabricated time.
                                prior = next(
                                    p
                                    for p in controller.store.current().products
                                    if p.product == s.product
                                )
                                if prior.owner != s.contract:
                                    controller.owner(
                                        s.product,
                                        s.contract,
                                        datetime.now(UTC),
                                        fact["source_id"],
                                    )
                                controller.signal(s)
                            recover_blocked_products(controller, gateway, reply["recovery"])
                    if inspect:
                        report = {
                            "status": "READ_ONLY_CONNECTED",
                            "account_id": config["account_id"],
                            "equity": snapshot["account"]["balance"],
                            "position_count": len(snapshot["positions"]),
                            "active_orders": sum(
                                o["state"] not in TERMINAL for o in snapshot["orders"]
                            ),
                            "mapped_contracts": len(current_mappings),
                            "products": len(market.products),
                            "issues": issues,
                            "ready_for_start": preflight_ready(
                                controller,
                                snapshot,
                                issues,
                                current_mappings,
                                market.products,
                                datetime.now(UTC),
                            )
                            and not (base / "hold.json").exists(),
                        }
                        write_private(
                            base / "preflight.json",
                            {
                                **report,
                                "at": datetime.now(UTC).isoformat(),
                                "config": config,
                            },
                        )
                        print(json.dumps(report), flush=True)
                        return 0
                    state = controller.store.current() if controller.store else None
                    if (
                        state
                        and action != "observe"
                        and should_tick(
                            state,
                            datetime.now(UTC),
                            stopping=action == "stop",
                            opening_allowed=action == "trade",
                            facts=facts,
                        )
                    ):
                        inputs = []
                        for candidate in execution_candidates(
                            state, opening_allowed=action == "trade"
                        ):
                            fact = facts.get((candidate.product, candidate.contract))
                            if fact is None:
                                continue
                            symbol = next(
                                (
                                    s
                                    for s, p in controller.symbols.items()
                                    if p == (candidate.product, candidate.contract)
                                ),
                                None,
                            )
                            if symbol is None:
                                continue
                            pending = next(
                                (
                                    o
                                    for o in state.orders
                                    if o.product == candidate.product
                                    and not o.reconciled
                                ),
                                None,
                            )
                            side = (
                                pending.side
                                if pending
                                else (
                                    "BUY"
                                    if next(
                                        p
                                        for p in state.products
                                        if p.product == candidate.product
                                    ).desired
                                    > 0
                                    else "SELL"
                                )
                            )
                            try:
                                inputs.append(
                                    execution_input(
                                        gateway,
                                        fact,
                                        symbol,
                                        side,
                                        cancelling=pending is not None,
                                        opening=candidate.offset == "OPEN"
                                        and pending is None,
                                    )
                                )
                            except Exception:
                                issues[candidate.product] = (
                                    "TQ_EXECUTION_INPUT_UNAVAILABLE"
                                )
                        now = datetime.now(UTC)
                        snapshot = gateway.snapshot(now)
                        if gateway.reconnection_required:
                            require_recovery(controller, now)
                        rb = controller.synchronize(snapshot, now)
                        if (
                            controller.store.current().phase == "READY"
                            and not gateway.reconnection_required
                        ):
                            controller.tick(
                                inputs,
                                datetime.now(UTC),
                                opening_allowed=action == "trade",
                                stopping=action == "stop",
                            )
                    elif (
                        state
                        and action in {"pause", "stop"}
                        and not any(
                            o.offset == "OPEN" and not o.reconciled
                            for o in state.orders
                        )
                    ):
                        # Consume paused targets once, without generating historical opens.
                        if any(not p.opening_consumed for p in state.products):
                            now = datetime.now(UTC)
                            snapshot = gateway.snapshot(now)
                            controller.synchronize(snapshot, now)
                            controller.tick(
                                (),
                                datetime.now(UTC),
                                opening_allowed=False,
                                stopping=action == "stop",
                            )
                    held = None
                    if action == "stop" and not any(
                        o["state"] not in TERMINAL
                        and o["order_id"] in controller.journal.mappings()
                        for o in snapshot["orders"]
                    ):
                        # Missing claimed orders remain UNKNOWN, never a successful stop proof.
                        if controller.store:
                            controller.synchronize(snapshot, datetime.now(UTC))
                        break
                except Exception as error:
                    candidate = str(error) if type(error) is ValueError else ""
                    code = (
                        candidate
                        if re.fullmatch(r"TQ_[A-Z0-9_]{1,100}", candidate)
                        else "TQ_EXECUTION_BLOCKED"
                    )
                    persistent = (
                        read_private(base / "hold.json", limit=1024)
                        if (base / "hold.json").exists() else None
                    )
                    held = persistent["code"] if persistent else code
                    if controller.store:
                        # A disconnect always destroys permission to reuse a target.
                        state = controller.store.current()
                        if (
                            code in {"TQ_DISCONNECTED", "TQ_RECOVERY_REQUIRED"}
                            and state.phase == "READY"
                        ):
                            controller.store.execute(
                                "disconnect:" + datetime.now(UTC).isoformat(),
                                m.Disconnect(datetime.now(UTC)),
                            )
                    if inspect:
                        print(
                            json.dumps({"status": "READ_ONLY_BLOCKED", "code": code}),
                            flush=True,
                        )
                        return 1
                    if persistent is None and code not in {
                        "TQ_DISCONNECTED",
                        "TQ_RECOVERY_REQUIRED",
                        "TQ_ACCOUNT_INCOMPLETE",
                        "TQ_AWAITING_ORDER_FACTS",
                        "TQ_AWAITING_TRADE_FACTS",
                        "TQ_AWAITING_ACCOUNT_FACTS",
                        "TQ_MARKET_AUTHORITY_UNAVAILABLE",
                    }:
                        # An unknown send, external mutation or corrupted ledger is
                        # a durable hold, not another chance to replay the request.
                        write_private(
                            base / "hold.json",
                            {
                                "account_id": config["account_id"],
                                "code": code,
                                "at": datetime.now(UTC).isoformat(),
                            },
                        )
                    if (base / "hold.json").exists():
                        action = "pause"
                if time.monotonic() - last_publish >= 2:
                    now = datetime.now(UTC)
                    if snapshot and (
                        last_equity is None or now - last_equity >= timedelta(minutes=5)
                    ):
                        controller.journal.event(
                            "equity",
                            {
                                "at": now.isoformat(),
                                "equity": snapshot["account"]["balance"],
                                "trading_day": day,
                            },
                            now,
                        )
                        last_equity = now
                    persistent = (
                        read_private(base / "hold.json", limit=1024)
                        if (base / "hold.json").exists()
                        else None
                    )
                    code = held or (persistent["code"] if persistent else None)
                    opening = (
                        action == "trade"
                        and code is None
                        and controller.store is not None
                        and controller.store.current().phase == "READY"
                        and not gateway.reconnection_required
                    )
                    payload = projection(
                        controller,
                        snapshot,
                        now,
                        mode=mode,
                        opening=opening,
                        code=code,
                        trading_day=day,
                        source_issues=issues,
                    )
                    payload.update(
                        runtime_root=str(root),
                        runtime_commit=config["commit"],
                        runtime_tag=config["tag"],
                        pid=os.getpid(),
                    )
                    write_private(monitor_path, payload)
                    last_publish = time.monotonic()
                # A persisted hold cannot be lifted by merely writing trade to control.
                if (base / "hold.json").exists():
                    # Keep update-driven observation alive, but all later actions
                    # must remain paused until an explicit readback recovery.
                    if read_private(control_path, limit=1024).get("mode") == "trade":
                        write_private(control_path, {"mode": "pause"})
            now = datetime.now(UTC)
            payload = projection(
                controller, snapshot, now, mode=mode, opening=False, trading_day=day
            )
            payload["overview"]["observer"]["status"] = "stopped"
            payload["overview"]["observer"]["stage"] = "STOPPED"
            payload.update(
                runtime_root=str(root),
                runtime_commit=config["commit"],
                runtime_tag=config["tag"],
                pid=os.getpid(),
            )
            write_private(monitor_path, payload)
            return 0
        finally:
            if controller:
                controller.close()
            if market:
                market.close()
            if gateway:
                with (
                    open(os.devnull, "w") as sink,
                    contextlib.redirect_stdout(sink),
                    contextlib.redirect_stderr(sink),
                ):
                    gateway.close()


def digest_native(snapshot):
    from .journal import digest

    return digest({k: snapshot[k] for k in ("positions", "orders", "trades")})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    try:
        return run(args.config, inspect=args.inspect)
    except Exception as error:
        code = (
            str(error) if type(error) is ValueError else "TQ_CONNECT_OR_RUNTIME_FAILED"
        )
        if not re.fullmatch(r"TQ_[A-Z0-9_]{1,100}", code):
            code = "TQ_CONNECT_OR_RUNTIME_FAILED"
        try:
            base = private_folder(directory())
            out = blank(datetime.now(UTC), code)
            write_private(base / "monitor.json", {"overview": out, "records": []})
        except Exception:
            pass
        print(json.dumps({"status": "BLOCKED", "code": code}), flush=True)
        return 1


if __name__ == "__main__":
    code = main()
    import sys

    sys.stdout.flush()
    os._exit(code)
