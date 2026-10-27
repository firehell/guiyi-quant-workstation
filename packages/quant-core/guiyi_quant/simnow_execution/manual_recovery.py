"""Last, explicit pre-opening recovery; preserves the failed attempt and budget."""

from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
import stat

from .. import htdy_account_execution as a
from ..htdy_account_execution.model import manual_test_id
from .evidence import Evidence
from .inventory import native_hash
import sqlite3


def private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or info.st_size > 65536
        ):
            raise ValueError("MANUAL_RECOVERY_PRIVATE_FACT_REQUIRED")
        raw = os.read(fd, 65537)
    finally:
        os.close(fd)
    return raw, json.loads(raw)


def claim_recovery(folder, test_id, account_id, now, *, trading_day):
    manual_test_id(test_id)
    prefix = test_id.replace(":", "-")
    _, plan = private_json(folder / (prefix + "-recovery-plan.json"))
    if set(plan) != {
        "schema",
        "test_id",
        "account_id",
        "expires_at",
        "preimages",
        "failed_status_sha256",
        "diagnostic_fact_sha256",
        "diagnostic_result_sha256",
        "native_source_id",
        "max_total_connections",
        "initial_funds_timeout",
    } or (
        plan["schema"] != "simnow_manual_preflight_recovery_v1"
        or plan["test_id"] != test_id
        or plan["account_id"] != account_id
        or type(plan["max_total_connections"]) is not int
        or plan["max_total_connections"] != 3
        or type(plan["initial_funds_timeout"]) is not int
        or plan["initial_funds_timeout"] != 45
    ):
        raise ValueError("MANUAL_RECOVERY_PLAN_INVALID")
    expires = datetime.fromisoformat(plan["expires_at"])
    if (
        now.tzinfo is None
        or expires.tzinfo is None
        or not now < expires <= now + timedelta(hours=1)
    ):
        raise ValueError("MANUAL_RECOVERY_PLAN_EXPIRED")
    original, original_value = private_json(folder / (prefix + "-status.json"))
    fact, diag = private_json(folder / (prefix + "-diagnostic-fact.json"))
    receipt, result = private_json(folder / (prefix + "-diagnostic-result.json"))
    if any(
        sha256(raw).hexdigest() != plan[key]
        for raw, key in (
            (original, "failed_status_sha256"),
            (fact, "diagnostic_fact_sha256"),
            (receipt, "diagnostic_result_sha256"),
        )
    ) or (
        original_value.get("stage") != "NATIVE_ACCOUNT_PREFLIGHT"
        or original_value.get("native_released") is not True
        or original_value.get("broker_roundtrip_passed") is not False
        or any(
            v.get("test_id") != test_id
            or v.get("orders_sent") != 0
            or v.get("settlement_confirmations") != 0
            or v.get("status") != "READ_ONLY_SNAPSHOT_VERIFIED"
            or v.get("flat_observed") is not True
            or v.get("source_id") != plan["native_source_id"]
            for v in (diag, result)
        )
        or result.get("fact_sha256") != plan["diagnostic_fact_sha256"]
        or any(
            result.get(k) is not True
            for k in (
                "native_released",
                "original_files_unchanged",
                "fact_retained_before_release",
                "cleanup_budget_met",
            )
        )
        or result.get("evidence_close_failed") is True
    ):
        raise ValueError("MANUAL_RECOVERY_FACT_BINDING_INVALID")
    _, first = private_json(folder / (prefix + "-login.json"))
    _, second = private_json(folder / (prefix + "-diagnostic-login.json"))
    if (
        any(
            v.get("test_id") != test_id
            or v.get("account_id") != account_id
            or v.get("max_connections") != 1
            for v in (first, second)
        )
        or first.get("connections") != 1
        or second.get("cumulative_manual_connections_after_claim") != 2
    ):
        raise ValueError("MANUAL_RECOVERY_BUDGET_BINDING_INVALID")
    if set(plan["preimages"]) != {
        "account.sqlite",
        "dispatch.sqlite",
        "signals.sqlite",
    }:
        raise ValueError("MANUAL_RECOVERY_PREIMAGE_INVALID")
    for name, expected in plan["preimages"].items():
        path = folder / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("MANUAL_RECOVERY_PREIMAGE_DRIFT")
    state = a.LocalStore.inspect(folder / "account.sqlite")
    if (
        state.account_id != account_id
        or state.orders
        or state.fills
        or state.positions
        or any(type(item.command) is a.ManualBeginV1 for item in state.audit)
    ):
        raise ValueError("MANUAL_RECOVERY_NO_ORDER_PROOF_REQUIRED")
    evidence_path = folder / "native-evidence.sqlite"
    if evidence_path.is_symlink() or not evidence_path.is_file():
        raise ValueError("MANUAL_RECOVERY_SOURCE_REQUIRED")
    conn = sqlite3.connect(evidence_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if conn.execute("SELECT account FROM owner").fetchall() != [(account_id,)]:
            raise ValueError("MANUAL_RECOVERY_SOURCE_REQUIRED")
        row = conn.execute(
            "SELECT payload FROM snapshots WHERE source=?", (plan["native_source_id"],)
        ).fetchone()
        if row is None:
            raise ValueError("MANUAL_RECOVERY_SOURCE_REQUIRED")
        snapshot = Evidence._decode(row[0])
        if (
            snapshot.account_id != account_id
            or snapshot.source_id != plan["native_source_id"]
            or snapshot.trading_day != trading_day
            or snapshot.source_id
            != "ctp-inventory:"
            + snapshot.trading_day
            + ":"
            + native_hash(
                (
                    account_id,
                    snapshot.trading_day,
                    snapshot.data,
                    snapshot.at.isoformat(),
                )
            )
            or snapshot.started_at > snapshot.at
            or not timedelta(0) <= now - snapshot.at <= timedelta(minutes=20)
        ):
            raise ValueError("MANUAL_RECOVERY_SOURCE_EXPIRED")
    finally:
        conn.close()
    fd = os.open(
        folder / (prefix + "-recovery-login.json"),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as stream:
        json.dump(
            dict(
                schema=plan["schema"],
                test_id=test_id,
                account_id=account_id,
                at=now.isoformat(),
                cumulative_manual_connections=3,
                max_total_connections=3,
                max_connections=1,
                diagnostic_fact_sha256=plan["diagnostic_fact_sha256"],
            ),
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
