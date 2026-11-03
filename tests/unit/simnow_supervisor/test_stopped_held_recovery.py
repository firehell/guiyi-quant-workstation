"""Actual MacBackend recovery views over real temporary configs, SQLite and backups."""

from copy import copy, deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace as NS

import pytest

from guiyi_quant.simnow_execution import ordinary_takeover as ordinary
from test_held_readonly_handoff import held_failure as held_failure, write, RUN, SOURCE
from test_trade_switch import m


@pytest.fixture
def recovery(held_failure, tmp_path, monkeypatch):
    f = held_failure
    b = f.b
    old_cfg = json.loads(b.old_config.read_bytes())
    old_cfg.update(state_project_root=str(f.root), api_env=str(tmp_path / "api-env"))
    write(b.old_config, old_cfg)
    f.preimage["old_config"] = b.identity(b.old_config)
    b.code = tmp_path / "release-v1.16.72"
    (b.code / "scripts/broker").mkdir(parents=True)
    (b.code / "scripts/broker/simnow_supervisor.py").write_text("fixture candidate\n")
    b.tag, b.exact = "v1.16.72", "e" * 40
    first_dir, fresh_dir = tmp_path / "first-attempt", tmp_path / "recovery-attempt"
    first_dir.mkdir(mode=0o700)
    fresh_dir.mkdir(mode=0o700)
    target = dict(
        old_cfg,
        project_root=str(b.code),
        account_recovery_hold=False,
        ordinary_takeover_permit=str(first_dir / ordinary.NAME),
    )
    target_config = first_dir / "candidate.private.json"
    write(target_config, target)
    fresh = dict(target, ordinary_takeover_permit=str(fresh_dir / ordinary.NAME))
    b.config = fresh_dir / "candidate.private.json"
    write(b.config, fresh)
    b.cfg = fresh
    b.settings = NS(
        **{
            **fresh,
            "state_root": f.root,
            "state_project_root": f.root,
            "project_root": b.code,
            "sdk_python": Path(old_cfg["sdk_python"]),
            "api_env": tmp_path / "api-env",
            "ordinary_takeover_permit": fresh_dir / ordinary.NAME,
            "source_config_path": b.config,
            "source_config_sha256": hashlib.sha256(b.config.read_bytes()).hexdigest(),
        }
    )
    b.monitor, b.plist = (
        tmp_path / "installed-monitor.private.json",
        tmp_path / "installed.plist",
    )
    b.candidate_plist = fresh_dir / "candidate.plist"

    def plist(config, project):
        return plistlib.dumps(
            dict(
                Label=m.LABEL,
                ProgramArguments=[
                    old_cfg["sdk_python"],
                    "-I",
                    str(project / "scripts/broker/simnow_supervisor.py"),
                    "--config",
                    str(config),
                    "--trade",
                ],
            )
        )

    b.plist.write_bytes(plist(b.old_config, Path(old_cfg["project_root"])))
    b.plist.chmod(0o600)
    b.candidate_plist.write_bytes(plist(b.config, b.code))
    b.candidate_plist.chmod(0o600)
    original_plist = first_dir / "candidate.plist"
    original_plist.write_bytes(plist(target_config, b.code))
    original_plist.chmod(0o600)
    old_monitor = {
        k: v
        for k, v in old_cfg.items()
        if k
        in {
            "schema",
            "account_id",
            "state_root",
            "state_project_root",
            "project_root",
            "sdk_python",
            "api_env",
            "mode",
            "enabled",
        }
    }
    old_monitor["mode"] = "observe"
    write(b.monitor, old_monitor)
    b.release_identity = lambda root: dict(
        root=str(root), tag="v1.16.69", commit=SOURCE
    )
    b.code_check = lambda: b.exact
    b._candidate = lambda: (b.exact, {"candidate_valid": True})
    b._label_loaded = lambda: None
    b.home = tmp_path
    b.locks = [tmp_path / "global-account.lock", f.folder / "host.lock"]
    for path in b.locks:
        path.touch(mode=0o600)
    now = datetime.now(UTC)
    start = now + timedelta(hours=1)
    f.window["sessions"] = [
        dict(start=start.isoformat(), end=(start + timedelta(hours=1)).isoformat())
    ]
    f.window.update(
        session_start=start.isoformat(),
        connect_after=(start - timedelta(seconds=120)).isoformat(),
        connect_until=(start + timedelta(seconds=120)).isoformat(),
    )
    historical = dict(
        policy="simnow_completed_contract_anchor_v1",
        trading_day="20261103",
        product_count=60,
        sha256="d" * 64,
    )
    b._historical_anchor = lambda: historical
    monkeypatch.setattr(
        ordinary,
        "release_identity",
        lambda root: dict(root=str(root), tag=b.tag, commit=b.exact),
    )
    first = copy(b)
    first.config, first.cfg, first.candidate_plist = (
        target_config,
        target,
        original_plist,
    )
    first.settings = NS(
        **{
            **vars(b.settings),
            "ordinary_takeover_permit": first_dir / ordinary.NAME,
            "source_config_path": target_config,
            "source_config_sha256": hashlib.sha256(
                target_config.read_bytes()
            ).hexdigest(),
        }
    )
    preimage = first._preimage()
    local_account = b._account()
    source_proof = b._held_readonly_source_proof(
        f.control,
        {**preimage, "host_pid": 29975, "host_run_id": RUN},
        local_account,
        f.window,
    )
    preimage.update(
        account=local_account,
        held_readonly_handoff=source_proof,
        historical_contract_anchor=historical,
        host_pid=29975,
        host_run_id=RUN,
        locks=[
            dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino)
            for p in b.locks
        ],
    )
    source = dict(
        candidate=dict(
            tag=b.tag,
            commit=b.exact,
            annotated_exact=True,
            clean=True,
            sdk_check=True,
            preflight_valid=True,
            identities=dict(preimage, code=b.exact),
        ),
        account=local_account,
        host=dict(
            label=m.LABEL,
            mode="trade",
            pid=29975,
            run_id=RUN,
            account_recovery_hold=True,
            unique=True,
            dual_locks_held_by_pid=True,
            command_identity="c" * 64,
        ),
        ordinary_permit=ordinary.binding(first.settings, target_config, f.window, now),
        connection_permit=None,
        historical_contract_anchor=historical,
        window=f.window,
        preimage=preimage,
        old_config_path=str(b.old_config),
    )
    f.control.update(status="STOPPED", at=datetime.now(UTC).isoformat())
    write(f.folder / "continuous.json", f.control)
    write(
        f.root / "monitor.json",
        dict(status="STOPPED", run_id=RUN, account_id=b.settings.account_id),
    )

    def gone(pid, sig):
        assert pid == 29975 and sig == 0
        raise ProcessLookupError()

    monkeypatch.setattr(m.os, "kill", gone)
    first._recovery = True
    return NS(
        b=b, first=first, f=f, source=source, first_dir=first_dir, fresh_dir=fresh_dir
    )


