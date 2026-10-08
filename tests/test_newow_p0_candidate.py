from hashlib import sha256
import json
import pytest

from scripts.newow_p0_candidate import (
    CANONICAL_ROOT, CUTOFF, FREQUENCIES, SCHEMA, STRATEGIES,
    exclusive_campaign, stage_key, stage_order, validate_manifest, write_once,
)


def fixture_manifest(tmp_path):
    universe = "\n".join(f"p{index}" for index in range(60)).encode()
    manifest = {"schema": SCHEMA, "as_of": CUTOFF, "code_sha": "a" * 40,
                "worktree": str(tmp_path), "canonical_root": CANONICAL_ROOT,
                "universe_sha256": sha256(universe).hexdigest(),
                "products": universe.decode().splitlines(),
                "since": "2023-01-01", "through": "2026-09-24",
                "frequencies": list(FREQUENCIES), "strategies": list(STRATEGIES)}
    return manifest, universe


def test_manifest_exact_scope(tmp_path):
    manifest, universe = fixture_manifest(tmp_path)
    validate_manifest(manifest, head="a" * 40, root=tmp_path, universe=universe)


@pytest.mark.parametrize("field,value", [
    ("schema", "public"), ("code_sha", "b" * 40), ("as_of", "2026-10-08"),
    ("canonical_root", "/tmp/source"), ("universe_sha256", "b" * 64),
    ("products", ["rb"]), ("since", "2025-01-01"),
    ("frequencies", ["1m"]), ("strategies", ["trend"]),
])
def test_manifest_rejects_drift(tmp_path, field, value):
    manifest, universe = fixture_manifest(tmp_path)
    manifest[field] = value
    with pytest.raises(ValueError):
        validate_manifest(manifest, head="a" * 40, root=tmp_path, universe=universe)


def test_write_once_preserves_unknown_attempt(tmp_path):
    path = tmp_path / "attempt.json"
    write_once(path, {"state": "UNKNOWN", "retry_allowed": False})
    with pytest.raises(FileExistsError):
        write_once(path, {"state": "RETRY"})
    assert json.loads(path.read_text())["state"] == "UNKNOWN"


def test_campaign_lock_rejects_second_writer(tmp_path):
    with exclusive_campaign(tmp_path):
        with pytest.raises(ValueError, match="P0_CAMPAIGN_BUSY"):
            with exclusive_campaign(tmp_path):
                pass
    with exclusive_campaign(tmp_path):
        pass


def test_product_serial_base_before_fusion():
    products = [f"p{index}" for index in range(60)]
    order = stage_order(products)
    assert len(order) == len(set(order)) == 720
    assert all(item[0] == "p0" for item in order[:12])
    assert all(item[2] in ("trend", "oscillation") for item in order[:8])
    assert all(item[2] == "dual_fusion" for item in order[8:12])
    assert order[12][0] == "p1"


@pytest.mark.parametrize("product,frequency,strategy", [
    ("foreign", "5m", "trend"), ("rb", "1m", "trend"),
    ("rb", "5m", "main_rise"), ("../rb", "5m", "trend"),
])
def test_stage_rejects_scope_and_path_escape(product, frequency, strategy):
    with pytest.raises(ValueError, match="P0_STAGE_SCOPE_INVALID"):
        stage_key(product, frequency, strategy, ["rb"])


def test_symlink_assets_and_stage_escape_rejected(tmp_path):
    from scripts.newow_p0_candidate import safe_path
    root = tmp_path / "candidate"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "assets").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        safe_path(root / "assets" / "rb-5m-trend", root)
    with pytest.raises(OSError):
        write_once(root / "assets" / "attempt.json", {"state": "UNKNOWN"})
    assert not (outside / "attempt.json").exists()


