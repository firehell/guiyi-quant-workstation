import pytest
from app import runtime_retirement as m


@pytest.mark.parametrize("omit_close_resolution", (False, True))
def test_archive_post_feed_stopped_chain_requires_unique_close_resolution(
    tmp_path, monkeypatch, omit_close_resolution
):
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from app.runtime_handover import _write
    from tests.test_runtime_stopped_recovery import recover_after_feed_failure

    host, failed, fresh = recover_after_feed_failure(tmp_path, monkeypatch)
    if omit_close_resolution:
        folder = host.directory / "cohort-forward-recoveries" / fresh["plan_sha256"]
        receipt = m._json(folder / "receipt.json")
        del receipt["feed_close_resolution"]
        _write(folder / "receipt.json", receipt)
        state = m._json(folder / "state.json")
        state["receipt_sha256"] = m.sha((folder / "receipt.json").read_bytes())
        _write(folder / "state.json", state)
    terminal = host.directory / "cohort-attempts" / ("f" * 64)
    terminal.mkdir(mode=0o700)
    _write(
        terminal / "plan.json",
        {"plan_sha256": terminal.name, "created_at": fresh["created_at"], "new": {}},
    )
    _write(
        terminal / "state.json",
        {
            "schema_version": 1,
            "plan_sha256": terminal.name,
            "phase": "switched",
            "effects": {
                "verified": {"continuous_identity": "matched"},
                "calendars_on": {
                    "calendar_registration_only": True,
                    "identity": "matched",
                },
            },
        },
    )
    previous = m._json(failed["stopped_confirmation"]["path"])
    assert len(previous["attempts"]) == 2
    expected = set(previous["attempts"]) | {
        fresh["plan_sha256"],
        failed["plan_sha256"],
        fresh["closed_feed"]["plan_sha256"],
        failed["source"]["plan_sha256"],
        terminal.name,
    }
    monkeypatch.setattr(cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    seal = {
        "directory": str(host.directory),
        "releases": [],
        "terminal_cohort": terminal.name,
        "closed_attempts": sorted(expected),
        "originals": {str(p): m.sha(p.read_bytes()) for p in tmp_path.rglob("*.json")},
    }
    if omit_close_resolution:
        with pytest.raises(ValueError):
            m._closed_history(seal, tmp_path)
    else:
        assert m._closed_history(seal, tmp_path) == expected


def test_archive_original_intake_timeout_closed_by_stopped_recovery(
    tmp_path, monkeypatch
):
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from app.runtime_stopped_recovery import reconcile_stopped
    from app.runtime_handover import _write
    from tests.test_runtime_stopped_recovery import original_failed_consumers

    host, failed_path, failed, _ = original_failed_consumers(tmp_path, monkeypatch)
    selected = reconcile_stopped(host, failed_path)["confirmation"]
    plan = recovery.freeze_forward_recovery(
        host, failed["source"]["plan_path"], stopped_confirmation=selected["path"]
    )
    intake = {
        "schema_version": 2,
        "kind": "reference_receiving_liveness_v1",
        "mode": "durable_receiving_caught_up_idle",
        "calculation_ready": False,
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "advanced_count": 0,
        "remaining_count": 0,
        "old_tail_reached": True,
    }
    host.await_consumers = lambda *args: intake
    host.verify_forward = lambda *args: {
        "continuous_identity": "matched",
        "calculation_ready": False,
        "intake": intake,
    }
    host.forward_calendars = lambda *args: {
        "calendar_registration_only": True,
        "identity": "matched",
    }
    path = tmp_path / "stopped-fresh.json"
    _write(path, plan)
    recovery.apply_forward_recovery(host, path)
    # A later successful version switch remains required before retirement.
    terminal = host.directory / "cohort-attempts" / ("f" * 64)
    terminal.mkdir(mode=0o700)
    _write(
        terminal / "plan.json",
        {"plan_sha256": terminal.name, "created_at": plan["created_at"], "new": {}},
    )
    _write(
        terminal / "state.json",
        {
            "schema_version": 1,
            "plan_sha256": terminal.name,
            "phase": "switched",
            "effects": {
                "verified": {"continuous_identity": "matched"},
                "calendars_on": {
                    "calendar_registration_only": True,
                    "identity": "matched",
                },
            },
        },
    )
    monkeypatch.setattr(cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    expected = {
        plan["plan_sha256"],
        failed["plan_sha256"],
        failed["original_close"]["plan_sha256"],
        failed["source"]["plan_sha256"],
        terminal.name,
    }
    seal = {
        "directory": str(host.directory),
        "releases": [],
        "terminal_cohort": terminal.name,
        "closed_attempts": sorted(expected),
        "originals": {str(p): m.sha(p.read_bytes()) for p in tmp_path.rglob("*.json")},
    }
    assert m._closed_history(seal, tmp_path) == expected


@pytest.mark.parametrize(
    "damage", (None, "source", "close_receipt", "close_effect", "resolution")
)
def test_original_feed_recovery_archive_closes_only_verified_chain(
    tmp_path, monkeypatch, damage
):
    from app import runtime_cohort as cohort, runtime_cohort_recovery as recovery
    from tests.test_runtime_cohort_original_feed_recovery import original_fixture

    host, _source, source_path, source_attempt, source_bytes, _identity = (
        original_fixture(tmp_path, monkeypatch)
    )
    intake = {
        "schema_version": 2,
        "kind": "reference_receiving_liveness_v1",
        "mode": "durable_receiving_caught_up_idle",
        "calculation_ready": False,
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "advanced_count": 0,
        "remaining_count": 0,
        "old_tail_reached": True,
    }
    host.await_consumers = lambda *args: intake
    host.verify_forward = lambda *args: {
        "continuous_identity": "matched",
        "calculation_ready": False,
        "intake": intake,
    }
    host.forward_calendars = lambda *args: {
        "calendar_registration_only": True,
        "identity": "matched",
    }
    close_plan = recovery.freeze_forward_recovery(
        host, source_path, original_verified_feed_halt=True, close_feed_only=True
    )
    close_path = tmp_path / "close.json"
    from app.runtime_handover import _write

    _write(close_path, close_plan)
    recovery.apply_forward_recovery(host, close_path)
    normal = recovery.freeze_forward_recovery(
        host, source_path, original_verified_feed_halt=True, feed_close_plan=close_path
    )
    normal_path = tmp_path / "normal.json"
    _write(normal_path, normal)
    recovery.apply_forward_recovery(host, normal_path)
    close_dir = host.directory / "cohort-forward-recoveries" / close_plan["plan_sha256"]
    normal_dir = host.directory / "cohort-forward-recoveries" / normal["plan_sha256"]
    if damage == "source":
        state = m._json(source_attempt / "state.json")
        state["failed_phase"] = "feed"
        _write(source_attempt / "state.json", state)
    elif damage == "close_receipt":
        receipt = m._json(close_dir / "receipt.json")
        receipt["recovery_started"] = True
        _write(close_dir / "receipt.json", receipt)
    elif damage == "close_effect":
        state = m._json(close_dir / "state.json")
        state["effects"]["feed_stop"]["label_absent"] = False
        _write(close_dir / "state.json", state)
    elif damage == "resolution":
        receipt = m._json(normal_dir / "receipt.json")
        receipt["original_feed_halt_resolution"]["source"] = {}
        _write(normal_dir / "receipt.json", receipt)
    # Release/plan schema validation is covered by the recovery tests. This test
    # exercises immutable archive linkage without any live registry dependency.
    monkeypatch.setattr(cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    terminal = host.directory / "cohort-attempts" / ("f" * 64)
    terminal.mkdir(mode=0o700)
    _write(
        terminal / "plan.json",
        {"plan_sha256": terminal.name, "created_at": normal["created_at"], "new": {}},
    )
    _write(
        terminal / "state.json",
        {
            "schema_version": 1,
            "plan_sha256": terminal.name,
            "phase": "switched",
            "effects": {
                "verified": {"continuous_identity": "matched"},
                "calendars_on": {
                    "calendar_registration_only": True,
                    "identity": "matched",
                },
            },
        },
    )
    seal = {
        "directory": str(host.directory),
        "releases": [],
        "terminal_cohort": terminal.name,
        "closed_attempts": [
            source_attempt.name,
            close_dir.name,
            normal_dir.name,
            terminal.name,
        ],
        "originals": {
            str(path): m.sha(path.read_bytes()) for path in tmp_path.rglob("*.json")
        },
    }
    if damage:
        with pytest.raises((ValueError, KeyError)):
            m._closed_history(seal, tmp_path)
    else:
        assert m._closed_history(seal, tmp_path) == {
            source_attempt.name,
            close_dir.name,
            normal_dir.name,
            terminal.name,
        }
        assert (source_attempt / "state.json").read_bytes() == source_bytes


class Backend:
    def __init__(self, tmp_path):
        self.directory = tmp_path / "runtime"
        self.directory.mkdir(mode=0o700)
        self.repo_root = tmp_path
        self.root = tmp_path / "release"
        self.root.mkdir()
        self.source = self.directory / "state.json"
        self.source.write_bytes(b'{"phase":"outcome_unknown"}')
        self.marker = self.root / ".run" / "market-runtime-enabled"
        self.marker.parent.mkdir()
        self.marker.write_bytes(b"enabled\n")

    def collect(self, roots):
        return {
            "directory": str(self.directory),
            "repo_root": str(self.repo_root),
            "repository_common_dir": str(self.repo_root),
            "releases": [{"root": str(self.root), "tag": "v1.2.3", "commit": "a" * 40}],
            "closed_attempts": ["b" * 64],
            "originals": {str(self.source): m.sha(self.source.read_bytes())},
            "markers": {str(self.marker): m.sha(self.marker.read_bytes())},
            "guards": {"binding": "c" * 64},
            "terminal_cohort": "d" * 64,
        }


def test_seal_preserves_unknown_and_archives_only_exact_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        m, "_closed_history", lambda plan, _: set(plan["closed_attempts"])
    )
    monkeypatch.setattr(m, "_verify_present_release", lambda *args: None)
    backend = Backend(tmp_path)
    monkeypatch.setattr(m, "_verify_git", lambda *args: None)
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path))
    plan = m.build_closeout_plan((backend.root,), backend=backend)
    result = m.seal_closed(plan, backend=backend)
    assert result == m.seal_closed(plan, backend=backend)
    assert backend.source.read_bytes() == b'{"phase":"outcome_unknown"}'
    backend.marker.unlink()
    assert (
        m.historical_bytes(backend.directory, tmp_path, backend.marker) == b"enabled\n"
    )
    assert m.sealed_closed_attempts(backend.directory, tmp_path, []) == {"b" * 64}
    with pytest.raises(ValueError):
        m.historical_bytes(backend.directory, tmp_path, backend.root / ".env")
    backend.source.write_bytes(b"changed")
    with pytest.raises(ValueError):
        m.sealed_closed_attempts(backend.directory, tmp_path, [])


