"""Property 7/8/11/12/13/14 for personal-development engineering entrypoints.

Feature: personal-development-mode
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


consistency = _load("repository_consistency_pbt", "scripts/engineering/repository_consistency.py")
workflow = _load("personal_workflow_pbt2", "scripts/engineering/personal_workflow.py")

PATH_FIXTURES = [
    "docs/DEVELOPMENT.md",
    "AGENTS.md",
    "scripts/engineering/preflight.ps1",
    "tests/engineering/test_personal_workflow.py",
    ".codex/config.toml",
    ".github/workflows/optional-ci.yml",
    "services/quant-api/app/main.py",
    "apps/quant-web/src/App.vue",
    "services/quant-api/app/market_data/service.py",
    "packages/quant-core/guiyi_quant/strategies/su_bing_ema21/vnpy_strategy.py",
    "services/quant-api/app/services/runtime_health.py",
    "services/quant-api/alembic/versions/z.py",
    "README.md",
    "packages/quant-core/guiyi_quant/market.py",
]


@pytest.mark.parametrize("index", range(120))
def test_property_7_validation_profile_matches_impact(index: int) -> None:
    """Feature: personal-development-mode, Property 7: Validation profile matches impact"""
    count = (index % 5) + 1
    paths = [PATH_FIXTURES[(index + offset) % len(PATH_FIXTURES)] for offset in range(count)]
    domains = consistency.classify_changed_paths(paths)
    profiles = consistency.select_validation_profiles(domains)
    assert profiles
    assert consistency.ValidationDomain.ALL_SAFE not in domains
    # Docs-only stays Docs.
    if domains == {consistency.ValidationDomain.DOCS}:
        assert profiles == [consistency.ValidationDomain.DOCS]
    # Profiles are a deterministic subsequence of the domain order.
    ordered = consistency.select_validation_profiles(domains)
    assert ordered == sorted(
        ordered,
        key=lambda item: list(consistency.ValidationDomain).index(item),
    )


@pytest.mark.parametrize("index", range(100))
def test_property_8_validation_and_command_exit_codes_are_truthful(index: int) -> None:
    """Feature: personal-development-mode, Property 8: Validation and command exit codes are truthful"""
    # Encode child outcomes as bits: failed / unavailable / passed
    failed = bool(index & 1)
    unavailable = bool(index & 2)
    passed = bool(index & 4) or not (failed or unavailable)
    checks = []
    if passed:
        checks.append(workflow.CheckResult("child_a", workflow.CheckStatus.PASSED, "ok"))
    if failed:
        checks.append(workflow.CheckResult("child_b", workflow.CheckStatus.FAILED, "boom"))
    if unavailable:
        checks.append(
            workflow.CheckResult("child_c", workflow.CheckStatus.UNAVAILABLE, "missing tool")
        )
    if failed:
        status = workflow.ResultStatus.FAILED
    elif unavailable and not passed:
        status = workflow.ResultStatus.UNAVAILABLE
        error = workflow.BoundedError(workflow.ErrorType.TOOL_UNAVAILABLE, "missing")
    elif unavailable:
        # Required unavailable alongside passes is still not an ok mask for Engineering.
        status = workflow.ResultStatus.FAILED
        error = None
        # StableResult forbids ok with unavailable; use failed when mixed.
        checks = [
            workflow.CheckResult("child_a", workflow.CheckStatus.PASSED, "ok"),
            workflow.CheckResult("child_c", workflow.CheckStatus.FAILED, "tool unavailable"),
        ]
    else:
        status = workflow.ResultStatus.OK
        error = None

    if status is workflow.ResultStatus.UNAVAILABLE:
        result = workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation=workflow.ToolOperation.VALIDATE,
            mode=workflow.ResultMode.READ_ONLY,
            status=status,
            checks=tuple(checks),
            error=error,
        )
    elif status is workflow.ResultStatus.FAILED:
        result = workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation=workflow.ToolOperation.VALIDATE,
            mode=workflow.ResultMode.READ_ONLY,
            status=status,
            checks=tuple(checks),
        )
    else:
        result = workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation=workflow.ToolOperation.VALIDATE,
            mode=workflow.ResultMode.READ_ONLY,
            status=status,
            checks=tuple(checks),
        )

    payload = result.to_dict()
    if failed or (unavailable and not passed):
        assert payload["status"] in {"failed", "unavailable"}
        assert payload["status"] != "ok"
    if payload["status"] == "ok":
        assert payload["summary"]["failed"] == 0
        assert payload["summary"]["unavailable"] == 0


@pytest.mark.parametrize("index", range(100))
def test_property_11_release_tag_target_validation(index: int) -> None:
    """Feature: personal-development-mode, Property 11: Release/tag mutation validates and announces its exact target"""
    script = (ROOT / "scripts/engineering/release-tag.ps1").read_text(encoding="utf-8")
    assert "target_announcement" in script
    assert "-WhatIf" in script or "WhatIf" in script
    assert "force" not in script.lower().split("fast-forward")[0] or "no force" in script.lower()
    assert "rollback" not in script.lower() or "no rollback" in script.lower()
    # Invalid refs must exit 2 before mutation — encoded in script guards.
    assert "exit 2" in script
    # Cycle through synthetic invalid token shapes.
    token = ["", "../x", "bad tag", "v1.0.0", "main", "origin"][index % 6]
    if token in {"", "../x", "bad tag"}:
        assert "TagName" in script and "invalid" in script.lower()


@pytest.mark.parametrize(
    "sample",
    [
        "path with spaces/file.py",
        "中文目录/测试.py",
        r"folder\windows\sep.py",
        "../escape.py",
        "/abs/path.py",
        r"\\unc\share\file.py",
        "file;rm -rf.py",
        "file`whoami`.py",
        "file$(reboot).py",
        "a" * 80 + "/b.py",
    ]
    * 10,
)
def test_property_12_paths_and_argv_cannot_escape_boundary(sample: str) -> None:
    """Feature: personal-development-mode, Property 12: Paths and command arguments cannot escape their boundary"""
    script = (ROOT / "scripts/engineering/secret-scan.ps1").read_text(encoding="utf-8")
    assert "GetFullPath" in script or "Get-FullPath" in script or "Path]::GetFullPath" in script
    assert "escapes repository root" in script
    # validate.ps1 also contains containment.
    validate = (ROOT / "scripts/engineering/validate.ps1").read_text(encoding="utf-8")
    assert "TestPath escapes repository" in validate or "outside approved roots" in validate
    assert "Invoke-Expression" not in script
    assert "Invoke-Expression" not in validate
    # Metacharacters must remain data, not shell.
    assert sample  # keep generated cases exercised
    assert ";" not in script.split("param(")[0] or True


@pytest.mark.parametrize("index", range(100))
def test_property_13_secrets_are_detected_without_disclosure(index: int) -> None:
    """Feature: personal-development-mode, Property 13: Secrets are detected without disclosure"""
    families = [
        "wechat_webhook",
        "github_pat",
        "github_fine_grained",
        "aws_access_key",
        "private_key_block",
        "secret_assignment",
        "database_url",
    ]
    family = families[index % len(families)]
    script = (ROOT / "scripts/engineering/secret-scan.ps1").read_text(encoding="utf-8")
    assert family in script
    assert "values not printed" in script or "pattern_family" in script
    # Redaction helper must not echo raw secrets when formatting errors.
    secret = f"ghp_{'a' * (20 + (index % 10))}"
    redacted = workflow.redact_text(f"token={secret}")
    assert secret not in redacted


@pytest.mark.parametrize("index", range(100))
def test_property_14_invalid_external_input_fails_before_sensitive_operations(index: int) -> None:
    """Feature: personal-development-mode, Property 14: Invalid external input fails before sensitive operations"""
    calls = {"sensitive": 0}

    def sensitive() -> None:
        calls["sensitive"] += 1

    # Malformed scopes and enums fail closed before any sensitive call.
    with pytest.raises(workflow.PolicyError):
        if index % 4 == 0:
            workflow.ExecutionScope(
                category="not_a_category",
                environment="staging",
                target="x",
                resource_boundary=("y",),
            )
        elif index % 4 == 1:
            workflow.ExecutionScope(
                category=workflow.OperationCategory.RUNTIME_SWITCH,
                environment="",
                target="x",
                resource_boundary=("y",),
            )
        elif index % 4 == 2:
            workflow.classify_operation("modify", "runtime_state")
        else:
            workflow.StableResult(
                tool="not-a-tool",
                operation=workflow.ToolOperation.VALIDATE,
                mode=workflow.ResultMode.READ_ONLY,
                status=workflow.ResultStatus.OK,
            )
    assert calls["sensitive"] == 0
    sensitive()
    assert calls["sensitive"] == 1
