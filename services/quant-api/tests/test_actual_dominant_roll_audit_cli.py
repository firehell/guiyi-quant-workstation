from __future__ import annotations

import builtins
from datetime import date
import importlib.util
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "rqdata_actual_dominant_roll_audit_v2.py"
)


class _SessionContext:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_args: object) -> None:
        self.exited = True


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "rqdata_actual_dominant_roll_audit_v2_cli",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_load_and_parser_do_not_import_app_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_imports: list[str] = []
    original_import = builtins.__import__

    def tracked_import(name: str, *args, **kwargs):
        if name == "app" or name.startswith("app."):
            app_imports.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracked_import)

    module = _load_script()
    args = module.build_parser().parse_args(["verify"])

    assert args.command == "verify"
    assert app_imports == []


def test_main_loads_dotenv_before_importing_app_runtime_modules(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    events: list[str] = []
    project_root = tmp_path / "project"
    project_root.mkdir()
    output_dir = tmp_path / "runtime-order-output"

    class FakeConfig:
        def __init__(self, **values: object) -> None:
            self.__dict__.update(values)

    result = SimpleNamespace(
        summary={
            "status": module.ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED,
            "direct_postgresql": True,
            **module.WRITE_BOUNDARY_FLAGS,
        }
    )
    service_module = ModuleType(
        "app.services.rqdata_ingest.actual_dominant_roll_audit_v2"
    )
    service_module.ActualDominantRollAuditConfig = FakeConfig  # type: ignore[attr-defined]
    service_module.run_actual_dominant_roll_audit = (  # type: ignore[attr-defined]
        lambda *_args: result
    )
    service_module.write_actual_dominant_roll_reports = (  # type: ignore[attr-defined]
        lambda _result, output: {"audit_evidence.json": output / "audit_evidence.json"}
    )
    session_module = ModuleType("app.db.session")
    session_module.SessionLocal = _SessionContext  # type: ignore[attr-defined]

    for package_name in ("app", "app.services", "app.services.rqdata_ingest", "app.db"):
        package = ModuleType(package_name)
        package.__path__ = []  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(
        sys.modules,
        "app.services.rqdata_ingest.actual_dominant_roll_audit_v2",
        service_module,
    )
    monkeypatch.setitem(sys.modules, "app.db.session", session_module)

    original_import = builtins.__import__

    def tracked_import(name: str, *args, **kwargs):
        if name == "app" or name.startswith("app."):
            events.append(f"import:{name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracked_import)
    monkeypatch.setattr(
        module,
        "load_dotenv",
        lambda path, override: events.append(f"dotenv:{path}:{override}"),
    )

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(project_root),
            "--scan-mode",
            "full",
            "--output-dir",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["status"] == module.ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED
    assert captured.err == ""
    assert events[0] == f"dotenv:{project_root / '.env'}:False"
    assert "import:app.services.rqdata_ingest.actual_dominant_roll_audit_v2" in events
    assert "import:app.db.session" in events
    assert all(
        index > 0
        for index, event in enumerate(events)
        if event.startswith("import:app")
    )


def test_parser_exposes_only_verify_with_frozen_defaults() -> None:
    module = _load_script()

    args = module.build_parser().parse_args(["verify"])

    assert args.command == "verify"
    assert args.project_root == SCRIPT_PATH.parents[1]
    assert args.audit_end == date(2026, 7, 10)
    assert args.scan_mode == "quick"
    assert args.products_file == Path("data/universe/full_products_90.txt")
    assert args.product == []
    assert args.max_workers == 4
    assert args.output_dir == Path(
        "data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006"
    )
    assert not hasattr(args, "overwrite")


@pytest.mark.parametrize(
    "argv",
    [
        ["verify", "--audit-end", "not-a-date"],
        ["verify", "--scan-mode", "turbo"],
        ["verify", "--output-dir"],
    ],
)
def test_invalid_arguments_emit_one_compact_json_line(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    with pytest.raises(SystemExit) as exc_info:
        module.main(argv)

    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert captured.out == ""
    assert exc_info.value.code == 2
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["status"] == "INVALID_ARGUMENTS"
    assert payload["error_type"] == "ArgumentError"
    assert "usage:" not in captured.err.lower()
    assert payload["writes_database"] is False
    assert payload["calls_rqdata"] is False


def test_rejects_noncanonical_products_file_before_database_access(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(tmp_path),
            "--products-file",
            "data/universe/not-canonical.txt",
            "--output-dir",
            "reports/actual-roll",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert captured.out == ""
    assert exit_code == 2
    assert payload["status"] == "INVALID_PRODUCTS_FILE"
    assert payload["output_directory"] == str((tmp_path / "reports/actual-roll").resolve())
    assert payload["writes_database"] is False
    assert payload["writes_parquet"] is False
    assert payload["writes_manifest"] is False
    assert payload["writes_quality"] is False
    assert payload["calls_provider_api"] is False
    assert payload["calls_rqdata"] is False


def test_existing_output_directory_is_a_distinct_collision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    output_dir = tmp_path / "reports/actual-roll"
    output_dir.mkdir(parents=True)

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(tmp_path),
            "--output-dir",
            "reports/actual-roll",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert captured.out == ""
    assert exit_code == 3
    assert payload["status"] == "OUTPUT_EXISTS"
    assert payload["output_directory"] == str(output_dir.resolve())


def test_relative_output_directory_cannot_escape_project_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    access_attempts: list[str] = []
    db_module = ModuleType("app.db.session")

    def unexpected_session():
        access_attempts.append("database")
        raise AssertionError("database access must not occur")

    db_module.SessionLocal = unexpected_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.db.session", db_module)
    monkeypatch.setattr(
        module,
        "run_actual_dominant_roll_audit",
        lambda *_args: access_attempts.append("audit"),
    )
    monkeypatch.setattr(
        module,
        "write_actual_dominant_roll_reports",
        lambda *_args: access_attempts.append("writer"),
    )

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(tmp_path),
            "--output-dir",
            "../escaped",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    escaped = (tmp_path / "../escaped").resolve()
    assert captured.out == ""
    assert exit_code == 2
    assert payload["status"] == "INVALID_OUTPUT_DIRECTORY"
    assert payload["output_directory"] == str(escaped)
    assert access_attempts == []
    assert not escaped.exists()


def test_filtered_products_are_forwarded_to_a_smoke_only_audit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    session = _SessionContext()
    db_module = ModuleType("app.db.session")
    db_module.SessionLocal = lambda: session  # type: ignore[attr-defined]
    db_module.get_db = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.db.session", db_module)
    loaded_env: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        module,
        "load_dotenv",
        lambda path, override: loaded_env.append((path, override)),
        raising=False,
    )
    calls: dict[str, object] = {}

    def fake_run(config, received_session):
        calls["config"] = config
        calls["session"] = received_session
        return SimpleNamespace(
            summary={
                "status": module.ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED,
                "product_count": 2,
                "rank1_mapping_count": 8,
                "residual_count": 1,
                "hard_jm_residual_count": 1,
                "formal_residual_count": 0,
                "inventory_residual_count": 0,
                "direct_postgresql": True,
                **module.WRITE_BOUNDARY_FLAGS,
            }
        )

    def fake_write(result, output_dir):
        calls["result"] = result
        calls["output_dir"] = output_dir
        return {"audit_evidence.json": output_dir / "audit_evidence.json"}

    monkeypatch.setattr(module, "run_actual_dominant_roll_audit", fake_run, raising=False)
    monkeypatch.setattr(module, "write_actual_dominant_roll_reports", fake_write, raising=False)

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(tmp_path),
            "--scan-mode",
            "full",
            "--product",
            "jm",
            "--product",
            "rb",
            "--max-workers",
            "7",
            "--output-dir",
            "reports/filtered",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 4, captured.err
    payload = json.loads(captured.out)
    config = calls["config"]
    assert loaded_env == [(tmp_path / ".env", False)]
    assert config.project_root == tmp_path.resolve()
    assert config.products == ("jm", "rb")
    assert config.scan_mode == "full"
    assert config.max_workers == 7
    assert config.require_postgresql is True
    assert calls["session"] is session
    assert calls["output_dir"] == (tmp_path / "reports/filtered").resolve()
    assert session.entered is True
    assert session.exited is True
    assert payload["status"] == module.ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED


def test_verified_result_dispatches_reports_and_returns_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    project_root = tmp_path / "project"
    project_root.mkdir()
    session = _SessionContext()
    db_module = ModuleType("app.db.session")
    db_module.SessionLocal = lambda: session  # type: ignore[attr-defined]
    db_module.get_db = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.db.session", db_module)
    result = SimpleNamespace(
        summary={
            "status": module.ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED,
            "product_count": 90,
            "rank1_mapping_count": 12_345,
            "residual_count": 9,
            "hard_jm_residual_count": 0,
            "formal_residual_count": 0,
            "inventory_residual_count": 9,
            "direct_postgresql": True,
            **module.WRITE_BOUNDARY_FLAGS,
        }
    )
    calls: dict[str, object] = {}
    monkeypatch.setattr(module, "run_actual_dominant_roll_audit", lambda *_args: result)

    def fake_write(received_result, output_dir):
        calls["result"] = received_result
        calls["output_dir"] = output_dir
        return {
            "audit_evidence.json": output_dir / "audit_evidence.json",
            "ACTUAL_DOMINANT_ROLL_SUMMARY.md": output_dir
            / "ACTUAL_DOMINANT_ROLL_SUMMARY.md",
        }

    monkeypatch.setattr(module, "write_actual_dominant_roll_reports", fake_write)

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(project_root),
            "--scan-mode",
            "full",
            "--output-dir",
            str(tmp_path / "absolute-formal"),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    output_dir = (tmp_path / "absolute-formal").resolve()
    assert captured.err == ""
    assert exit_code == 0
    assert calls == {"result": result, "output_dir": output_dir}
    assert payload["status"] == module.ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED
    assert payload["output_directory"] == str(output_dir)
    assert payload["counts"] == {
        "product_count": 90,
        "rank1_mapping_count": 12_345,
        "residual_count": 9,
        "hard_jm_residual_count": 0,
        "formal_residual_count": 0,
        "inventory_residual_count": 9,
    }
    assert payload["db_snapshot_source"] == "direct_postgresql"
    assert payload["outputs"]["audit_evidence.json"] == str(
        output_dir / "audit_evidence.json"
    )
    for key in module.WRITE_BOUNDARY_FLAGS:
        assert payload[key] is False


def test_database_error_redacts_raw_normalized_url_and_password(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    password = uuid4().hex
    database_url = f"postgresql://audit-user:{password}@localhost/guiyi"
    normalized_url = database_url.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )
    monkeypatch.setenv("DATABASE_URL", database_url)

    class FailingSessionContext:
        def __enter__(self):
            raise RuntimeError(
                "ENV_BLOCKED_DB raw="
                f"{database_url} normalized={normalized_url} password-token={password}"
            )

        def __exit__(self, *_args: object) -> None:
            return None

    db_module = ModuleType("app.db.session")
    db_module.SessionLocal = FailingSessionContext  # type: ignore[attr-defined]
    db_module.get_db = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.db.session", db_module)

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(tmp_path),
            "--output-dir",
            "reports/db-blocked",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert captured.out == ""
    assert exit_code == 2
    assert payload["status"] == "ENV_BLOCKED_DB"
    assert payload["error_type"] == "RuntimeError"
    if any(
        sensitive in captured.err
        for sensitive in (database_url, normalized_url, password)
    ):
        pytest.fail("redaction leaked a sensitive database value", pytrace=False)
    assert "[REDACTED_DATABASE_URL]" in payload["error"]
    assert "[REDACTED_DATABASE_PASSWORD]" in payload["error"]


def test_report_writer_collision_keeps_distinct_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    db_module = ModuleType("app.db.session")
    db_module.SessionLocal = _SessionContext  # type: ignore[attr-defined]
    db_module.get_db = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.db.session", db_module)
    result = SimpleNamespace(
        summary={
            "status": module.ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED,
            "direct_postgresql": True,
            **module.WRITE_BOUNDARY_FLAGS,
        }
    )
    monkeypatch.setattr(module, "run_actual_dominant_roll_audit", lambda *_args: result)
    monkeypatch.setattr(
        module,
        "write_actual_dominant_roll_reports",
        lambda *_args: (_ for _ in ()).throw(FileExistsError("concurrent output collision")),
    )

    exit_code = module.main(
        [
            "verify",
            "--project-root",
            str(tmp_path),
            "--output-dir",
            "reports/raced",
        ]
    )

    payload = json.loads(capsys.readouterr().err)
    assert exit_code == 3
    assert payload["status"] == "OUTPUT_EXISTS"
    assert payload["error_type"] == "FileExistsError"


def test_script_entrypoint_never_imports_or_calls_rqdata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_provider_imports: list[str] = []
    original_import = builtins.__import__

    def guarded_import(name: str, *args, **kwargs):
        if name == "rqdatac" or name.startswith("rqdatac."):
            attempted_provider_imports.append(name)
            raise AssertionError(f"forbidden provider import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "verify",
            "--project-root",
            str(tmp_path),
            "--products-file",
            "not-the-canonical-products-file.txt",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 2
    assert payload["status"] == "INVALID_PRODUCTS_FILE"
    assert attempted_provider_imports == []
