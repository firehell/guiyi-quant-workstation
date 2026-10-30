"""Ordinary budget takeover; local private fixtures only, no broker operations."""

from datetime import datetime, UTC, timedelta
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from guiyi_quant.simnow_execution import ordinary_takeover as ordinary
from guiyi_quant.simnow_execution.account_binding import existing_account
from guiyi_quant.htdy_account_execution.codec import digest
from guiyi_quant.simnow_execution.inbox import SignalInbox
from test_settings import existing_v2, write


@pytest.fixture
def granted(tmp_path, monkeypatch):
    config, value, folder = existing_v2(tmp_path)
    out = tmp_path / "ordinary-intent"
    out.mkdir(mode=0o700)
    path = out / ordinary.NAME
    state = existing_account(Path(value["state_root"]), value["account_id"])
    profile = dict(
        profile_id="original_anchor_v1",
        account_id=state.account_id,
        initial_readback_sha256=digest(state.initial_readback),
    )
    value.update(
        ordinary_takeover_permit=str(path),
        account_takeover_pending=True,
        account_profile=profile,
        enabled=True,
    )
    write(config, value)
    s = NS(**value)
    s.source_config_path = config
    import hashlib

    s.source_config_sha256 = hashlib.sha256(config.read_bytes()).hexdigest()
    for k in (
        "state_root",
        "project_root",
        "sdk_python",
        "api_env",
        "ordinary_takeover_permit",
    ):
        setattr(s, k, Path(getattr(s, k)))
    monkeypatch.setattr(
        ordinary,
        "release_identity",
        lambda _: dict(root=str(s.project_root), tag="v1.16.40", commit="a" * 40),
    )
    now = datetime(2026, 10, 30, 8, tzinfo=UTC)
    session = datetime(2026, 10, 30, 13, tzinfo=UTC)
    window = dict(
        policy=ordinary.POLICY,
        trading_day="20261102",
        session_start=session.isoformat(),
        connect_after=(session - timedelta(seconds=120)).isoformat(),
        connect_until=(session + timedelta(seconds=120)).isoformat(),
        sessions=[
            dict(
                start=session.isoformat(),
                end=(session + timedelta(hours=2)).isoformat(),
            )
        ],
        session_facts_sha256="c" * 64,
    )
    frozen = ordinary.binding(s, config, window, now)
    anchor = ordinary.account_anchor(s)
    intent = out / "switch-intent.private.json"
    record = dict(
        schema=ordinary.INTENT_SCHEMA,
        window_policy=ordinary.POLICY,
        stage="INSTALLED",
        plan_hash="b" * 64,
        snapshot=dict(ordinary_permit=frozen, connection_anchor=anchor),
    )
    intent.write_text(json.dumps(record))
    intent.chmod(0o600)
    sha = ordinary.issue(s, frozen, "b" * 64, intent, now, clock=lambda: now)
    record.update(stage="START_REQUESTED", ordinary_grant_sha256=sha)
    intent.write_text(json.dumps(record))
    inbox = SignalInbox(folder / "signals.sqlite", s.account_id, ("RB",))
    yield s, inbox, now, session, intent, record, frozen
    inbox.close()


def test_ordinary_three_attempts_use_original_budget_without_touching_old_day(granted):
    s, i, now, start, path, r, f = granted
    i.conn.execute("INSERT INTO attempts VALUES (?,?)", ("20261030", 3))
    # Grant freezes all original budget rows; modifying them after grant is rejected.
    with pytest.raises(ValueError):
        ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)


def test_same_run_retries_consume_normal_cap_and_restart_never_reuses(granted):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    for count in (1, 2, 3):
        n, window = ordinary.consume(
            s,
            i,
            "1" * 32,
            "20261102",
            start,
            clock=lambda: start,
            authority=lambda: f["window"],
        )
        assert n == count and window[0] <= start < window[1]
    with pytest.raises(ValueError):
        ordinary.consume(
            s,
            i,
            "1" * 32,
            "20261102",
            start,
            clock=lambda: start,
            authority=lambda: f["window"],
        )
    with pytest.raises(ValueError):
        ordinary.activate(
            s, i, "2" * 32, start, clock=lambda: start, authority=lambda: f["window"]
        )
    assert i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261102",)
    ).fetchone() == (3,)


