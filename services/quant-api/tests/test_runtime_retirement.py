import pytest
from app import runtime_retirement as m


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


def test_unsealed_pending_recovery_pins_root(tmp_path):
    root = tmp_path / "release"
    directory = tmp_path / "runtime"
    child = directory / "cohort-forward-recoveries" / ("a" * 64)
    child.mkdir(parents=True, mode=0o700)
    child.parent.chmod(0o700)
    m._write(child / "state.json", m._encoded({"phase": "outcome_unknown"}))
    m._write(child / "plan.json", m._encoded({"controller": {"root": str(root)}}))
    result = m.recovery_references(directory, tmp_path, (root,))
    assert result[str(root)] == ["recovery:cohort-forward-recoveries:" + "a" * 64]


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