def test_plan_drift_and_hash_tampering_rejected(tmp_path):
    backend = Backend(tmp_path)
    plan = m.build_closeout_plan((backend.root,), backend=backend)
    backend.marker.write_bytes(b"changed")
    with pytest.raises(ValueError):
        m.seal_closed(plan, backend=backend)
    plan["closed_attempts"] = []
    with pytest.raises(ValueError):
        m.seal_closed(plan, backend=backend)


@pytest.mark.parametrize("damage", ["blob", "index", "symlink", "permissions", "extra"])
def test_missing_or_changed_seal_never_authorizes_history(
    tmp_path, monkeypatch, damage
):
    monkeypatch.setattr(
        m, "_closed_history", lambda plan, _: set(plan["closed_attempts"])
    )
    monkeypatch.setattr(m, "_verify_present_release", lambda *args: None)
    backend = Backend(tmp_path)
    monkeypatch.setattr(m, "_verify_git", lambda *args: None)
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path))
    plan = m.build_closeout_plan((backend.root,), backend=backend)
    result = m.seal_closed(plan, backend=backend)
    from pathlib import Path

    index = Path(result["path"])
    blob = index.parent / plan["markers"][str(backend.marker)]
    if damage == "index":
        index.write_bytes(b"{}")
    elif damage == "blob":
        blob.write_bytes(b"tampered")
    elif damage == "permissions":
        index.chmod(0o644)
    elif damage == "extra":
        (index.parent / "unexpected").write_bytes(b"not sealed")
    else:
        raw = blob.read_bytes()
        blob.unlink()
        external = tmp_path / "external"
        external.write_bytes(raw)
        blob.symlink_to(external)
    with pytest.raises((ValueError, OSError)):
        m.verify_historical_release(
            backend.directory, tmp_path, backend.root, "v1.2.3", "a" * 40
        )