def install_state(r, stage):
    if stage == "none":
        return
    original = r.first._replace
    if stage == "partial":

        def partial(path, raw):
            original(path, raw)
            if path == r.first.plist:
                raise RuntimeError("fixture power loss")

        r.first._replace = partial
        with pytest.raises(RuntimeError):
            r.first.install(r.source)
    else:
        assert r.first.install(r.source) is True


@pytest.mark.parametrize("stage", ["none", "installed", "partial"])
@pytest.mark.parametrize(
    "readonly", [True, False], ids=["readonly-failure", "healthy-held"]
)
def test_real_backend_recovers_original_source_view_and_rechecks_finish(
    recovery, stage, readonly
):
    r = recovery
    if not readonly:
        r.f.failure.unlink()
        r.source["preimage"].pop("held_readonly_handoff")
        r.source["candidate"]["identities"].pop("held_readonly_handoff")
        r.b.recover_held_readonly_source = False
    install_state(r, stage)
    source_bytes = json.dumps(r.source, sort_keys=True)
    fresh = r.b.recovery_snapshot(r.source)
    m.validate_snapshot(fresh)
    assert fresh["preimage"]["old_release"] == r.source["preimage"]["old_release"]
    assert fresh["preimage"]["old_config"] == r.source["preimage"]["old_config"]
    assert bool(fresh["preimage"].get("held_readonly_handoff")) is readonly
    anchor = fresh["preimage"]["recovery_source_anchor"]
    assert anchor["source_preimage_sha256"] == m.digest(r.source["preimage"])
    assert (
        anchor["files"]["old_config"]["read_from"]["path"]
        == r.source["old_config_path"]
    )
    if stage != "none":
        for key in ("old_plist", "monitor"):
            assert (
                anchor["files"][key]["backup"]["identity"]["inode"]
                != r.source["preimage"][key]["inode"]
            )
    with r.b.offline_guard(fresh):
        verified = r.b.offline_preflight(fresh)
        assert verified["writer_idle"] is verified["protected_state_unchanged"] is True
        assert verified["preimage"] == fresh["preimage"]
    assert json.dumps(r.source, sort_keys=True) == source_bytes