def test_symlink_final_attempt_preserved(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("original")
    link = tmp_path / "attempt.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_once(link, {"state": "UNKNOWN"})
    assert target.read_text() == "original"


def campaign_fixture(tmp_path, monkeypatch):
    import sys
    from scripts import newow_p0_serial_campaign as campaign
    root = tmp_path / "worktree"
    output = root / "outputs" / "candidate"
    output.mkdir(parents=True)
    manifest = output / "candidate.json"
    body = {"products": ["rb"]}
    monkeypatch.setattr("scripts.newow_p0_candidate._freeze", lambda _: (body, root))
    write_once(manifest, body)
    write_once(output / "bootstrap-completed.json", {
        "manifest_sha256": sha256(manifest.read_bytes()).hexdigest()})
    monkeypatch.setattr(sys, "argv", ["campaign", "--worktree", str(root),
        "--manifest", str(manifest), "--output", str(output)])
    return campaign, output, manifest


def test_campaign_unknown_dispatch_never_retries(tmp_path, monkeypatch):
    campaign, output, manifest = campaign_fixture(tmp_path, monkeypatch)
    stage = output / "assets" / "rb-5m-trend"
    write_once(stage / "dispatch-plan.json", {"state": "UNKNOWN"})
    calls = []
    monkeypatch.setattr(campaign.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match="P0_PRIOR_DISPATCH_STOP_NO_RETRY"):
        campaign.main()
    assert calls == []


def test_campaign_completed_artifact_drift_blocks(tmp_path, monkeypatch):
    campaign, output, manifest = campaign_fixture(tmp_path, monkeypatch)
    stage = output / "assets" / "rb-5m-trend"
    artifact = stage / "plan.json"
    write_once(artifact, {"frozen": True})
    write_once(stage / "dispatch-plan-completed.json", {
        "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        "artifact_sha256": sha256(artifact.read_bytes()).hexdigest()})
    artifact.write_text('{"frozen":false}')
    monkeypatch.setattr(campaign.subprocess, "run", lambda *a, **k: pytest.fail("must not dispatch"))
    with pytest.raises(ValueError, match="P0_COMPLETED_DISPATCH_DRIFT"):
        campaign.main()


def test_campaign_command_failure_stops_preserving_unknown(tmp_path, monkeypatch):
    from types import SimpleNamespace
    campaign, output, manifest = campaign_fixture(tmp_path, monkeypatch)
    calls = []
    def fail(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(campaign.subprocess, "run", fail)
    assert campaign.main() == 7
    assert len(calls) == 1
    stage = output / "assets" / "rb-5m-trend"
    assert json.loads((stage / "dispatch-plan.json").read_text())["state"] == "UNKNOWN"
    assert not (stage / "dispatch-plan-completed.json").exists()
    with pytest.raises(ValueError, match="P0_PRIOR_DISPATCH_STOP_NO_RETRY"):
        campaign.main()
    assert len(calls) == 1


def test_campaign_only_skips_exact_complete_commands(tmp_path, monkeypatch):
    campaign, output, manifest = campaign_fixture(tmp_path, monkeypatch)
    for product, frequency, strategy in stage_order(["rb"]):
        stage = output / "assets" / f"{product}-{frequency}-{strategy}"
        for command, name in (("plan", "plan.json"), ("build", "native-report.json"), ("readback", "readback.json")):
            artifact = stage / name
            write_once(artifact, {"native": command})
            write_once(stage / f"dispatch-{command}-completed.json", {
                "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                "artifact_sha256": sha256(artifact.read_bytes()).hexdigest()})
    monkeypatch.setattr(campaign.subprocess, "run", lambda *a, **k: pytest.fail("must skip exact completion"))
    assert campaign.main() == 0


def test_campaign_stop_after_product_preserves_full_expected_matrix(tmp_path, monkeypatch, capsys):
    import sys
    campaign, output, manifest = campaign_fixture(tmp_path, monkeypatch)
    body = {"products": ["rb", "hc"]}
    manifest.write_text(json.dumps(body))
    (output / "bootstrap-completed.json").write_text(json.dumps({"manifest_sha256": sha256(manifest.read_bytes()).hexdigest()}))
    monkeypatch.setattr("scripts.newow_p0_candidate._freeze", lambda _: (body, output.parents[1]))
    sys.argv.extend(["--stop-after-product", "rb"])
    for product, frequency, strategy in stage_order(["rb"]):
        stage = output / "assets" / f"{product}-{frequency}-{strategy}"
        for command, name in (("plan", "plan.json"), ("build", "native-report.json"), ("readback", "readback.json")):
            artifact = stage / name
            write_once(artifact, {"native": command})
            write_once(stage / f"dispatch-{command}-completed.json", {
                "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                "artifact_sha256": sha256(artifact.read_bytes()).hexdigest()})
    monkeypatch.setattr(campaign.subprocess, "run", lambda *a, **k: pytest.fail("must stop before hc"))
    assert campaign.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PARTIAL_NATIVE_COMPLETION"
    assert result["expected_streams"] == 720 and result["completed_streams"] == 12
    assert not (output / "assets" / "hc-5m-trend").exists()


@pytest.mark.parametrize("reason", ["P0_SCOPE_INVALID", "SOURCE_BUSY", "REFERENCE_QUERY_INVALID", "NEWOW_DATA_UNAVAILABLE", "MARKET_SOURCE_MISSING"])
def test_safe_error_allows_only_sanitized_domain_codes(reason):
    from scripts.newow_p0_candidate import safe_error_reason
    assert safe_error_reason(ValueError(reason)) == reason


@pytest.mark.parametrize("reason", ["postgres://owner:SECRET@localhost/private", "P0_ERROR\nSECRET", "SOURCE_https://SECRET.invalid", "select * from private", "Traceback (most recent call last): SECRET"])
def test_safe_error_never_emits_secret_sql_url_or_stack(reason):
    from scripts.newow_p0_candidate import safe_error_reason
    assert safe_error_reason(ValueError(reason)) == "P0_UNCLASSIFIED_STOP_READBACK_REQUIRED"