@pytest.mark.parametrize("relative_root", ("release", "扩展盘/release"))
def test_unsealed_pending_recovery_pins_root(tmp_path, monkeypatch, relative_root):
    root = tmp_path / relative_root
    directory = tmp_path / "runtime"
    child = directory / "cohort-forward-recoveries" / ("a" * 64)
    child.mkdir(parents=True, mode=0o700)
    child.parent.chmod(0o700)
    m._write(child / "state.json", m._encoded({"phase": "outcome_unknown"}))
    m._write(child / "plan.json", m._encoded({"controller": {"root": str(root)}}))
    result = m.recovery_references(directory, tmp_path, (root,))
    assert result[str(root)] == ["recovery:cohort-forward-recoveries:" + "a" * 64]
    monkeypatch.setattr(m, "sealed_closed_attempts",
                        lambda *_args: {child.name})
    assert m.recovery_references(directory, tmp_path, (root,))[str(root)] == []


def test_future_checkout_same_repository_can_read_seal_but_other_repo_cannot(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(m, "_verify_present_release", lambda *args: None)
    monkeypatch.setattr(
        m, "_closed_history", lambda plan, _: set(plan["closed_attempts"])
    )
    monkeypatch.setattr(m, "_verify_present_release", lambda *args: None)
    backend = Backend(tmp_path)
    monkeypatch.setattr(m, "_verify_git", lambda *args: None)
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path))
    plan = m.build_closeout_plan((backend.root,), backend=backend)
    m.seal_closed(plan, backend=backend)
    m.verify_historical_release(
        backend.directory, tmp_path / "future", backend.root, "v1.2.3", "a" * 40
    )
    monkeypatch.setattr(m, "_common", lambda _: "other")
    with pytest.raises(ValueError):
        m.verify_historical_release(
            backend.directory, tmp_path / "future", backend.root, "v1.2.3", "a" * 40
        )


