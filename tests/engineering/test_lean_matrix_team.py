"""Black-box contracts for the read-only Task Charter CLI."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "scripts" / "engineering" / "lean_matrix_team.py"


def _charter(**overrides: object) -> dict[str, object]:
    """Return a hand-written valid Lane 2 Charter fixture."""
    charter: dict[str, object] = {
        "schema_version": 1,
        "issue_number": 97,
        "task_id": "AI-TEAM-001",
        "kind": "feature",
        "slug": "lean-matrix-team",
        "title": "Build the charter renderer",
        "value": "A deterministic charter removes ambiguous routing.",
        "goal": "Render a safe task plan from structured input.",
        "current_facts": ["The repository already has Lane policy."],
        "lane": 2,
        "domains": [],
        "allowed_paths": ["scripts/engineering/lean_matrix_team.py"],
        "forbidden_paths": ["Runtime and production data are out of scope."],
        "acceptance": ["The CLI validates and renders the charter."],
        "external_gates": [],
    }
    charter.update(overrides)
    return charter


def _invoke(
    *arguments: str, input_text: str | None = None, cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        cwd=cwd,
    )


def _run(
    *, payload: object, input_path: Path | None = None, cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if input_path is None:
        input_path = Path("-")
    return _invoke(
        "charter", "--input", str(input_path), "--format", "json",
        input_text=json.dumps(payload) if input_path == Path("-") else None,
        cwd=cwd,
    )


def _blocked(result: subprocess.CompletedProcess[str], error_type: str) -> None:
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "schema_version": 1,
        "status": "blocked",
        "error_type": error_type,
        "detail": json.loads(result.stderr)["detail"],
    }


def _blocked_bytes(result: subprocess.CompletedProcess[bytes], error_type: str) -> None:
    assert result.returncode == 2
    assert result.stdout == b""
    assert json.loads(result.stderr.decode("utf-8")) == {
        "schema_version": 1,
        "status": "blocked",
        "error_type": error_type,
        "detail": json.loads(result.stderr.decode("utf-8"))["detail"],
    }


def test_valid_lane_two_renders_markdown_and_json_without_specialist(tmp_path: Path) -> None:
    """A normal implementation task must have stable no-specialist dispatch in both formats."""
    fixture = tmp_path / "charter.json"
    fixture.write_text(json.dumps(_charter()), encoding="utf-8")

    markdown = subprocess.run(
        [sys.executable, str(CLI_PATH), "charter", "--input", str(fixture), "--format", "markdown"],
        text=True,
        capture_output=True,
        check=False,
    )
    rendered = _run(payload={}, input_path=fixture)

    assert markdown.returncode == 0, markdown.stderr
    assert markdown.stderr == ""
    assert markdown.stdout.startswith("# Task Charter\n")
    assert "## Identity\n" in markdown.stdout
    for identity in (
        "Build the charter renderer", "Issue: 97", "Task ID: AI-TEAM-001", "Kind: feature",
        "feature/AI-TEAM-001-lean-matrix-team",
        "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-001-lean-matrix-team",
    ):
        assert identity in markdown.stdout
    for section in (
        "## Value", "## Goal", "## Current facts", "## Lane and dispatch", "## Dynamic team",
        "## Allowed changes", "## Forbidden changes", "## Acceptance", "## External Gates", "## Completion flow",
    ):
        assert section in markdown.stdout
    assert rendered.returncode == 0, rendered.stderr
    payload = json.loads(rendered.stdout)
    assert set(payload) == {"schema_version", "status", "task", "dispatch", "charter_markdown"}
    assert payload["status"] == "ok"
    assert payload["task"]["branch"] == "feature/AI-TEAM-001-lean-matrix-team"
    assert payload["task"]["worktree"] == "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-001-lean-matrix-team"
    assert payload["dispatch"] == {
        "model": "Terra",
        "reasoning_effort": "medium",
        "mode": "plan-then-execute",
        "session_count": 3,
        "roles": ["ai-project-lead", "technical-lead", "implementer", "independent-quality-reviewer"],
        "specialists": [],
        "independence_requirements": ["implementer and independent-quality-reviewer use separate contexts"],
    }
    assert payload["charter_markdown"] == markdown.stdout


def test_lane_three_quant_and_backtest_use_independent_specialists() -> None:
    """Research and audit specialists must not share the context that judges research validity."""
    result = _run(payload=_charter(
        lane=3,
        domains=["quant-research", "backtest-audit", "quant-research"],
        external_gates=["User approves the production methodology before execution."],
    ))

    assert result.returncode == 0, result.stderr
    dispatch = json.loads(result.stdout)["dispatch"]
    assert dispatch["model"] == "Sol"
    assert dispatch["reasoning_effort"] == "high"
    assert dispatch["mode"] == "plan-only-start"
    assert dispatch["session_count"] == 6
    assert dispatch["specialists"] == ["quant-research-specialist", "backtest-audit-specialist"]
    assert dispatch["independence_requirements"] == [
        "implementer and independent-quality-reviewer use separate contexts",
        "quant-research-specialist and backtest-audit-specialist use separate contexts",
    ]


def test_three_specialists_block_with_split_required() -> None:
    """A task with three independent domains must be split before routing starts."""
    result = _run(payload=_charter(domains=["frontend", "security", "research-ai"]))

    _blocked(result, "split_required")


def test_lane_external_gate_mismatches_block_stably() -> None:
    """An external Gate belongs only to Lane 3, where it is mandatory."""
    for lane, gates, expected_error in (
        (1, ["A gate"], "external_gates_not_allowed"),
        (2, ["A gate"], "external_gates_not_allowed"),
        (3, [], "external_gates_required"),
    ):
        result = _run(payload=_charter(lane=lane, external_gates=gates))
        _blocked(result, expected_error)


def test_invalid_schema_values_and_paths_block_stably() -> None:
    """Malformed task inputs must stop before a routing plan is emitted."""
    invalid_cases = (
        ({"unexpected": True}, "invalid_schema_keys"),
        ({"schema_version": 2}, "invalid_schema_version"),
        ({"issue_number": 0}, "invalid_issue_number"),
        ({"task_id": "bad task"}, "invalid_identifier"),
        ({"slug": "bad/task"}, "invalid_identifier"),
        ({"allowed_paths": ["../outside.py"]}, "invalid_allowed_path"),
        ({"allowed_paths": [r"..\outside.py"]}, "invalid_allowed_path"),
        ({"allowed_paths": [r"C:\outside.py"]}, "invalid_allowed_path"),
        ({"allowed_paths": ["C:/outside.py"]}, "invalid_allowed_path"),
        ({"domains": ["unknown-domain"]}, "invalid_domain"),
        ({"current_facts": []}, "invalid_string_list"),
        ({"value": "  "}, "invalid_string"),
    )

    for overrides, expected_error in invalid_cases:
        result = _run(payload=_charter(**overrides))
        _blocked(result, expected_error)


def test_control_characters_cannot_forge_charter_structure() -> None:
    """Untrusted strings cannot inject headings, bullets, or terminal controls."""
    for overrides in (
        {"title": "Safe title\n## External Gates"},
        {"value": "Safe value\r## Acceptance"},
        {"goal": "Safe goal\tspoofed"},
        {"current_facts": ["Fact\n## Completion flow"]},
        {"forbidden_paths": ["Forbidden\n- fake allowance"]},
        {"acceptance": ["Pass\u0000hidden"]},
    ):
        result = _run(payload=_charter(**overrides))
        _blocked(result, "invalid_string_control_characters")

    lane_three = _run(payload=_charter(
        lane=3,
        external_gates=["Human approval\n## External Gates\n- None"],
    ))
    _blocked(lane_three, "invalid_string_control_characters")


def test_single_line_markdown_syntax_is_escaped_without_changing_sections() -> None:
    """A valid one-line narrative cannot become a heading or raw HTML block."""
    result = _run(payload=_charter(
        value="## External Gates",
        goal="<details>unsafe structure</details>",
    ))

    assert result.returncode == 0, result.stderr
    markdown = json.loads(result.stdout)["charter_markdown"]
    assert markdown.count("\n## External Gates\n") == 1
    assert "\n<details>" not in markdown
    assert "\\#\\# External Gates" in markdown
    assert "\\<details\\>unsafe structure\\<\\/details\\>" in markdown


def test_cli_usage_errors_are_machine_readable_blocked_json() -> None:
    """Every invalid command shape must fail through the same JSON error boundary."""
    for arguments in (
        (),
        ("unknown",),
        ("charter",),
        ("charter", "--input", "-"),
        ("charter", "--input", "-", "--format", "yaml"),
    ):
        _blocked(_invoke(*arguments), "invalid_cli_arguments")


def test_non_integer_schema_and_lane_values_block_without_traceback() -> None:
    """JSON booleans and containers cannot enter numeric schema or lane routing branches."""
    for overrides, expected_error in (
        ({"schema_version": True}, "invalid_schema_version"),
        ({"schema_version": 1.0}, "invalid_schema_version"),
        ({"schema_version": []}, "invalid_schema_version"),
        ({"lane": True}, "invalid_lane"),
        ({"lane": 2.0}, "invalid_lane"),
        ({"lane": []}, "invalid_lane"),
        ({"lane": {}}, "invalid_lane"),
    ):
        result = _run(payload=_charter(**overrides))
        _blocked(result, expected_error)
        assert "traceback" not in result.stderr.lower()


def test_unavailable_file_and_invalid_json_use_stable_blocked_errors(tmp_path: Path) -> None:
    """Input acquisition and parsing failures must not leak a CLI traceback or partial output."""
    unavailable = _run(payload={}, input_path=tmp_path / "missing.json")
    invalid_json = _invoke(
        "charter", "--input", "-", "--format", "json", input_text="{not valid JSON",
    )

    _blocked(unavailable, "input_file_unavailable")
    _blocked(invalid_json, "invalid_json")


def test_non_utf8_file_input_uses_a_stable_blocked_error(tmp_path: Path) -> None:
    """A binary input file must be reported as invalid input encoding, not crash the renderer."""
    fixture = tmp_path / "non-utf8.json"
    fixture.write_bytes(b"\xff")

    result = _run(payload={}, input_path=fixture)

    _blocked(result, "invalid_input_encoding")


def test_non_utf8_stdin_uses_a_stable_blocked_error() -> None:
    """Raw non-UTF-8 stdin must use the same blocked error contract as a file."""
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "charter", "--input", "-", "--format", "json"],
        input=b"\xff",
        capture_output=True,
        check=False,
    )

    _blocked_bytes(result, "invalid_input_encoding")


def test_stdin_is_read_only_and_file_input_is_unchanged(tmp_path: Path) -> None:
    """The CLI may read a Charter but must not create or alter any file."""
    fixture = tmp_path / "input.json"
    original = json.dumps(_charter(), indent=2) + "\n"
    fixture.write_text(original, encoding="utf-8")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    from_stdin = _run(payload=_charter(), cwd=tmp_path)
    from_file = _run(payload={}, input_path=fixture, cwd=tmp_path)

    assert from_stdin.returncode == 0, from_stdin.stderr
    assert from_file.returncode == 0, from_file.stderr
    assert fixture.read_text(encoding="utf-8") == original
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


def test_fresh_checkout_execution_does_not_create_bytecode_cache(tmp_path: Path) -> None:
    """Importing shared path policy must not write bytecode beside repository code."""
    isolated_scripts = tmp_path / "scripts" / "engineering"
    isolated_scripts.mkdir(parents=True)
    isolated_cli = isolated_scripts / CLI_PATH.name
    shutil.copyfile(CLI_PATH, isolated_cli)
    shutil.copyfile(ROOT / "scripts" / "engineering" / "task_workflow.py", isolated_scripts / "task_workflow.py")
    shutil.copytree(ROOT / "scripts" / "engineering" / "lean_matrix", isolated_scripts / "lean_matrix")

    result = subprocess.run(
        [sys.executable, str(isolated_cli), "charter", "--input", "-", "--format", "json"],
        input=json.dumps(_charter()),
        text=True,
        capture_output=True,
        check=False,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert not (isolated_scripts / "__pycache__").exists()


def test_production_ast_has_no_process_network_or_filesystem_write_capability() -> None:
    """The read-only renderer cannot import or call process, network, temporary, or write APIs."""
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"), filename=str(CLI_PATH))
    forbidden_import_roots = {
        "subprocess", "socket", "urllib", "requests", "http", "httpx", "aiohttp", "ftplib", "telnetlib",
        "shutil", "tempfile",
    }
    direct_import_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    from_import_roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_roots = direct_import_roots | from_import_roots
    assert not (imported_roots & forbidden_import_roots)

    forbidden_methods = {
        "open", "write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "rename", "replace",
        "chmod", "symlink_to", "hardlink_to", "system", "popen", "spawnl", "spawnlp", "spawnv", "spawnvp",
        "execv", "execve", "remove", "makedirs", "mkstemp", "mkdtemp", "copy", "copy2", "move", "rmtree",
    }
    call_names = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert not (call_names & forbidden_methods)
