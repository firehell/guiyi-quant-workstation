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
    ("services/quant-api/app/runtime_contracts.py", ["after-market", "alert", "api", "live", "market-feed", "web"], True),
    ("unknown-dependency.txt", ["after-market", "alert", "api", "live", "market-feed", "web"], False),
    ("scripts/research/subing-replay.sh", [], False),
    ("scripts/research/subing_exit_comparison.py", [], False),
    ("scripts/research/subing_three_timing.py", [], False),
    ("scripts/research/subing_trade_report.py", [], False),
    ("scripts/research/subing_model_facts.py", ["after-market", "alert", "api", "live", "market-feed", "web"], False),
    ("scripts/research/unknown_consumer.py", ["after-market", "alert", "api", "live", "market-feed", "web"], False),
    ("packages/quant-core/formula.py", ["alert", "api", "web"], True),
    ("scripts/ops/macos/run-local-service.sh", ["after-market", "alert", "api", "live", "market-feed", "web"], True),
    ("services/quant-api/app/market_data/market_feed.py", ["after-market", "alert", "api", "live", "market-feed", "web"], True),
    ("services/quant-api/app/market_data/observation_stream.py", ["after-market", "alert", "api", "live", "market-feed", "web"], True),
    ("services/quant-api/app/market_data/feed_buffer.py", ["market-feed"], False),
    ("services/quant-api/app/market_data/completed_worker_policy.py", ["live"], False),
    ("services/quant-api/app/market_data/archive_worker_policy.py", ["after-market"], False),
])
@pytest.mark.parametrize("market_release", [False, True])
def test_readonly_plan_freezes_impact_and_contracts(tmp_path, change_path, expected, blocked, market_release):
    if market_release and change_path not in {
        "services/quant-api/app/market_data/observation_stream.py",
        "services/quant-api/app/market_data/market_feed.py",
        "services/quant-api/app/market_data/feed_buffer.py",
        "services/quant-api/app/market_data/completed_worker_policy.py",
        "services/quant-api/app/market_data/archive_worker_policy.py",
    }:
        pytest.skip("application classification case")
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
             "apps/web/main.ts", "services/quant-api/app/runtime_contracts.py", "services/quant-api/app/market_data/market_feed.py",
             "services/quant-api/app/market_data/observation_stream.py", "services/quant-api/app/routers/ordinary.py"]
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n")
    from app.market_release_identity import MARKET_TAG_PREFIX
    from app.market_version import MARKET_RELEASE_VERSION
    version_path = root / "services/quant-api/app/market_version.py"
    version_path.write_text('"""Release version for the Market Foundation component."""\n\n'
                            f'MARKET_RELEASE_VERSION = "{MARKET_RELEASE_VERSION}"\n')
    (version_path.parent / "market_release_identity.py").write_text("# supports Market bindings\n")
    git("add", ".")
    git("commit", "-m", "fixture")
    git("tag", "-a", "v1.2.3", "-m", "fixture")
    commit = git("rev-parse", "HEAD")
    candidate = tmp_path / "candidate"
    git("worktree", "add", "--detach", str(candidate), "HEAD")
    changed = candidate / change_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("new content\n")
    def candidate_git(*args):
        return subprocess.run(["/usr/bin/git", "-c", "core.fsmonitor=false", *args], cwd=candidate,
                              check=True, capture_output=True, text=True).stdout.strip()
    candidate_git("add", ".")
    candidate_git("commit", "-m", "ui")
    tag = MARKET_TAG_PREFIX + MARKET_RELEASE_VERSION if market_release else "v1.2.4"
    candidate_git("tag", "-a", tag, "-m", "candidate")
    git("checkout", "--detach", "v1.2.3")
    registry = BindingRegistry(1, {service: ServiceBinding(service, str(root), "v1.2.3", commit, 1,
                              True, contract_fingerprints(root)) for service in ("api", "web", "live", "alert", "market-feed", "after-market")})
    plan = build_release_plan(registry, candidate_root=candidate, tag=tag,
                              commit=candidate_git("rev-parse", "HEAD"))
    if market_release:
        if not blocked:
            assert plan["status"] == "ready"
            assert plan["affected_services"] == expected
            assert set(plan["candidate_bindings"]) == set(expected)
            service = expected[0]
            assert plan["candidate_bindings"][service]["tag"] == tag
            assert plan["candidate_bindings"][service]["generation"] == 2
            for service in ("api", "alert", "live", "web"):
                assert plan["previous_bindings"][service]["tag"] == "v1.2.3"
                assert plan["previous_bindings"][service]["generation"] == 1
            if service == "market-feed":
                proposed = ServiceBinding(**plan["candidate_bindings"][service])
                mixed = BindingRegistry(1, {**registry.services, service: proposed})
                write_bindings(mixed, home=tmp_path, expected_sha256=None)
                assert read_bindings(home=tmp_path) == mixed

                application = tmp_path / "next-app"
                candidate_git("worktree", "add", "--detach", str(application), "HEAD")
                (application / "apps/web/main.ts").write_text("independent app update\n")
                subprocess.run(["/usr/bin/git", "-C", str(application), "add", "."], check=True, capture_output=True)
                subprocess.run(["/usr/bin/git", "-C", str(application), "commit", "-m", "web"],
                               check=True, capture_output=True)
                subprocess.run(["/usr/bin/git", "-C", str(application), "tag", "-a", "v1.2.4", "-m", "app"],
                               check=True, capture_output=True)
                app_commit = subprocess.check_output(
                    ["/usr/bin/git", "-C", str(application), "rev-parse", "HEAD"], text=True,
                ).strip()
                app_plan = build_release_plan(mixed, candidate_root=application, tag="v1.2.4", commit=app_commit)
                assert app_plan["status"] == "ready"
                assert app_plan["affected_services"] == ["api", "web"]
                assert service not in app_plan["candidate_bindings"]
        else:
            assert plan["status"] == "blocked"
            assert plan["candidate_bindings"] == {}
            assert any(reason["code"] == "MARKET_RELEASE_SHARED_CHANGE" and change_path in reason["paths"]
                       for reason in plan["blocked"])
        return
    assert plan["readonly"] is True
    assert plan["status"] == ("blocked" if blocked else "ready")
    assert plan["affected_services"] == expected
    assert {reason["code"] for reason in plan["blocked"]} == ({"MIXED_CONTRACT_INCOMPATIBLE"} if blocked else set())
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


def test_runtime_consumers_share_exact_service_contract():
    from app import runtime_bindings, runtime_handover

    assert runtime_bindings.SERVICES is runtime_handover.SERVICES
    assert runtime_bindings.ALL is runtime_bindings.SERVICES
    assert runtime_bindings.SERVICES == frozenset({
        'api', 'web', 'live', 'market-feed', 'alert', 'reference-worker',
        'after-market', 'weekly-audit', 'late-provider-recovery', 'log-rotate', 'home-projection',
    })
