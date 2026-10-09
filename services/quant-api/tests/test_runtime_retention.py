from pathlib import Path

import pytest

from app.runtime_retention import build_cleanup_plan


class Backend:
    def __init__(self):
        self.references = {}
        self.unknown = False
    def candidate_identity(self, root):
        return {"root": str(root), "commit": "a" * 40, "tag": "v1.2.3"}
    def references_by_root(self, roots):
        if self.unknown:
            raise ValueError("private environment must not escape")
        return {str(root): self.references.get(str(root), []) for root in roots}


def test_exact_cleanup_candidates_with_any_reference_are_retained(tmp_path):
    backend = Backend()
    one, two, three = (tmp_path / name for name in ("binding", "process", "unused"))
    for root in (one, two, three):
        root.mkdir()
    backend.references = {str(one): ["binding:live"], str(two): ["loaded:com.guiyi.quant-alert"]}
    plan = build_cleanup_plan((one, two, three), backend=backend)
    assert plan["dry_run"] is True
    assert [item["status"] for item in plan["targets"]] == ["retained", "retained", "eligible"]
    assert len(plan["plan_sha256"]) == 64


def test_unknown_probe_blocks_cleanup_without_leaking_output(tmp_path):
    backend = Backend()
    backend.unknown = True
    plan = build_cleanup_plan((tmp_path,), backend=backend)
    assert plan["targets"][0]["status"] == "blocked"
    assert "environment must not escape" not in str(plan)


def test_invalid_or_duplicate_target_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_cleanup_plan((Path("relative"),), backend=Backend())
    with pytest.raises(ValueError):
        build_cleanup_plan((tmp_path, tmp_path), backend=Backend())


def test_host_reader_keeps_registry_plist_and_loaded_references(tmp_path, monkeypatch):
    import plistlib
    from app.runtime_bindings import BindingRegistry, ServiceBinding, write_bindings
    from app.runtime_retention import RetentionBackend
    root = tmp_path / "release"
    root.mkdir()
    binding = ServiceBinding("live", str(root), "v1.2.3", "a" * 40, 1, False,
        {key: "c" * 64 for key in ("db", "live", "input", "formula", "reference", "launcher")})
    write_bindings(BindingRegistry(1, {"live": binding}), home=tmp_path, expected_sha256=None)
    directory = tmp_path / "Library/LaunchAgents"
    directory.mkdir(parents=True)
    label = binding.label
    (directory / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label,
        "WorkingDirectory": str(root), "ProgramArguments": ["/bin/bash", "/stable/launcher", "live"],
        "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(root), "IGNORED_SECRET": "not-for-output"}}))
    backend = RetentionBackend(home=tmp_path)
    def command(args):
        if args[0] == "/bin/launchctl":
            return "PID\tStatus\tLabel\n42\t0\t" + label
        if args[0] == "/usr/sbin/lsof":
            return "p999\nfcwd\nn/unrelated"
        return "999 /usr/bin/python unrelated"
    monkeypatch.setattr(backend, "_command", command)
    observed = (f"{label} = {{\n working directory = {root}\n arguments = {{\n/bin/bash\n/stable/launcher\nlive\n}}\n"
                f"environment = {{\nGUIYI_PROJECT_ROOT => {root}\nIGNORED_SECRET => not-for-output\n}}\n}}")
    monkeypatch.setattr("app.market_data.captured_recovery_runtime._read_launchd_service", lambda *a, **k: observed)
    references = backend.references_by_root((root,))
    assert references[str(root)] == ["binding:live", f"plist:{label}", f"loaded:{label}"]
    assert "not-for-output" not in str(references)


def test_foreign_repository_worktree_is_never_eligible(tmp_path, monkeypatch):
    from app.runtime_retention import RetentionBackend, RetentionError
    root = tmp_path / "foreign-release"
    root.mkdir()
    (root / ".git").write_text("gitdir: fixture")
    foreign = tmp_path / "foreign-common"
    project = tmp_path / "project-common"
    foreign.mkdir()
    project.mkdir()
    monkeypatch.setattr("app.runtime_retention._git", lambda cwd, *args: str(foreign if cwd == root else project))
    with pytest.raises(RetentionError, match="REPOSITORY_IDENTITY_INVALID"):
        RetentionBackend().candidate_identity(root)
