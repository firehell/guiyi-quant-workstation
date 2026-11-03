"""Ordinary migration preserves held accounts; only local Git/files/fixtures."""

from datetime import datetime, timedelta
from test_ordinary_takeover import granted as granted
from guiyi_quant.simnow_execution import ordinary_takeover as ordinary
from guiyi_quant.simnow_execution import native_portfolio as native
from guiyi_quant.simnow_execution.supervisor import Supervisor

import json
import plistlib
import subprocess
from types import SimpleNamespace as NS
import pytest
from test_trade_switch import m, setup as setup


def git(root, *args):
    return subprocess.check_output(
        [
            "/usr/bin/git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-C",
            str(root),
            *args,
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


@pytest.fixture
def release(tmp_path):
    root = tmp_path / "managed" / "guiyi-quant-workstation"
    root.mkdir(parents=True)
    git(root, "init", "-q")
    (root / "source.txt").write_text("fixed source\n")
    git(root, "add", "source.txt")
    git(root, "commit", "-qm", "fixture")
    git(root, "tag", "-a", "v1.16.69", "-m", "fixture")
    git(root, "checkout", "--detach", "-q", "v1.16.69")
    return root


def test_old_managed_root_uses_annotated_exact_tag_not_directory_name(release):
    b = m.MacBackend.__new__(m.MacBackend)
    assert b.release_identity(release) == dict(
        root=str(release), tag="v1.16.69", commit=git(release, "rev-parse", "HEAD")
    )


@pytest.mark.parametrize(
    "change", ["dirty", "untracked", "lightweight", "attached", "symlink"]
)
def test_release_identity_still_rejects_unproven_source(release, change):
    path = release
    if change == "dirty":
        (release / "source.txt").write_text("changed")
    elif change == "untracked":
        (release / "extra.txt").write_text("extra")
    elif change == "lightweight":
        git(release, "tag", "-d", "v1.16.69")
        git(release, "tag", "v1.16.69")
    elif change == "attached":
        git(release, "checkout", "-qb", "working")
    else:
        path = release.parent / "alias"
        path.symlink_to(release, target_is_directory=True)
    with pytest.raises(m.SwitchError, match="CANDIDATE_UNPROVEN"):
        m.MacBackend.__new__(m.MacBackend).release_identity(path)


@pytest.fixture
def held_preimage(tmp_path):
    tmp_path.chmod(0o700)
    b = m.MacBackend.__new__(m.MacBackend)
    b.folder = tmp_path
    b.code = tmp_path / "release-v1.16.69"
    b.tag, b.exact = "v1.16.69", "a" * 40
    b.ordinary = True
    b.config, b.old_config = tmp_path / "new.json", tmp_path / "old.json"
    b.plist, b.candidate_plist = (
        tmp_path / "installed.plist",
        tmp_path / "candidate.plist",
    )
    b.monitor = tmp_path / "monitor.json"
    base = dict(
        schema=2,
        account_id="a" * 64,
        state_root=str(tmp_path),
        state_project_root=str(tmp_path),
        project_root=str(b.code),
        sdk_python=str(tmp_path / "python"),
        api_env=str(tmp_path / "api"),
        mode="trade",
        enabled=True,
        account_takeover_pending=True,
        account_recovery_hold=True,
    )
    b.cfg = dict(base)
    b.settings = NS(
        **{
            **base,
            "state_root": tmp_path,
            "state_project_root": tmp_path,
            "project_root": b.code,
            "sdk_python": tmp_path / "python",
            "api_env": tmp_path / "api",
        }
    )

    def write(path, value):
        path.write_bytes(
            value if isinstance(value, bytes) else json.dumps(value).encode()
        )
        path.chmod(0o600)

    write(b.old_config, base)
    write(b.config, base)
    write(
        b.plist,
        plistlib.dumps(
            dict(
                Label=m.LABEL,
                ProgramArguments=["python", "--config", str(b.old_config), "--trade"],
            )
        ),
    )
    write(b.candidate_plist, b"candidate")
    write(b.monitor, {**base, "mode": "observe"})
    b.identity = lambda *args, **kwargs: {"sha256": "b" * 64}
    b.release_identity = lambda root: dict(root=str(root), tag=b.tag, commit=b.exact)
    return b


def test_migration_rejects_candidate_that_drops_original_hold(held_preimage):
    b = held_preimage
    b.cfg["account_recovery_hold"] = False
    b.settings.account_recovery_hold = False
    b.config.write_text(json.dumps(b.cfg))
    with pytest.raises(m.SwitchError, match="CANDIDATE_UNPROVEN"):
        b._preimage()


def test_same_held_candidate_retains_preimage_contract(held_preimage):
    b = held_preimage
    assert b._preimage()["old_config"] == {"sha256": "b" * 64}


def test_switch_receipt_cannot_claim_held_migration_when_new_host_hold_is_off(setup):
    b, c, _ = setup
    b.value["account"]["account_recovery_hold"] = True
    original = b.readback
    b.readback = lambda snapshot: {
        **original(snapshot),
        "account_recovery_hold": False,
        "auto_order": True,
    }
    with pytest.raises(m.SwitchError, match="READBACK_UNPROVEN"):
        c.apply(c.plan())
    assert json.loads(c.intent.read_bytes())["result"] == "UNKNOWN"


@pytest.mark.parametrize("elapsed", [1, 61])
def test_actual_stop_resamples_expiry_after_slow_prechecks(
    tmp_path, monkeypatch, elapsed
):
    b = m.MacBackend.__new__(m.MacBackend)
    b.old_config = tmp_path / "old.json"
    b.folder = tmp_path
    b._stop_signals = b._stop_historical_anchor = "same"
    b._prove = lambda *args: None
    b.identity = lambda *args: "same"
    clock = NS(at=1000)

    def slow_authority():
        clock.at += elapsed
        return "same"

    b._historical_anchor = slow_authority
    signals = []
    monkeypatch.setattr(m.os, "kill", lambda *args: signals.append(args))
    if elapsed > 60:
        with pytest.raises(m.SwitchError, match="PLAN_EXPIRED"):
            b.stop(12345, expires_at=1060, clock=lambda: clock.at)
        assert signals == []
    else:
        b.stop(12345, expires_at=1060, clock=lambda: clock.at)
        assert signals == [(12345, m.signal.SIGTERM)]


def host(s, inbox, factory, at, day, window):
    clock = NS(at=at)
    market = NS(
        issues={},
        plan=lambda now: NS(
            active=True,
            connect_allowed=True,
            trading_day=datetime.strptime(day, "%Y%m%d").date(),
        ),
        ordinary_takeover_window=lambda *args: window,
    )
    sup = Supervisor(s, ("RB",), market, factory, clock=lambda: clock.at)
    sup.run_id = "1" * 32
    sup.folder = s.state_root / s.account_id
    sup.inbox = inbox
    sup.monitor = NS(publish=lambda *args, **kwargs: None)
    return sup, clock


@pytest.mark.parametrize("granted", [None, "held"], indirect=True)
@pytest.mark.parametrize("missing_setter", [True, False])
def test_active_ordinary_window_blocks_missing_hook_or_slow_keychain(
    granted, monkeypatch, missing_setter
):
    s, inbox, now, start, intent, record, frozen = granted
    ordinary.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    calls = []
    clock = NS(at=start)

    def credentials(*args):
        clock.at = start + timedelta(minutes=3)
        return NS(user="test-only-user", password="test-only-password")

    monkeypatch.setattr(native.CredentialStore, "load", credentials)
    module = NS(
        Gateway=lambda user, password: NS(user=user, password=password, api=None),
        tdapi=None,
    )

    def connector(*args):
        calls.append("connector")

    def factory(settings, folder):
        if missing_setter:
            return NS(connect=lambda: calls.append("connect"))
        return native.NativePortfolio(
            settings,
            folder,
            module,
            connector,
            now=lambda: clock.at,
            initial_funds_timeout=15,
        )

    sup, ignored = host(s, inbox, factory, start, "20261102", frozen["window"])
    sup.now = lambda: clock.at
    with pytest.raises(ValueError, match="ORDINARY_TAKEOVER_INVALID"):
        sup.connect("20261102")
    assert calls == []
    assert inbox.conn.execute(
        "SELECT count FROM attempts WHERE day='20261102'"
    ).fetchone() == (1,)
    if not missing_setter:
        assert sup.driver.stage == "PRE_NATIVE_GUARD"
        sup.driver.close()


@pytest.mark.parametrize("granted", ["held"], indirect=True)
def test_retired_ordinary_permit_does_not_block_later_normal_held_connection(
    granted, monkeypatch
):
    import os

    s, inbox, now, start, intent, record, frozen = granted
    ordinary.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    record.update(stage="COMPLETE", pid=os.getpid(), run_id="1" * 32)
    intent.write_text(json.dumps(record))
    later = start + timedelta(days=3)
    assert ordinary.permit_required(s, "20261103") is False
    calls = []

    class ReachedConnector(Exception):
        pass

    monkeypatch.setattr(
        native.CredentialStore,
        "load",
        lambda *args: NS(user="test-only-user", password="test-only-password"),
    )
    module = NS(
        Gateway=lambda user, password: NS(user=user, password=password, api=None),
        tdapi=None,
    )

    def connector(*args):
        calls.append("connector")
        raise ReachedConnector()

    def factory(settings, folder):
        return native.NativePortfolio(
            settings,
            folder,
            module,
            connector,
            now=lambda: later,
            initial_funds_timeout=15,
        )

    sup, ignored = host(s, inbox, factory, later, "20261103", {})
    with pytest.raises(ReachedConnector):
        sup.connect("20261103")
    assert calls == ["connector"]
    assert inbox.conn.execute(
        "SELECT count FROM attempts WHERE day='20261103'"
    ).fetchone() == (1,)
    sup.driver.close()


@pytest.mark.parametrize("granted", ["held"], indirect=True)
def test_new_day_budget_preserves_exhausted_old_day_and_unknown_records(
    granted, tmp_path
):
    s, inbox, now, start, intent, record, frozen = granted
    inbox.conn.execute("INSERT INTO attempts VALUES ('20261103',3)")
    inbox.block("20261103", "CONTINUOUS_RECOVERY_REQUIRED")
    unknown = tmp_path / "prior-unknown.json"
    unknown.write_text(json.dumps(dict(stage="VERIFYING", result="UNKNOWN")))
    before = tuple(inbox.conn.iterdump())
    source = unknown.read_bytes()
    budget = ordinary.budget_binding(s, "20261104")
    assert budget["initial_count"] == 0
    assert ["20261103", 3] in budget["attempts"]
    assert ["20261103", "CONTINUOUS_RECOVERY_REQUIRED"] in budget["blocks"]
    with pytest.raises(ValueError, match="ORDINARY_TAKEOVER_INVALID"):
        ordinary.budget_binding(s, "20261103")
    assert tuple(inbox.conn.iterdump()) == before and unknown.read_bytes() == source


@pytest.mark.parametrize(
    "disk_hold,live_hold,target_hold,code",
    [
        (False, True, False, "CANDIDATE_UNPROVEN"),
        (True, False, True, "HOST_UNPROVEN"),
        (False, False, True, None),
        (True, True, True, None),
    ],
)
def test_source_runtime_hold_cannot_be_lost_even_if_disk_config_disagrees(
    disk_hold, live_hold, target_hold, code
):
    b = m.MacBackend.__new__(m.MacBackend)
    b._old_recovery_hold = disk_hold
    b.settings = NS(account_recovery_hold=target_hold)
    control = dict(
        account_recovery_hold=live_hold, auto_order=False, opening_enabled=False
    )
    if code:
        with pytest.raises(m.SwitchError, match=code):
            b._source_hold(control)
    else:
        assert b._source_hold(control) is live_hold


def test_held_switch_can_verify_destination_without_claiming_native_recovery(setup):
    b, c, _ = setup
    b.value["account"]["account_recovery_hold"] = True
    original = b.readback
    b.readback = lambda snapshot: {
        **original(snapshot),
        "account_recovery_hold": True,
        "auto_order": False,
    }
    result = c.apply(c.plan())
    assert result["result"] == "HOST_SWITCH_VERIFIED"
    assert result["native_recovery_complete"] is False
