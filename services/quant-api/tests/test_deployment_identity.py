import plistlib
import pytest

from app.services.deployment_identity import SERVICE_LABELS, deployment_identity_health


@pytest.mark.parametrize("defect, expected", [(None, "matched"), ("mixed", "mismatch"),
    ("absent", "unknown"), ("permission", "unknown"), ("unloaded", "unknown"),
    ("loaded_tamper", "unknown"), ("argument_tamper", "unknown"), ("invalid_commit", "unknown"),
    ("invalid_plist", "unknown"), ("probe_permission", "unknown"),
    ("weekly_unloaded", "unknown")])
def test_installed_and_loaded_exact_binding(tmp_path, defect, expected):
    home = tmp_path / "home"
    directory = home / "Library/LaunchAgents"
    directory.mkdir(parents=True)
    root = tmp_path / "runtime"
    root.mkdir()
    other_root = tmp_path / "other"
    other_root.mkdir()
    commit = "a" * 40
    outputs = {}
    for name, service in SERVICE_LABELS.items():
        selected_root = other_root if defect == "mixed" and name == "live_market" else root
        label = f"com.guiyi.quant-{service}"
        args = ("/bin/bash", str(home / "Library/Application Support/GuiyiQuant/run-local-service.sh"), service)
        if service == "weekly-audit":
            args = ("/bin/bash", str(selected_root / "scripts/ops/macos/run-local-service.sh"), "weekly-audit-scheduled")
        env = {"GUIYI_PROJECT_ROOT": str(selected_root), "GUIYI_RUNTIME_COMMIT": commit}
        payload = {"Label": label, "WorkingDirectory": str(selected_root), "ProgramArguments": list(args),
            "EnvironmentVariables": env}
        path = directory / f"{label}.plist"
        path.write_bytes(plistlib.dumps(payload))
        if name == "live_market":
            if defect == "absent":
                path.unlink()
            if defect == "permission":
                path.chmod(0o666)
            if defect == "invalid_plist":
                path.write_bytes(b"invalid")
            if defect == "argument_tamper":
                args = ("/bin/bash", "/untrusted/script", service)
        loaded_commit = "b" * 40 if defect == "loaded_tamper" and name == "live_market" else commit
        outputs[label] = (f"{label} = {{\n state = running\n pid = 42\n working directory = {selected_root}\n"
            + " arguments = {\n" + "\n".join(args) + "\n }\n environment = {\n"
            + f" GUIYI_PROJECT_ROOT => {selected_root}\n GUIYI_RUNTIME_COMMIT => {loaded_commit}\n }}\n}}")
    def reader(label, *, root):
        if defect == "probe_permission":
            raise PermissionError("secret password")
        if defect == "weekly_unloaded" and label.endswith("-weekly-audit"):
            return None
        if defect == "unloaded" and label.endswith("-live"):
            return None
        return outputs[label]
    result = deployment_identity_health(root=root, commit="malformed" if defect == "invalid_commit" else commit,
        home=home, service_reader=reader)
    assert result["status"] == expected
    assert "EnvironmentVariables" not in str(result)
    assert "arguments" not in str(result)


def test_probe_permission_failure_is_unknown(tmp_path):
    def denied(*args, **kwargs): raise PermissionError("secret password")
    result = deployment_identity_health(root=tmp_path, commit="a" * 40, home=tmp_path,
        service_reader=denied)
    assert result["status"] == "unknown"
    assert "password" not in str(result)


@pytest.mark.parametrize("marker, probe_error, expected", [(False, False, "disabled"),
    (True, False, "unknown"), (False, True, "unknown")])
def test_optional_explicit_absence_requires_missing_marker(tmp_path, marker, probe_error, expected):
    (tmp_path / "Library/LaunchAgents").mkdir(parents=True)
    (tmp_path / ".run").mkdir()
    if marker:
        (tmp_path / ".run/weekly-audit-enabled").write_text("enabled\n")
    def reader(label, *, root):
        if probe_error:
            raise PermissionError("private")
        return None
    result = deployment_identity_health(root=tmp_path, commit="a" * 40, home=tmp_path,
        service_reader=reader)
    assert result["services"]["weekly_audit"]["status"] == expected
    assert result["services"]["live_market"]["status"] == ("unknown" if probe_error else "disabled")


def test_optional_missing_plist_but_loaded_service_is_unknown(tmp_path):
    (tmp_path / "Library/LaunchAgents").mkdir(parents=True)
    result = deployment_identity_health(root=tmp_path, commit="a" * 40, home=tmp_path,
        service_reader=lambda *args, **kwargs: "loaded unverified definition")
    assert result["services"]["weekly_audit"]["status"] == "unknown"
    assert result["services"]["reference_worker"]["status"] == "unknown"


@pytest.mark.parametrize("marker", [None, "market-runtime-enabled", "alert-runtime-enabled"])
def test_first_install_explicit_absence_and_real_marker(tmp_path, marker):
    (tmp_path / "Library/LaunchAgents").mkdir(parents=True)
    (tmp_path / ".run").mkdir()
    if marker:
        (tmp_path / ".run" / marker).write_text("enabled\n")
    result = deployment_identity_health(root=tmp_path, commit="a" * 40, home=tmp_path,
        service_reader=lambda *args, **kwargs: None)
    assert result["services"]["live_market"]["status"] == (
        "unknown" if marker == "market-runtime-enabled" else "disabled")
    assert result["services"]["alert"]["status"] == (
        "unknown" if marker == "alert-runtime-enabled" else "disabled")
    assert result["status"] == ("unknown" if marker else "matched")