@pytest.mark.parametrize(
    "change",
    [
        "old_config",
        "old_config_inode",
        "bad_backup",
        "missing_backup",
        "foreign_installed",
        "source_grant",
        "source_run_claim",
        "source_attempt",
        "new_grant",
        "missing_flag",
        "new_failure",
    ],
)
def test_real_backend_rejects_unsafe_stopped_recovery(recovery, change):
    r = recovery
    install_state(r, "installed")
    suffix = ".ordinary-" + r.source["preimage"]["config"]["sha256"][:16] + ".preimage"
    if change == "old_config":
        r.b.old_config.write_text(r.b.old_config.read_text() + " ")
    if change == "old_config_inode":
        replacement = r.b.old_config.with_name("same-bytes-new-inode.private.json")
        replacement.write_bytes(r.b.old_config.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(r.b.old_config)
    if change == "bad_backup":
        r.b.plist.with_name(r.b.plist.name + suffix).write_bytes(b"corrupt")
    if change == "missing_backup":
        r.b.plist.with_name(r.b.plist.name + suffix).unlink()
    if change == "foreign_installed":
        r.b.plist.write_bytes(b"unknown")
    if change == "source_grant":
        write(Path(r.source["ordinary_permit"]["permit_path"]), {})
    if change == "source_run_claim":
        write(Path(r.source["ordinary_permit"]["permit_path"] + ".run-claim"), {})
    if change == "source_attempt":
        Path(
            r.source["ordinary_permit"]["permit_path"] + ".attempt-1.claim"
        ).symlink_to(r.first_dir / "missing")
    if change == "new_grant":
        write(r.b.settings.ordinary_takeover_permit, {})
    if change == "missing_flag":
        r.b.recover_held_readonly_source = False
    if change == "new_failure":
        write(r.f.folder / ("failure-" + RUN + "-999.json"), {})
    with pytest.raises(m.SwitchError):
        r.b.recovery_snapshot(r.source)


def test_every_virtual_preimage_rechecks_actual_installed_state(recovery):
    r = recovery
    install_state(r, "installed")
    fresh = r.b.recovery_snapshot(r.source)
    r.b.monitor.write_bytes(b"foreign monitor")
    with r.b.offline_guard(fresh):
        with pytest.raises(m.SwitchError):
            r.b.offline_preflight(fresh)


def test_partial_backup_before_any_install_can_recover_only_unchanged_originals(
    recovery, monkeypatch
):
    r = recovery
    suffix = ".ordinary-" + r.source["preimage"]["config"]["sha256"][:16] + ".preimage"
    target = r.b.monitor.with_name(r.b.monitor.name + suffix)
    original_open = m.os.open

    def interrupted(path, *args, **kwargs):
        if Path(path) == target:
            raise PermissionError("fixture backup interrupted")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as partial:
        partial.setattr(m.os, "open", interrupted)
        with pytest.raises(PermissionError):
            r.first.install(r.source)
    assert r.b.plist.with_name(r.b.plist.name + suffix).is_file()
    assert not target.exists()
    fresh = r.b.recovery_snapshot(r.source)
    with r.b.offline_guard(fresh):
        assert r.b.offline_preflight(fresh)["protected_state_unchanged"] is True


def test_unchanged_old_config_cannot_mask_a_corrupt_preservation_backup(recovery):
    r = recovery
    install_state(r, "installed")
    suffix = ".ordinary-" + r.source["preimage"]["config"]["sha256"][:16] + ".preimage"
    r.b.old_config.with_name(r.b.old_config.name + suffix).write_bytes(b"corrupt")
    assert r.b.identity(r.b.old_config) == r.source["preimage"]["old_config"]
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        r.b.recovery_snapshot(r.source)


def test_backup_same_bytes_new_inode_invalidates_the_planned_physical_anchor(recovery):
    r = recovery
    install_state(r, "installed")
    fresh = r.b.recovery_snapshot(r.source)
    physical = fresh["preimage"]["recovery_source_anchor"]["files"]["old_plist"][
        "backup"
    ]
    path = Path(physical["path"])
    replacement = path.with_name("replacement.private")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)
    assert r.b.identity(path)["sha256"] == physical["identity"]["sha256"]
    assert path.stat().st_ino != physical["identity"]["inode"]
    with r.b.offline_guard(fresh):
        assert r.b.offline_preflight(fresh)["protected_state_unchanged"] is False