def native_case(tmp_path, monkeypatch, old_phase="restore_unknown"):
    from dataclasses import dataclass
    from app import (
        runtime_bindings,
        runtime_cohort,
        runtime_cohort_recovery,
        runtime_retention,
    )

    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    root = tmp_path / "old"
    root.mkdir()

    @dataclass
    class Binding:
        root: str
        tag: str = "v1.2.4"
        commit: str = "e" * 40

    @dataclass
    class Registry:
        services: dict

    bindings = Registry(
        {name: Binding(str(tmp_path / "current")) for name in runtime_bindings.SERVICES}
    )
    monkeypatch.setattr(runtime_bindings, "read_bindings", lambda: bindings)
    monkeypatch.setattr(runtime_cohort, "registry", lambda _: bindings)
    monkeypatch.setattr(runtime_cohort, "validate", lambda *a, **k: None)
    monkeypatch.setattr(
        runtime_cohort_recovery, "_no_unresolved_recovery", lambda *_: None
    )
    monkeypatch.setattr(m, "_verify_present_release", lambda *args: None)
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path))
    monkeypatch.setattr(m, "_verify_git", lambda *args: None)
    monkeypatch.setattr(
        runtime_retention.RetentionBackend,
        "references_by_root",
        lambda _, roots: {str(root): [] for root in roots},
    )
    monkeypatch.setattr(
        runtime_retention.RetentionBackend,
        "candidate_identity",
        lambda _, target: {"root": str(target), "tag": "v1.2.3", "commit": "a" * 40},
    )
    parent = directory / "cohort-attempts"
    parent.mkdir(mode=0o700)
    old, current = parent / ("b" * 64), parent / ("d" * 64)
    for child in (old, current):
        child.mkdir(mode=0o700)
        m._write(
            child / "plan.json",
            m._encoded(
                {
                    "plan_sha256": child.name,
                    "created_at": "2026-10-27T00:00:00+00:00",
                    "new": {},
                }
            ),
        )
    old_state = {
        "schema_version": 1,
        "phase": old_phase,
        "plan_sha256": old.name,
        "effects": {"drain": {}},
    }
    m._write(old / "state.json", m._encoded(old_state))
    state = {
        "schema_version": 1,
        "phase": "switched",
        "plan_sha256": current.name,
        "effects": {
            "verified": {"continuous_identity": "matched"},
            "calendars_on": {"identity": "matched", "calendar_registration_only": True},
        },
    }
    m._write(current / "state.json", m._encoded(state))
    m._write(directory / "cohort-release.json", m._encoded(state))
    receipt = {
        "kind": "precommit_restore_readback",
        "schema_version": 1,
        "plan_sha256": old.name,
        "source_attempt_sha256": m.sha(m._read(old / "state.json")),
        "source_global_sha256": m.sha(m._read(old / "state.json")),
        "source_plan_sha256": m.sha(m._read(old / "plan.json")),
        "proof": {"identity_sha256": "a" * 64},
    }
    m._write(old / "recovery-readback.json", m._encoded(receipt))
    return m.RetirementBackend(directory, tmp_path), root, old, current


def test_native_collector_accepts_only_hash_bound_restore_readback(
    tmp_path, monkeypatch
):
    backend, root, old, current = native_case(tmp_path, monkeypatch)
    plan = m.build_closeout_plan((root,), backend=backend)
    assert set(plan["closed_attempts"]) == {old.name, current.name}
    assert plan["terminal_cohort"] == current.name
    receipt = m._json(old / "recovery-readback.json")
    receipt["source_attempt_sha256"] = "f" * 64
    (old / "recovery-readback.json").write_bytes(m._encoded(receipt))
    with pytest.raises(ValueError):
        m.build_closeout_plan((root,), backend=backend)


def test_collector_verifies_each_release_once_per_call_and_history_independently(
    tmp_path, monkeypatch,
):
    from app import runtime_cohort

    backend, root, _old, terminal = native_case(tmp_path, monkeypatch)
    identity = {"root": str(root), "tag": "v1.2.3", "commit": "a" * 40}
    plan_path = terminal / "plan.json"
    plan = m._json(plan_path)
    plan["releases"] = [identity] * 12
    plan_path.write_bytes(m._encoded(plan))

    def validate(value, _created, **kwargs):
        verifier = kwargs.get("history_verifier")
        if verifier is not None:
            for item in value.get("releases", ()):
                verifier(
                    item["root"], item["tag"], item["commit"], backend.directory,
                )

    monkeypatch.setattr(runtime_cohort, "validate", validate)
    git_calls, present_calls = [], []
    monkeypatch.setattr(m, "_verify_git", lambda *args: git_calls.append(args))
    monkeypatch.setattr(
        m, "_verify_present_release",
        lambda *args: present_calls.append(args),
    )
    first = m.build_closeout_plan((root,), backend=backend)
    assert len(git_calls) == len(present_calls) == 2
    assert m.build_closeout_plan((root,), backend=backend) == first
    assert len(git_calls) == len(present_calls) == 4


