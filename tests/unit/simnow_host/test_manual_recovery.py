"""A final pre-opening connection cannot reset the failed run or its budget."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3

import pytest

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.inventory import Snapshot, native_hash
from guiyi_quant.simnow_execution.manual_recovery import claim_recovery

T = datetime(2026, 10, 27, 5, 40, tzinfo=UTC)
ID = "manual:1eea688e-3c2d-4091-828a-216a6368b9bf"
PREFIX = ID.replace(":", "-")


def save(folder, suffix, value):
    path = folder / (PREFIX + suffix)
    path.write_text(json.dumps(value, sort_keys=True))
    path.chmod(0o600)
    return sha256(path.read_bytes()).hexdigest()


def fixture(folder):
    account = "a" * 64
    rb = a.Readback(
        h.AccountSnapshot(account, T, Decimal(100000), Decimal(100000)),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        (),
        (),
        "native-baseline",
        T + timedelta(minutes=30),
        True,
    )
    store = a.LocalStore(folder / "account.sqlite", a.start(account, ("RB",), T, rb))
    store.close()
    for name in ("dispatch.sqlite", "signals.sqlite"):
        (folder / name).write_bytes(b"unchanged fixture")
        (folder / name).chmod(0o600)
    evidence = Evidence(folder / "native-evidence.sqlite", account)
    payload = {"funds": [], "positions": [], "orders": [], "trades": []}
    source = "ctp-inventory:20261027:" + native_hash(
        (account, "20261027", payload, T.isoformat())
    )
    evidence.append(Snapshot(account, "20261027", T, T, source, json.dumps(payload)))
    evidence.close()
    original = {
        "stage": "NATIVE_ACCOUNT_PREFLIGHT",
        "native_released": True,
        "broker_roundtrip_passed": False,
    }
    diag = dict(
        test_id=ID,
        status="READ_ONLY_SNAPSHOT_VERIFIED",
        orders_sent=0,
        settlement_confirmations=0,
        source_id=source,
        flat_observed=True,
    )
    fact_hash = save(folder, "-diagnostic-fact.json", diag)
    result = dict(
        diag,
        fact_sha256=fact_hash,
        native_released=True,
        original_files_unchanged=True,
        fact_retained_before_release=True,
        cleanup_budget_met=True,
    )
    plan = dict(
        schema="simnow_manual_preflight_recovery_v1",
        test_id=ID,
        account_id=account,
        expires_at=(T + timedelta(minutes=40)).isoformat(),
        preimages={
            name: sha256((folder / name).read_bytes()).hexdigest()
            for name in ("account.sqlite", "dispatch.sqlite", "signals.sqlite")
        },
        failed_status_sha256=save(folder, "-status.json", original),
        diagnostic_fact_sha256=fact_hash,
        diagnostic_result_sha256=save(folder, "-diagnostic-result.json", result),
        native_source_id=source,
        max_total_connections=3,
        initial_funds_timeout=45,
    )
    save(
        folder,
        "-login.json",
        dict(test_id=ID, account_id=account, max_connections=1, connections=1),
    )
    save(
        folder,
        "-diagnostic-login.json",
        dict(
            test_id=ID,
            account_id=account,
            max_connections=1,
            cumulative_manual_connections_after_claim=2,
        ),
    )
    save(folder, "-recovery-plan.json", plan)
    return account, plan


def test_last_recovery_claim_preserves_all_original_facts_and_is_once(tmp_path):
    account, _ = fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    claim_recovery(
        tmp_path, ID, account, T + timedelta(minutes=1), trading_day="20261027"
    )
    assert all(
        (tmp_path / name).read_bytes() == value for name, value in before.items()
    )
    with pytest.raises(FileExistsError):
        claim_recovery(
            tmp_path, ID, account, T + timedelta(minutes=1), trading_day="20261027"
        )
    claim = json.loads((tmp_path / (PREFIX + "-recovery-login.json")).read_text())
    assert claim["cumulative_manual_connections"] == claim["max_total_connections"] == 3


@pytest.mark.parametrize(
    "bad",
    [
        "hash",
        "expired",
        "source_old",
        "account",
        "budget",
        "release",
        "missing_fact",
        "source_payload",
        "wrong_day",
    ],
)
def test_recovery_requires_unchanged_empty_account_and_bound_diagnostic(tmp_path, bad):
    account, plan = fixture(tmp_path)
    now = T + timedelta(minutes=1)
    day = "20261027"
    if bad == "hash":
        (tmp_path / "dispatch.sqlite").write_bytes(b"drift")
    elif bad == "expired":
        plan["expires_at"] = T.isoformat()
    elif bad == "source_old":
        now = T + timedelta(minutes=21)
    elif bad == "account":
        plan["account_id"] = "b" * 64
    elif bad == "budget":
        save(
            tmp_path,
            "-diagnostic-login.json",
            dict(
                test_id=ID,
                account_id=account,
                max_connections=1,
                cumulative_manual_connections_after_claim=3,
            ),
        )
    elif bad == "release":
        receipt = json.loads(
            (tmp_path / (PREFIX + "-diagnostic-result.json")).read_text()
        )
        receipt["native_released"] = False
        plan["diagnostic_result_sha256"] = save(
            tmp_path, "-diagnostic-result.json", receipt
        )
    elif bad == "source_payload":
        conn = sqlite3.connect(tmp_path / "native-evidence.sqlite")
        raw = conn.execute("SELECT payload FROM snapshots").fetchone()[0]
        value = json.loads(raw)
        value["payload_json"] = '{"tampered":true}'
        conn.execute("DROP TRIGGER no_update")
        conn.execute("UPDATE snapshots SET payload=?", (json.dumps(value),))
        conn.commit()
        conn.close()
    elif bad == "wrong_day":
        day = "20261028"
    else:
        (tmp_path / (PREFIX + "-diagnostic-fact.json")).unlink()
    save(tmp_path, "-recovery-plan.json", plan)
    with pytest.raises((ValueError, FileNotFoundError)):
        claim_recovery(tmp_path, ID, account, now, trading_day=day)
    assert not (tmp_path / (PREFIX + "-recovery-login.json")).exists()


def test_recovery_status_never_overwrites_original_failed_bytes(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "manual_status_writer",
        Path(__file__).parents[3] / "scripts/broker/simnow_manual_roundtrip.py",
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    old = b'{"failed":true}'
    (tmp_path / (PREFIX + "-status.json")).write_bytes(old)
    assert runner.write_status(tmp_path, ID, dict(stage="RECOVERING"), recovery=True)
    assert (tmp_path / (PREFIX + "-status.json")).read_bytes() == old
    assert (tmp_path / (PREFIX + "-recovery-status.json")).is_file()
