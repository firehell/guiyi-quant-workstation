"""Explicit reconciliation of already filled, owner-approved manual closes."""

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
import stat
import os

from ..htdy_account_execution import model as m
from ..htdy_account_execution.reducer import apply
from .gateway import decimal, quantity, instant_ns
from .journal import digest
from .runtime import read_private_bytes


def require(value):
    if not value:
        raise ValueError("TQ_MANUAL_CLOSE_EVIDENCE_UNPROVEN")


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def validate_snapshot(snapshot):
    payload = {k: v for k, v in snapshot.items() if k not in {"snapshot_id", "observed_at"}}
    require(snapshot["snapshot_id"] == digest(payload))
    observed = datetime.fromisoformat(snapshot["observed_at"])
    m.time(observed)
    return observed


def native_record_matches(record, observations, identity, price_field):
    matches = [value for value in observations if value.get(identity) == record[identity]]
    if len(matches) != 1 or matches[0].keys() != record.keys():
        return False
    observed = matches[0]
    return all(
        decimal(value, positive=True) == decimal(observed[key], positive=True)
        if key == price_field else value == observed[key]
        for key, value in record.items()
    )


def load_evidence(folder):
    folder = Path(folder)
    require(folder.is_absolute() and folder.resolve(strict=True) == folder)
    info = folder.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077)
    intents = sorted(folder.glob("*-intent.json"))
    require(1 <= len(intents) <= 60)
    files = {"before.json", "after.json"}
    for path in intents:
        require(re.fullmatch(r"(?:0[1-9]|[1-5][0-9]|60)-intent\.json", path.name))
        files.update((path.name, path.name.replace("-intent", "-readback")))
    raw = {name: read_private_bytes(folder / name, limit=512 * 1024) for name in sorted(files)}
    import json
    values = {name: json.loads(body, object_pairs_hook=unique_fields) for name, body in raw.items()}
    fingerprint = digest({name: sha256(body).hexdigest() for name, body in raw.items()})
    before, after = values["before.json"], values["after.json"]
    validate_snapshot(before)
    validate_snapshot(after)
    require(before["account_id"] == after["account_id"])
    records = []
    for path in intents:
        intent = values[path.name]
        observation = values[path.name.replace("-intent", "-readback")]
        validate_snapshot(observation)
        require(observation["account_id"] == after["account_id"])
        orders = [o for o in observation["orders"] if o["order_id"] == intent["order_id"]]
        trades = [t for t in observation["trades"] if t["order_id"] == intent["order_id"]]
        require(len(orders) == len(trades) == 1)
        order, trade = orders[0], trades[0]
        symbol = order["exchange_id"] + "." + order["instrument_id"]
        require(symbol == intent["symbol"] and order["direction"] == intent["side"]
                and order["offset"] == trade["offset"] == intent["offset"] == "CLOSE"
                and order["state"] == "FILLED" and order["is_dead"] is True
                and order["is_error"] is False and order["price_type"] == "LIMIT"
                and quantity(order["volume_orign"]) == quantity(trade["volume"]) == intent["quantity"] == 1
                and quantity(order["volume_left"]) == 0
                and decimal(order["limit_price"], positive=True) == decimal(intent["price"], positive=True)
                and trade["direction"] == order["direction"]
                and (trade["exchange_id"], trade["instrument_id"]) == (order["exchange_id"], order["instrument_id"])
                and instant_ns(order["insert_date_time"]) < instant_ns(trade["trade_date_time"]))
        price, limit = decimal(trade["price"], positive=True), decimal(order["limit_price"], positive=True)
        require(price <= limit if order["direction"] == "BUY" else price >= limit)
        records.append((symbol, order, trade))
    require(len({o["order_id"] for _, o, _ in records}) == len(records)
            and len({t["trade_id"] for _, _, t in records}) == len(records))
    old = {p["symbol"]: p for p in before["positions"]}
    remaining = {p["symbol"]: p for p in after["positions"]}
    require(len(old) == len(before["positions"]) and len(remaining) == len(after["positions"]))
    for symbol, order, trade in records:
        require(symbol in old and symbol not in remaining)
        held = old.pop(symbol)
        side = "short" if order["direction"] == "BUY" else "long"
        other = "long" if side == "short" else "short"
        require(held["pos_" + side + "_his"] == 1
                and held["pos_" + side + "_today"] == 0
                and held["pos_" + other + "_his"] == held["pos_" + other + "_today"] == 0)
        require(order in after["orders"] and trade in after["trades"])
    require(old == remaining)
    require({t["trade_id"] for t in after["trades"]}
            - {t["trade_id"] for t in before["trades"]}
            == {t["trade_id"] for _, _, t in records})
    return fingerprint, before, after, tuple(records)


def recorded_command(controller, evidence, approval_source):
    key = "manual-closes:" + evidence
    prior = next((a.command for a in controller.store.current().audit if a.command_id == key), None)
    if prior is not None:
        require(type(prior) is m.TqKqManualClosesV1
                and prior.evidence_sha256 == evidence and prior.approval_source == approval_source)
    return key, prior