def test_collector_rejects_conflicting_identity_for_same_root_before_reuse(
    tmp_path, monkeypatch,
):
    backend, root, _old, terminal = native_case(tmp_path, monkeypatch)
    plan_path = terminal / "plan.json"
    plan = m._json(plan_path)
    plan["releases"] = [
        {"root": str(root), "tag": "v1.2.3", "commit": "a" * 40},
        {"root": str(root), "tag": "v1.2.4", "commit": "b" * 40},
    ]
    plan_path.write_bytes(m._encoded(plan))
    calls = []
    monkeypatch.setattr(m, "_verify_git", lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        m.build_closeout_plan((root,), backend=backend)
    assert len(calls) == 1


def test_collector_passes_verified_history_to_forward_private_validator(
    tmp_path, monkeypatch,
):
    from app import runtime_cohort_recovery as recovery

    backend, root, old, _terminal = native_case(tmp_path, monkeypatch)
    parent = backend.directory / "cohort-forward-recoveries"
    parent.mkdir(mode=0o700)
    child = parent / ("e" * 64)
    child.mkdir(mode=0o700)
    identity = {"root": str(root), "tag": "v1.2.3", "commit": "a" * 40}
    source = {"plan_sha256": old.name}
    m._write(child / "plan.json", m._encoded({
        "plan_sha256": child.name,
        "created_at": "2026-10-27T00:00:00+00:00",
        "source": source, "new": {"services": {"live": identity}},
    }))
    receipt = {
        "plan_sha256": child.name, "source": source,
        "kind": "postcas_forward_recovery_readback",
        "original_attempt_preserved": True,
        "intake": {}, "readback": {},
    }
    m._write(child / "receipt.json", m._encoded(receipt))
    m._write(child / "state.json", m._encoded({
        "plan_sha256": child.name, "phase": "recovered", "source": source,
        "receipt_sha256": m.sha(m._encoded(receipt)),
        "effects": {
            "consumers": {}, "intake": {}, "feed": {},
            "verified": {}, "calendars": {},
        },
    }))
    calls = []

    def validate(_plan, _created, **kwargs):
        verifier = kwargs.get("history_verifier")
        assert kwargs["historical"] is True
        assert verifier is not None
        verifier(root, identity["tag"], identity["commit"], backend.directory)
        calls.append(1)

    monkeypatch.setattr(recovery, "_validate", validate)
    monkeypatch.setattr(
        m, "_closed_history", lambda seal, _repo: set(seal["closed_attempts"]),
    )
    m.build_closeout_plan((root,), backend=backend)
    assert calls == [1]


def forward_terminal_case(tmp_path, monkeypatch):
    from app import runtime_cohort_recovery as recovery

    backend, root, old, anchor = native_case(tmp_path, monkeypatch)
    parent = backend.directory / "cohort-forward-recoveries"
    parent.mkdir(mode=0o700)
    source = backend.directory / "cohort-attempts" / ("c" * 64)
    close = parent / ("e" * 64)
    normal = parent / ("f" * 64)
    for child in (source, close, normal):
        child.mkdir(mode=0o700)
    new = {"services": {"live": {"generation": 49}}}
    source_plan = {
        "plan_sha256": source.name, "created_at": "2026-10-27T00:00:00+00:00",
        "old": {}, "new": new,
    }
    source_state = {
        "schema_version": 1, "plan_sha256": source.name,
        "phase": "outcome_unknown", "effects": {},
    }
    identity = {
        "kind": recovery.ORIGINAL_FEED_SOURCE,
        "plan_sha256": source.name, "plan_path": str(source / "plan.json"),
    }
    close_descriptor = {
        "plan_sha256": close.name, "plan_path": str(close / "plan.json"),
    }
    m._write(source / "plan.json", m._encoded(source_plan))
    m._write(source / "state.json", m._encoded(source_state))
    m._write(close / "plan.json", m._encoded({
        "plan_sha256": close.name, "created_at": source_plan["created_at"],
        "source": identity, "new": new,
    }))
    m._write(close / "state.json", m._encoded({
        "schema_version": 1, "plan_sha256": close.name, "phase": "feed_closed",
    }))
    confirmation = {"verified": True}
    plan = {
        "plan_sha256": normal.name, "created_at": source_plan["created_at"],
        "mode": recovery.ORIGINAL_FEED_MODE, "source": identity,
        "new": new, "original_close": close_descriptor,
        "audit": {"original_verified_feed_halt": confirmation},
    }
    intake = {"schema_version": 2}
    readback = {
        "continuous_identity": "matched", "calculation_ready": False,
        "intake": intake,
    }
    receipt = {
        "schema_version": 1, "kind": "postcas_forward_recovery_readback",
        "plan_sha256": normal.name, "source": identity,
        "observed_at": "2026-10-27T00:00:00+00:00",
        "intake": intake, "readback": readback, "natural_acceptance": "pending",
        "original_attempt_preserved": True,
        "original_feed_halt_resolution": {
            "kind": "original_cohort_verified_feed_halt_resolution_v1",
            "source": identity, "feed_close": close_descriptor,
            "confirmation": confirmation,
        },
    }
    state = {
        "schema_version": 1, "kind": recovery.KIND, "phase": "recovered",
        "plan_sha256": normal.name, "source": identity,
        "receipt_sha256": m.sha(m._encoded(receipt)),
        "effects": {
            "consumers": {"resumed_generation": 49},
            "intake": intake,
            "feed": {"bootstrapped": True, "label": "com.guiyi.quant-market-feed"},
            "verified": readback,
            "calendars": {"calendar_registration_only": True, "identity": "matched"},
        },
    }
    m._write(normal / "plan.json", m._encoded(plan))
    m._write(normal / "receipt.json", m._encoded(receipt))
    m._write(normal / "state.json", m._encoded(state))
    pointer = {
        "schema_version": 1, "kind": "postcas_forward_recovery_result",
        "phase": "switched", "source_phase": "outcome_unknown",
        "plan_sha256": normal.name, "source_plan_sha256": source.name,
        "receipt_sha256": state["receipt_sha256"],
        "original_attempt_preserved": True,
        "original_feed_halt_resolution": {
            "source_plan_sha256": source.name,
            "feed_close_plan_sha256": close.name,
            "receipt_sha256": state["receipt_sha256"],
        },
    }
    (backend.directory / "cohort-release.json").write_bytes(m._encoded(pointer))
    monkeypatch.setattr(recovery, "_validate", lambda *a, **k: None)
    monkeypatch.setattr(
        recovery, "_original_verified_feed_source",
        lambda *a, **k: (source_plan, source_state, identity),
    )
    monkeypatch.setattr(
        recovery, "_original_feed_close_attempt",
        lambda *a, **k: (close_descriptor, {}),
    )
    monkeypatch.setattr(recovery, "valid_original_verified_feed_halt",
                        lambda *a, **k: True)
    monkeypatch.setattr(recovery, "_valid_intake_result", lambda *a: True)
    return backend, root, old, anchor, source, close, normal


def test_forward_terminal_collector_seals_only_old_reader_compatible_history(
    tmp_path, monkeypatch,
):
    backend, root, old, anchor, source, close, normal = forward_terminal_case(
        tmp_path, monkeypatch,
    )
    plan = m.build_closeout_plan((root,), backend=backend)
    assert plan["terminal_cohort"] == anchor.name
    assert set(plan["closed_attempts"]) == {old.name, anchor.name}
    assert all(
        excluded not in path
        for path in plan["originals"]
        for excluded in (source.name, close.name, normal.name)
    )
    assert m._closed_history(plan, backend.repo_root) == {
        old.name, anchor.name,
    }
    assert plan["guards"]["global_sha256"] == m.sha(
        m._read(backend.directory / "cohort-release.json")
    )


@pytest.mark.parametrize("damage", (
    "pointer_extra", "receipt_hash", "source_hash", "readback",
    "close_resolution", "source_generation", "second_anchor",
    "extra_source_recovery",
))
def test_forward_terminal_collector_rejects_changed_causal_link(
    tmp_path, monkeypatch, damage,
):
    backend, root, _old, anchor, _source, _close, normal = forward_terminal_case(
        tmp_path, monkeypatch,
    )
    pointer_path = backend.directory / "cohort-release.json"
    pointer = m._json(pointer_path)
    if damage == "pointer_extra":
        pointer["unknown"] = True
    elif damage == "receipt_hash":
        pointer["receipt_sha256"] = "a" * 64
    elif damage == "source_hash":
        pointer["source_plan_sha256"] = "a" * 64
    elif damage == "readback":
        state_path = normal / "state.json"
        state = m._json(state_path)
        state["effects"]["verified"]["continuous_identity"] = "unmatched"
        state_path.write_bytes(m._encoded(state))
    elif damage == "close_resolution":
        pointer["original_feed_halt_resolution"]["feed_close_plan_sha256"] = (
            "a" * 64
        )
    elif damage == "source_generation":
        plan_path = normal / "plan.json"
        changed = m._json(plan_path)
        changed["new"]["services"]["live"]["generation"] = 50
        plan_path.write_bytes(m._encoded(changed))
    elif damage == "second_anchor":
        extra = backend.directory / "cohort-attempts" / ("a" * 64)
        extra.mkdir(mode=0o700)
        m._write(extra / "plan.json", m._read(anchor / "plan.json"))
        state = m._json(anchor / "state.json")
        state["plan_sha256"] = extra.name
        m._write(extra / "state.json", m._encoded(state))
    else:
        extra = backend.directory / "cohort-forward-recoveries" / ("a" * 64)
        extra.mkdir(mode=0o700)
        extra_plan = m._json(normal / "plan.json")
        extra_plan["plan_sha256"] = extra.name
        m._write(extra / "plan.json", m._encoded(extra_plan))
        m._write(extra / "state.json", m._encoded({
            "schema_version": 1, "plan_sha256": extra.name,
            "phase": "recovered", "source": extra_plan["source"],
        }))
    if damage in {"pointer_extra", "receipt_hash", "source_hash",
                  "close_resolution"}:
        pointer_path.write_bytes(m._encoded(pointer))
    with pytest.raises(ValueError):
        m.build_closeout_plan((root,), backend=backend)


def test_native_collector_rejects_unclosed_cohort_and_new_unresolved_forward(
    tmp_path, monkeypatch
):
    backend, root, _, _ = native_case(tmp_path, monkeypatch, "outcome_unknown")
    with pytest.raises(ValueError):
        m.build_closeout_plan((root,), backend=backend)
    from app import runtime_cohort_recovery

    def blocked(_):
        raise ValueError("COHORT_FORWARD_RECOVERY_READBACK_REQUIRED")

    monkeypatch.setattr(runtime_cohort_recovery, "_no_unresolved_recovery", blocked)
    with pytest.raises(ValueError, match="COHORT_FORWARD_RECOVERY_READBACK_REQUIRED"):
        m.build_closeout_plan((root,), backend=backend)


def test_old_attempt_uses_exact_public_plan_without_creating_private_copy(
    tmp_path, monkeypatch
):
    from app.reference_trading.recovery_campaign import digest

    directory = tmp_path / "runtime"
    public_dir = directory / "rollover-readiness-20261027"
    public_dir.mkdir(parents=True)
    value = {"kind": "stopped_world_release_v1", "old": {}, "new": {}}
    value["plan_sha256"] = digest(value)
    child = directory / "cohort-attempts" / value["plan_sha256"]
    child.mkdir(parents=True)
    public = public_dir / "cohort-plan-v1.json"
    public.write_bytes(m._encoded(value))
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path / ".git"))
    paths = m._plan_paths([(child, {})], directory, tmp_path)
    assert paths == {child: public}
    assert not (child / "plan.json").exists()
    public.unlink()
    with pytest.raises(ValueError):
        m._plan_paths([(child, {})], directory, tmp_path)