@pytest.mark.parametrize(
    "marker",
    ["grant", "run-claim", "attempt-1.claim", "recovery-claim", "START_REQUESTED"],
)
def test_real_backend_coordinator_refuses_any_spent_or_unknown_start_source(
    recovery, marker
):
    r = recovery
    source_intent = r.first_dir / "switch-intent.private.json"
    record = dict(
        schema=m.SCHEMA,
        stage="INSTALLED",
        result="UNKNOWN",
        snapshot=deepcopy(r.source),
    )
    if marker == "START_REQUESTED":
        record["stage"] = marker
    write(source_intent, record)
    (r.first_dir / "switch.lock").touch(mode=0o600)
    if marker == "recovery-claim":
        write(r.first_dir / "pending-trade-recovery-claim.private.json", {})
    elif marker != "START_REQUESTED":
        grant = Path(r.source["ordinary_permit"]["permit_path"])
        write(
            grant if marker == "grant" else grant.with_name(grant.name + "." + marker),
            {},
        )
    before = source_intent.read_bytes()
    coordinator = m.Coordinator(r.b, r.fresh_dir)
    with pytest.raises(m.SwitchError):
        coordinator.plan_recovery(source_intent)
    assert source_intent.read_bytes() == before
    assert not (r.fresh_dir / "switch-intent.private.json").exists()
    assert not r.b.settings.ordinary_takeover_permit.exists()


@pytest.mark.parametrize("flag", ["enable_auto_order", "recover_held_readonly_source"])
def test_real_backend_coordinator_cannot_omit_either_explicit_flag(recovery, flag):
    r = recovery
    source_intent = r.first_dir / "switch-intent.private.json"
    write(
        source_intent,
        dict(schema=m.SCHEMA, stage="STOPPED", result="UNKNOWN", snapshot=r.source),
    )
    (r.first_dir / "switch.lock").touch(mode=0o600)
    setattr(r.b, flag, False)
    coordinator = m.Coordinator(r.b, r.fresh_dir)
    with pytest.raises(m.SwitchError):
        coordinator.plan_recovery(source_intent)
    assert not (r.first_dir / "pending-trade-recovery-claim.private.json").exists()
    assert not (r.fresh_dir / "ordinary-recovery-intent.private.json").exists()


def test_actual_backend_coordinator_finishes_stopped_handoff_without_rewriting_unknown(
    recovery,
):
    r = recovery
    install_state(r, "installed")
    source_intent = r.first_dir / "switch-intent.private.json"
    write(
        source_intent,
        dict(schema=m.SCHEMA, stage="INSTALLED", result="UNKNOWN", snapshot=r.source),
    )
    (r.first_dir / "switch.lock").touch(mode=0o600)
    original = source_intent.read_bytes()
    starts = []
    r.b.window_open = lambda: True
    r.b.start = lambda snapshot: starts.append("start-provider") or True
    r.b.readback = lambda snapshot: dict(
        verified=True,
        mode="trade",
        pid=29976,
        run_id="b" * 32,
        dual_locks_held_by_pid=True,
        config_bound=True,
        monitor_bound=True,
        account_takeover_pending=True,
        account_recovery_hold=False,
        auto_order=True,
        opening_enabled=False,
    )
    coordinator = m.Coordinator(r.b, r.fresh_dir, sleep=lambda _: None)
    plan = coordinator.plan_recovery(source_intent)
    result = coordinator.recover_pending_trade(plan)
    assert result["stage"] == "COMPLETE"
    assert result["result"] == "HOST_SWITCH_VERIFIED"
    assert result["native_recovery_complete"] is False
    assert starts == ["start-provider"]
    assert source_intent.read_bytes() == original
    assert json.loads(source_intent.read_bytes())["result"] == "UNKNOWN"
    assert not Path(r.source["ordinary_permit"]["permit_path"]).exists()
    assert r.b.settings.ordinary_takeover_permit.is_file()
    assert r.b.plist.read_bytes() == r.b.candidate_plist.read_bytes()
    with pytest.raises(m.SwitchError, match="ATTEMPT_CONSUMED"):
        coordinator.recover_pending_trade(plan)
