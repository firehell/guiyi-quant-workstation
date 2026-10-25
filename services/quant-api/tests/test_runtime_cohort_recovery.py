"""Pre-CAS recovery resolution never executes or erases a consumed plan."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from app import runtime_cohort as module
from app.runtime_cohort import CohortError, apply_cohort
from app.runtime_handover import _write
from tests.test_runtime_cohort import Host, plan


def recovery(tmp_path):
    host = Host(tmp_path)
    frozen = plan(host)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(frozen))
    path.chmod(0o600)
    attempt = host.directory / "cohort-attempts" / frozen["plan_sha256"]
    attempt.parent.mkdir(mode=0o700)
    attempt.mkdir(mode=0o700)
    state = {
        "schema_version": 1,
        "plan_sha256": frozen["plan_sha256"],
        "phase": "restore_unknown",
        "effects": {"prewarm": None, "calendars_off": {}, "drain": {}},
        "error_type": "CohortError",
    }
    _write(attempt / "state.json", state)
    _write(host.directory / "cohort-release.json", state)
    host.verify_old_restored = lambda _: {
        "identity_sha256": "f" * 64,
        "owners": {"market-feed": {"pid": 47191}},
    }
    return host, frozen, path, attempt, state


def test_expired_consumed_plan_can_only_be_audited_and_original_failure_remains(
    tmp_path,
):
    host, frozen, path, attempt, _ = recovery(tmp_path)
    host.now = lambda: Host.now(host) + timedelta(days=1)
    original = (attempt / "state.json").read_bytes()
    with pytest.raises(CohortError, match="PLAN_EXPIRED"):
        apply_cohort(host, frozen)
    result = module.resolve_restored_cohort(host, path)
    assert result["status"] == "cancelled"
    assert (attempt / "state.json").read_bytes() == original
    readback = json.loads((attempt / "recovery-readback.json").read_text())
    assert readback["kind"] == "precommit_restore_readback"
    assert readback["source_attempt_sha256"] == sha256(original).hexdigest()
    assert readback["source_plan_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert readback["proof"]["owners"]["market-feed"]["pid"] == 47191
    global_state = json.loads((host.directory / "cohort-release.json").read_text())
    assert global_state["phase"] == "cancelled"
    assert (
        global_state["resolution"]["receipt_sha256"]
        == sha256((attempt / "recovery-readback.json").read_bytes()).hexdigest()
    )
    assert host.calls == []
    # Only a new frozen plan is now permitted; the consumed attempt remains.
    assert plan(host)["plan_sha256"] != frozen["plan_sha256"]


@pytest.mark.parametrize(
    "phase", ["outcome_unknown", "committed", "switched", "cancelled", "old_exited"]
)
def test_resolution_never_accepts_post_cas_or_other_attempt_phases(tmp_path, phase):
    host, _, path, attempt, state = recovery(tmp_path)
    state["phase"] = phase
    _write(attempt / "state.json", state)
    _write(host.directory / "cohort-release.json", state)
    with pytest.raises(CohortError):
        module.resolve_restored_cohort(host, path)
    assert not (attempt / "recovery-readback.json").exists()


@pytest.mark.parametrize(
    "effect",
    [
        "commit",
        "committing",
        "committed",
        "consumers",
        "consumers_ready",
        "feed",
        "verified",
        "calendars_on",
    ],
)
def test_resolution_rejects_commit_or_post_commit_effects_even_if_phase_is_forged(
    tmp_path, effect
):
    host, _, path, attempt, state = recovery(tmp_path)
    state["effects"][effect] = {}
    _write(attempt / "state.json", state)
    _write(host.directory / "cohort-release.json", state)
    with pytest.raises(CohortError):
        module.resolve_restored_cohort(host, path)
    assert not (attempt / "recovery-readback.json").exists()


def test_resolution_rejects_changed_registry_before_host_audit(tmp_path):
    from app.runtime_bindings import BindingRegistry

    host, _, path, attempt, _ = recovery(tmp_path)
    changed = {
        **host.old.services,
        "api": replace(host.old.services["api"], generation=100),
    }
    host.registry = BindingRegistry(1, changed)
    host.verify_old_restored = lambda _: pytest.fail(
        "changed registry must reject before audit"
    )
    with pytest.raises(CohortError, match="REGISTRY_DRIFT"):
        module.resolve_restored_cohort(host, path)
    assert not (attempt / "recovery-readback.json").exists()


def test_resolution_drift_during_audit_does_not_rewrite_unknown_state(tmp_path):
    host, _, path, attempt, state = recovery(tmp_path)
    original = (attempt / "state.json").read_bytes()

    def drift(_):
        _write(
            host.directory / "cohort-release.json",
            {**state, "error_type": "external-change"},
        )
        return {"identity_sha256": "f" * 64}

    host.verify_old_restored = drift
    with pytest.raises(CohortError, match="SOURCE_DRIFT"):
        module.resolve_restored_cohort(host, path)
    assert (attempt / "state.json").read_bytes() == original
    assert (
        json.loads((host.directory / "cohort-release.json").read_text())["phase"]
        == "restore_unknown"
    )


def test_resolution_unknown_global_write_reads_back_once_without_replaying_write(
    tmp_path, monkeypatch
):
    host, _, path, attempt, _ = recovery(tmp_path)
    writes = []
    original = module._write

    def uncertain(target, value):
        writes.append(target)
        original(target, value)
        raise OSError("fsync result unknown")

    monkeypatch.setattr(module, "_write", uncertain)
    assert module.resolve_restored_cohort(host, path)["status"] == "cancelled"
    assert writes == [host.directory / "cohort-release.json"]
    assert (
        json.loads((attempt / "state.json").read_text())["phase"] == "restore_unknown"
    )


def test_existing_resolution_receipt_is_read_back_without_overwrite_after_pointer_write_failed(
    tmp_path, monkeypatch
):
    host, _, path, attempt, _ = recovery(tmp_path)
    original = module._write

    def blocked(*_args, **_kwargs):
        raise OSError("before pointer replacement")

    monkeypatch.setattr(module, "_write", blocked)
    with pytest.raises(CohortError, match="RESOLUTION_WRITE_UNKNOWN"):
        module.resolve_restored_cohort(host, path)
    receipt = attempt / "recovery-readback.json"
    saved, inode = receipt.read_bytes(), receipt.stat().st_ino
    monkeypatch.setattr(module, "_write", original)
    assert module.resolve_restored_cohort(host, path)["status"] == "cancelled"
    assert receipt.read_bytes() == saved and receipt.stat().st_ino == inode


def test_resolution_host_audit_failure_preserves_all_unknown_bytes(tmp_path):
    host, _, path, attempt, _ = recovery(tmp_path)
    original = (attempt / "state.json").read_bytes()

    def blocked(_):
        raise CohortError("COHORT_RESTORE_OWNER_LOCK_UNPROVEN")

    host.verify_old_restored = blocked
    with pytest.raises(CohortError, match="OWNER_LOCK_UNPROVEN"):
        module.resolve_restored_cohort(host, path)
    assert (attempt / "state.json").read_bytes() == original
    assert (host.directory / "cohort-release.json").read_bytes() == original
    assert not (attempt / "recovery-readback.json").exists()


def test_resolution_cli_dispatches_exact_historical_plan_audit_without_apply(
    tmp_path, monkeypatch, capsys
):
    from app import runtime_cohort_host

    host, _, path, attempt, _ = recovery(tmp_path)
    original = (attempt / "state.json").read_bytes()
    monkeypatch.setattr(runtime_cohort_host, "CohortHost", lambda: host)
    assert module.main(["resolve-restored", "--plan", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
    assert host.calls == [] and (attempt / "state.json").read_bytes() == original


def test_resolution_requires_matching_unknown_plan_identity_in_both_records(tmp_path):
    host, _, path, attempt, state = recovery(tmp_path)
    state["plan_sha256"] = "0" * 64
    _write(attempt / "state.json", state)
    original_global = (host.directory / "cohort-release.json").read_bytes()
    with pytest.raises(CohortError, match="PRECOMMIT_RESTORE_REQUIRED"):
        module.resolve_restored_cohort(host, path)
    assert (host.directory / "cohort-release.json").read_bytes() == original_global
    assert not (attempt / "recovery-readback.json").exists()


def test_resolution_requires_unchanged_registry_bytes_hash(tmp_path):
    host, _, path, attempt, _ = recovery(tmp_path)
    host.binding_hash = lambda: "d" * 64
    with pytest.raises(CohortError, match="REGISTRY_DRIFT"):
        module.resolve_restored_cohort(host, path)
    assert not (attempt / "recovery-readback.json").exists()


def test_resolution_receipt_is_private_and_cannot_resume_under_changed_runtime_identity(
    tmp_path, monkeypatch
):
    import stat

    host, _, path, attempt, _ = recovery(tmp_path)
    original_write = module._write
    monkeypatch.setattr(
        module,
        "_write",
        lambda *_args: (_ for _ in ()).throw(OSError("pointer write failed")),
    )
    with pytest.raises(CohortError, match="RESOLUTION_WRITE_UNKNOWN"):
        module.resolve_restored_cohort(host, path)
    receipt = attempt / "recovery-readback.json"
    saved = receipt.read_bytes()
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    host.verify_old_restored = lambda _: {"identity_sha256": "e" * 64}
    monkeypatch.setattr(module, "_write", original_write)
    with pytest.raises(CohortError, match="RECEIPT_MISMATCH"):
        module.resolve_restored_cohort(host, path)
    assert receipt.read_bytes() == saved
    assert (
        json.loads((host.directory / "cohort-release.json").read_text())["phase"]
        == "restore_unknown"
    )