def test_real_git_history_requires_annotated_identity_and_same_repository(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        m, "_closed_history", lambda plan, _: set(plan["closed_attempts"])
    )
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(
            [
                "/usr/bin/git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                *args,
            ],
            cwd=repo,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

    git("init")
    (repo / ".gitignore").write_text(".run/\n")
    git("add", ".gitignore")
    git("commit", "-m", "fixture")
    commit = git("rev-parse", "HEAD")
    git("tag", "-a", "v1.2.3", "-m", "fixture")
    root = tmp_path / "release-v1.2.3"
    git("worktree", "add", "--detach", str(root), "v1.2.3")
    backend = Backend(tmp_path)
    backend.root = root
    backend.repo_root = repo
    original_collect = backend.collect

    def collect(roots):
        value = original_collect(roots)
        value["releases"] = [{"root": str(root), "tag": "v1.2.3", "commit": commit}]
        value["repository_common_dir"] = m._common(repo)
        value["markers"] = {}
        return value

    backend.collect = collect
    plan = m.build_closeout_plan((root,), backend=backend)
    m.seal_closed(plan, backend=backend)
    m.verify_historical_release(backend.directory, repo, root, "v1.2.3", commit)
    (root / "dirty").write_text("not authorized")
    with pytest.raises(ValueError):
        m.sealed_closed_attempts(backend.directory, repo, [])
    with pytest.raises(ValueError):
        m.verify_historical_release(backend.directory, repo, root, "v1.2.3", commit)
    (root / "dirty").unlink()
    git("worktree", "remove", str(root))
    root.symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError):
        m.sealed_closed_attempts(backend.directory, repo, [])
    root.unlink()
    m.verify_historical_release(backend.directory, repo, root, "v1.2.3", commit)
    with pytest.raises(ValueError):
        m.verify_historical_release(backend.directory, repo, root, "v1.2.3", "f" * 40)
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(
        ["/usr/bin/git", "init", str(other)], check=True, capture_output=True
    )
    with pytest.raises(ValueError):
        m.verify_historical_release(backend.directory, other, root, "v1.2.3", commit)
    git("tag", "-d", "v1.2.3")
    git("tag", "v1.2.3", commit)
    with pytest.raises(ValueError):
        m.verify_historical_release(backend.directory, repo, root, "v1.2.3", commit)


