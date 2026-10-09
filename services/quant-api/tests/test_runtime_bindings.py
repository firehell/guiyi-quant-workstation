import hashlib
import json

import pytest

from app.runtime_bindings import (
    BindingRegistry, RuntimeBindingError, ServiceBinding, pinned_release_roots,
    read_bindings, registry_path, write_bindings,
)


def binding(root, service="live", generation=1):
    return ServiceBinding(service, str(root), "v1.2.3", "a" * 40, generation, True,
                          {key: "b" * 64 for key in ("db", "live", "input", "formula", "reference", "launcher")})


def test_atomic_registry_roundtrip_cas_and_pinned_roots(tmp_path):
    root = tmp_path / "release"
    root.mkdir()
    registry = BindingRegistry(1, {"live": binding(root)})
    digest = write_bindings(registry, home=tmp_path, expected_sha256=None)
    assert registry_path(tmp_path).stat().st_mode & 0o777 == 0o600
    assert read_bindings(home=tmp_path) == registry
    assert pinned_release_roots(home=tmp_path) == frozenset({root})
    assert digest == hashlib.sha256(registry_path(tmp_path).read_bytes()).hexdigest()
    with pytest.raises(RuntimeBindingError, match="REGISTRY_DRIFT"):
        write_bindings(registry, home=tmp_path, expected_sha256="c" * 64)
    assert write_bindings(registry, home=tmp_path, expected_sha256=digest) == digest


@pytest.mark.parametrize("defect", ["json", "permission", "symlink", "duplicate", "invalid_identity"])
def test_present_invalid_registry_never_falls_back(tmp_path, defect):
    assert read_bindings(home=tmp_path) is None
    root = tmp_path / "release"
    root.mkdir()
    write_bindings(BindingRegistry(1, {"live": binding(root)}), home=tmp_path, expected_sha256=None)
    path = registry_path(tmp_path)
    if defect == "json":
        path.write_text("{}")
        path.chmod(0o600)
    if defect == "permission":
        path.chmod(0o644)
    if defect == "symlink":
        destination = tmp_path / "copy"
        path.rename(destination)
        path.symlink_to(destination)
    if defect == "duplicate":
        text = path.read_text().replace('"schema_version":1', '"schema_version":1,"schema_version":1')
        path.write_text(text)
    if defect == "invalid_identity":
        payload = json.loads(path.read_text())
        payload["services"]["live"]["generation"] = True
        path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeBindingError):
        read_bindings(home=tmp_path)


@pytest.mark.parametrize("change_path, expected, blocked", [
    ("apps/web/main.ts", ["api", "web"], False),
    ("services/quant-api/app/routers/ordinary.py", ["api", "web"], False),
    ("unknown-dependency.txt", ["alert", "api", "live", "web"], False),
    ("packages/quant-core/formula.py", ["alert", "api", "web"], True),
    ("scripts/ops/macos/run-local-service.sh", ["alert", "api", "live", "web"], True),
    ("services/quant-api/app/market_data/market_feed.py", ["alert", "api", "live", "web"], True),
    ("services/quant-api/app/market_data/observation_stream.py", ["alert", "api", "live", "web"], True),
])
def test_readonly_plan_freezes_impact_and_contracts(tmp_path, change_path, expected, blocked):
    import subprocess
    from app.runtime_bindings import build_release_plan, contract_fingerprints
    root = tmp_path / "old"
    root.mkdir()
    def git(*args):
        return subprocess.run(["/usr/bin/git", "-c", "core.fsmonitor=false", *args], cwd=root,
                              check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    paths = ["services/quant-api/app/db/a.py", "services/quant-api/app/market_data/live_market.py",
             "services/quant-api/app/market_data/rqdata_adapter.py", "packages/quant-core/formula.py",
             "services/quant-api/app/reference_trading/worker.py", "scripts/ops/macos/run-local-service.sh",
             "apps/web/main.ts", "services/quant-api/app/market_data/market_feed.py",
             "services/quant-api/app/market_data/observation_stream.py", "services/quant-api/app/routers/ordinary.py"]
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n")
    git("add", ".")
    git("commit", "-m", "fixture")
    git("tag", "-a", "v1.2.3", "-m", "fixture")
    commit = git("rev-parse", "HEAD")
    candidate = tmp_path / "candidate"
    git("worktree", "add", "--detach", str(candidate), "HEAD")
    (candidate / change_path).write_text("new content\n")
    def candidate_git(*args):
        return subprocess.run(["/usr/bin/git", "-c", "core.fsmonitor=false", *args], cwd=candidate,
                              check=True, capture_output=True, text=True).stdout.strip()
    candidate_git("add", ".")
    candidate_git("commit", "-m", "ui")
    candidate_git("tag", "-a", "v1.2.4", "-m", "ui")
    git("checkout", "--detach", "v1.2.3")
    registry = BindingRegistry(1, {service: ServiceBinding(service, str(root), "v1.2.3", commit, 1,
                              True, contract_fingerprints(root)) for service in ("api", "web", "live", "alert")})
    plan = build_release_plan(registry, candidate_root=candidate, tag="v1.2.4",
                              commit=candidate_git("rev-parse", "HEAD"))
    assert plan["status"] == ("blocked" if blocked else "ready")
    assert plan["affected_services"] == expected
    if change_path == "apps/web/main.ts":
        assert plan["fingerprints"]["live"]["previous"] == plan["fingerprints"]["live"]["candidate"]
    (candidate / "untracked").write_text("dirty")
    with pytest.raises(RuntimeBindingError, match="RELEASE_IDENTITY_INVALID"):
        build_release_plan(registry, candidate_root=candidate, tag="v1.2.4", commit=candidate_git("rev-parse", "HEAD"))


def test_candidate_label_stays_bound_and_cross_service_label_is_rejected(tmp_path):
    from dataclasses import replace
    root = tmp_path / "release"
    root.mkdir()
    legacy = binding(root)
    assert legacy.label == "com.guiyi.quant-live"
    candidate = replace(legacy, launchd_label="com.guiyi.quant-live-candidate-" + "d" * 32)
    write_bindings(BindingRegistry(1, {"live": candidate}), home=tmp_path, expected_sha256=None)
    assert read_bindings(home=tmp_path).services["live"].label == candidate.label
    with pytest.raises(RuntimeBindingError):
        replace(legacy, launchd_label="com.guiyi.quant-alert-candidate-" + "d" * 32)
    with pytest.raises(RuntimeBindingError):
        replace(legacy, launchd_label="arbitrary")