def prepare(controller, folder, snapshot, at, approval_source):
    evidence, before, after, records = load_evidence(folder)
    require(before["account_id"] == controller.account_id)
    key, prior = recorded_command(controller, evidence, approval_source)
    if prior is not None:
        return key, prior, True
    observed = validate_snapshot(snapshot)
    require(timedelta(0) <= at - observed <= timedelta(seconds=10))
    require(snapshot["account_id"] == before["account_id"] == controller.account_id)
    require(all(o["state"] in {"FILLED", "CANCELLED", "REJECTED"} for o in snapshot["orders"]))
    require(snapshot["positions"] == after["positions"])
    orders, fills = [], []
    mappings = controller.native_mappings()
    for symbol, native, trade in records:
        require(native_record_matches(native, snapshot["orders"], "order_id", "limit_price")
                and native_record_matches(trade, snapshot["trades"], "trade_id", "price"))
        require(symbol in controller.symbols)
        product, contract = controller.symbols[symbol]
        order_id = "manual-tq:" + native["order_id"]
        require(native["order_id"] not in mappings or mappings[native["order_id"]] == order_id)
        mappings[native["order_id"]] = order_id
        source = "manual-evidence:" + evidence
        orders.append(m.Order(
            order_id, product, contract, native["direction"], "CLOSE",
            "human:" + approval_source, instant_ns(native["insert_date_time"]),
            decimal(native["limit_price"], positive=True), source, source, source,
            status="FILLED", terminal_at=at,
        ))
        fills.append(m.TqKqFill(
            "tq-trade:" + trade["trade_id"], order_id, controller.account_id, contract,
            instant_ns(trade["trade_date_time"]), at, decimal(trade["price"], positive=True),
            None, 1, trade["trade_id"], native["order_id"], snapshot["snapshot_id"],
        ))
    command = m.TqKqManualClosesV1(
        tuple(orders), tuple(fills), controller.readback(snapshot, at, mappings=mappings),
        evidence, approval_source,
    )
    state = controller.store.current()
    apply(state, key, command)
    return key, command, False


def run(config_path, evidence_folder, approval_source, *, commit=False):
    import contextlib
    from datetime import UTC
    from .cli import launch_state
    from .controller import Controller
    from .credentials import CredentialStore
    from .gateway import Gateway
    from .runtime import directory, owner_lock, read_private
    from .worker import verify_config

    base = directory()
    configuration = read_private(config_path, limit=8192)
    verify_config(configuration)
    m.text(approval_source)
    evidence, before, _, _ = load_evidence(evidence_folder)
    require(before["account_id"] == configuration["account_id"])

    def stopped():
        require(not (launch_state() or {}).get("pid")
                and read_private(base / "control.json") == {"mode": "stop"}
                and read_private(config_path, limit=8192) == configuration)
        verify_config(configuration)
        return True

    controller = gateway = None
    with owner_lock(base / "owner.lock"):
        stopped()
        folder = base / "accounts" / configuration["account_id"]
        require((folder / "account.sqlite").is_file() and (folder / "dispatch.sqlite").is_file())
        try:
            controller = Controller(folder, configuration["account_id"], (), None)
            # Existing account products are facts from its verified journal.
            controller.products = tuple(p.product for p in controller.store.current().products)
            stopped()
            key, prior = recorded_command(controller, evidence, approval_source)
            if prior is not None:
                return {"status": "TQ_MANUAL_CLOSE_NOOP", "command_id": key,
                        "count": len(prior.fills), "evidence_sha256": evidence}
            credentials = CredentialStore().load()
            require(credentials.account_id == configuration["account_id"])
            with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                gateway = Gateway(credentials)
            gateway.execution_allowed = False
            gateway.update(0.5)
            at = datetime.now(UTC)
            snapshot = gateway.snapshot(at)
            key, command, duplicate = prepare(
                controller, evidence_folder, snapshot, at, approval_source,
            )
            stopped()
            report = {
                "status": "TQ_MANUAL_CLOSE_NOOP" if duplicate else "TQ_MANUAL_CLOSE_PLANNED",
                "command_id": key, "count": len(command.fills),
                "positions_after": len(command.readback.snapshot.positions),
                "evidence_sha256": command.evidence_sha256,
            }
            if commit and not duplicate:
                def proof(_state):
                    stopped()
                    require(timedelta(0) <= datetime.now(UTC) - at <= timedelta(seconds=60))
                    return True

                controller.journal.event("snapshot", snapshot, at)
                result = controller.store.execute(key, command, manual_close_proof=proof)
                require(not result.effects)
                controller._manual_orders_cache = None
                report.update(status="TQ_MANUAL_CLOSE_RECONCILED", sequence=result.sequence,
                              phase=result.state.phase)
            return report
        finally:
            try:
                if gateway is not None:
                    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                        gateway.close()
            finally:
                if controller is not None:
                    controller.close()