def test_seal_revalidates_and_commits_under_deployment_lock(tmp_path, monkeypatch):
    from app.runtime_handover import deployment_lock, HandoverError

    monkeypatch.setattr(
        m, "_closed_history", lambda plan, _: set(plan["closed_attempts"])
    )
    monkeypatch.setattr(m, "_verify_present_release", lambda *args: None)
    backend = Backend(tmp_path)
    monkeypatch.setattr(m, "_verify_git", lambda *args: None)
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path))
    plan = m.build_closeout_plan((backend.root,), backend=backend)
    collect = backend.collect
    calls = []

    def locked_collect(roots):
        with pytest.raises(HandoverError, match="RUNTIME_DEPLOYMENT_BUSY"):
            with deployment_lock(runtime_dir=backend.directory):
                pass
        calls.append(1)
        return collect(roots)

    backend.collect = locked_collect
    m.seal_closed(plan, backend=backend)
    assert len(calls) == 2


def test_resigned_index_cannot_add_unclosed_attempt(tmp_path, monkeypatch):
    from pathlib import Path

    backend, root, _, _ = native_case(tmp_path, monkeypatch)
    plan = m.build_closeout_plan((root,), backend=backend)
    result = m.seal_closed(plan, backend=backend)
    folder = Path(result["path"]).parent
    unknown = backend.directory / "cohort-attempts" / ("e" * 64)
    unknown.mkdir(parents=True, mode=0o700)
    unknown.parent.chmod(0o700)
    m._write(
        unknown / "state.json",
        m._encoded(
            {
                "schema_version": 1,
                "plan_sha256": unknown.name,
                "phase": "outcome_unknown",
                "effects": {},
            }
        ),
    )
    m._write(
        unknown / "plan.json",
        m._encoded(
            {
                "plan_sha256": unknown.name,
                "created_at": "2026-10-27T00:00:00+00:00",
                "new": {},
            }
        ),
    )
    index = m._json(folder / "index.json")
    index["plan"]["originals"][str(unknown / "plan.json")] = m.sha(
        m._read(unknown / "plan.json")
    )
    index["plan"]["closed_attempts"].append(unknown.name)
    index["plan"]["originals"][str(unknown / "state.json")] = m.sha(
        m._read(unknown / "state.json")
    )
    index["plan"]["plan_sha256"] = m._digest(
        {k: v for k, v in index["plan"].items() if k != "plan_sha256"}
    )
    index["index_sha256"] = m._digest(
        {k: v for k, v in index.items() if k != "index_sha256"}
    )
    (folder / "index.json").write_bytes(m._encoded(index))
    target = folder.parent / index["plan"]["plan_sha256"]
    folder.rename(target)
    with pytest.raises(ValueError):
        m.sealed_closed_attempts(
            backend.directory, tmp_path, [(unknown, m._json(unknown / "state.json"))]
        )