@pytest.mark.parametrize("case", ["block", "config", "anchor", "expiry", "wrong_day"])
def test_binding_and_budget_drift_never_reaches_connection(granted, case):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    when = start
    day = "20261102"
    if case == "block":
        i.block(day, "UNPROVEN")
    if case == "config":
        s.source_config_path.write_text(s.source_config_path.read_text() + " ")
    if case == "anchor":
        (s.state_root / s.account_id / "account.sqlite").write_bytes(b"corrupt")
    if case == "expiry":
        when = start + timedelta(seconds=121)
    if case == "wrong_day":
        day = "20261103"
    with pytest.raises(ValueError):
        ordinary.consume(
            s, i, "1" * 32, day, when, clock=lambda: when, authority=lambda: f["window"]
        )
    assert (
        i.conn.execute(
            "SELECT count FROM attempts WHERE day=?", ("20261102",)
        ).fetchone()
        is None
    )


def test_unknown_sql_commit_leaves_claim_spent(granted, monkeypatch):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    monkeypatch.setattr(
        i, "attempt", lambda _: (_ for _ in ()).throw(RuntimeError("unknown"))
    )
    with pytest.raises(ValueError):
        ordinary.consume(
            s,
            i,
            "1" * 32,
            "20261102",
            start,
            clock=lambda: start,
            authority=lambda: f["window"],
        )
    with pytest.raises(ValueError):
        ordinary.consume(
            s,
            i,
            "1" * 32,
            "20261102",
            start,
            clock=lambda: start,
            authority=lambda: f["window"],
        )


def test_later_authoritative_day_retires_only_completed_first_run(granted):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    r.update(stage="COMPLETE", pid=__import__("os").getpid(), run_id="1" * 32)
    path.write_text(json.dumps(r))
    assert ordinary.permit_required(s, "20261102") is True
    assert ordinary.permit_required(s, "20261103") is False
    assert (
        i.conn.execute(
            "SELECT count FROM attempts WHERE day=?", ("20261103",)
        ).fetchone()
        is None
    )


@pytest.mark.parametrize("stage", ["START_REQUESTED", "VERIFYING", "UNKNOWN"])
def test_expiry_never_retires_unknown_deployment(granted, stage):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    r["stage"] = stage
    path.write_text(json.dumps(r))
    with pytest.raises(ValueError):
        ordinary.permit_required(s, "20261103")


def test_retry_after_first_window_uses_same_frozen_session_and_base_cap(granted):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    ordinary.consume(
        s,
        i,
        "1" * 32,
        "20261102",
        start,
        clock=lambda: start,
        authority=lambda: f["window"],
    )
    retry = start + timedelta(minutes=20)
    n, window = ordinary.consume(
        s,
        i,
        "1" * 32,
        "20261102",
        retry,
        clock=lambda: retry,
        authority=lambda: f["window"],
    )
    assert n == 2
    ordinary.validate_connection(window, retry, lambda: f["window"])
    altered = {**f["window"], "session_facts_sha256": "d" * 64}
    with pytest.raises(ValueError):
        ordinary.validate_connection(window, retry, lambda: altered)


def test_initial_first_run_cannot_be_reused_at_night_on_same_authoritative_day(granted):
    s, i, now, start, path, r, f = granted
    ordinary.activate(s, i, "1" * 32, now, clock=lambda: now)
    r.update(stage="COMPLETE", pid=__import__("os").getpid(), run_id="1" * 32)
    path.write_text(json.dumps(r))
    assert ordinary.permit_required(s, "20261102") is True
    with pytest.raises(ValueError):
        ordinary.activate(
            s,
            i,
            "2" * 32,
            start + timedelta(days=1),
            clock=lambda: start + timedelta(days=1),
        )


def test_v1_grant_readable_but_never_activated(granted):
    s, inbox, now, _, _, _, _ = granted
    path = s.ordinary_takeover_permit
    grant, _ = ordinary.read(path)
    grant["schema"] = "simnow_ordinary_takeover_v1"
    path.write_text(json.dumps(grant))
    before = path.read_bytes()
    assert ordinary.read(path)[0]["schema"] == "simnow_ordinary_takeover_v1"
    with pytest.raises(ValueError, match="ORDINARY_TAKEOVER_INVALID"):
        ordinary.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".run-claim").exists()
    assert inbox.conn.execute("SELECT * FROM attempts").fetchall() == []