def test_same_basename_in_other_namespace_is_not_covered(tmp_path, monkeypatch):
    backend, root, old, _ = native_case(tmp_path, monkeypatch)
    plan = m.build_closeout_plan((root,), backend=backend)
    m.seal_closed(plan, backend=backend)
    collision = backend.directory / "cohort-forward-recoveries" / old.name
    collision.mkdir(parents=True, mode=0o700)
    collision.parent.chmod(0o700)
    state = {"phase": "outcome_unknown", "plan_sha256": old.name}
    m._write(collision / "state.json", m._encoded(state))
    with pytest.raises(ValueError):
        m.sealed_closed_attempts(backend.directory, tmp_path, [(collision, state)])


def test_public_format_variants_use_bound_bytes_but_private_plan_is_authoritative(
    tmp_path, monkeypatch
):
    import json
    from app.reference_trading.recovery_campaign import digest

    directory = tmp_path / "runtime"
    public_dir = directory / "rollover-readiness-20261027"
    public_dir.mkdir(parents=True)
    value = {"kind": "stopped_world_release_v1", "old": {}, "new": {}}
    value["plan_sha256"] = digest(value)
    child = directory / "cohort-attempts" / value["plan_sha256"]
    child.mkdir(parents=True)
    one, two = public_dir / "cohort-plan-v1.json", public_dir / "cohort-plan-v2.json"
    one.write_bytes(m._encoded(value))
    two.write_text(json.dumps(value, indent=4))
    m._write(
        child / "recovery-readback.json",
        m._encoded({"source_plan_sha256": m.sha(two.read_bytes())}),
    )
    monkeypatch.setattr(m, "_common", lambda _: str(tmp_path / ".git"))
    assert m._plan_paths([(child, {})], directory, tmp_path)[child] == two
    m._write(child / "plan.json", m._encoded(value))
    assert (
        m._plan_paths([(child, {})], directory, tmp_path)[child] == child / "plan.json"
    )
