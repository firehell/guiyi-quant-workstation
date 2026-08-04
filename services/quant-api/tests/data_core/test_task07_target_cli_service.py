from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.data_core import cli_service


def test_task07_assess_is_readonly_and_requires_the_stage_c_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    observed: dict[str, object] = {}
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('20260803_0032')"))

    def assess(session, *, target_config, canonical_root):
        observed.update(
            readonly=session.info.get("task07_readonly_snapshot"),
            target_config=target_config,
            canonical_root=canonical_root,
        )
        return {
            "Stage_C": "NO_DATA_WRITE_REQUIRED",
            "writes_authorized": False,
            "repair_count": 0,
            "targets": [],
        }

    monkeypatch.setattr(cli_service, "run_target_canonical_assessment", assess)
    target_config = (tmp_path / "targets.yaml").resolve()
    canonical_root = (tmp_path / "canonical").resolve()
    canonical_root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(canonical_root))
    with Session(engine) as session:
        result = cli_service.run_data_core_command(
            "task07.assess",
            session,
            SimpleNamespace(
                target_config=target_config,
                canonical_root=canonical_root,
            ),
        )

    assert result == {
        "schema_version": 1,
        "command": "data.task07.assess",
        "status": "passed",
        "readonly": True,
        "production_writes": False,
        "effects": {
            "calls_rqdata": False,
            "writes_postgresql": False,
            "writes_parquet": False,
        },
        "database_revision": "20260803_0032",
        "Stage_C": "NO_DATA_WRITE_REQUIRED",
        "writes_authorized": False,
        "repair_count": 0,
        "targets": [],
    }
    assert observed == {
        "readonly": True,
        "target_config": target_config,
        "canonical_root": canonical_root,
    }

    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='20260802_0031'"))
    with Session(engine) as session, pytest.raises(
        ValueError,
        match="TASK07_DATABASE_REVISION_DRIFT",
    ):
        cli_service.run_data_core_command(
            "task07.assess",
            session,
            SimpleNamespace(
                target_config=target_config,
                canonical_root=canonical_root,
            ),
        )


def test_task07_assess_rejects_root_not_bound_to_configured_production_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('20260803_0032')"))

    production_root = tmp_path / "production-canonical"
    alternate_root = tmp_path / "alternate-canonical"
    production_root.mkdir()
    alternate_root.mkdir()
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(production_root))
    monkeypatch.setattr(
        cli_service,
        "run_target_canonical_assessment",
        lambda *_args, **_kwargs: {
            "Stage_C": "NO_DATA_WRITE_REQUIRED",
            "writes_authorized": False,
            "repair_count": 0,
            "targets": [],
        },
    )

    with Session(engine) as session, pytest.raises(
        ValueError,
        match="TASK07_CANONICAL_ROOT_DRIFT",
    ):
        cli_service.run_data_core_command(
            "task07.assess",
            session,
            SimpleNamespace(
                target_config=(tmp_path / "targets.yaml").resolve(),
                canonical_root=alternate_root.resolve(),
            ),
        )


@pytest.mark.parametrize(
    "command",
    sorted(cli_service._SUPERSEDED_TASK07_COMMANDS),
)
def test_public_runner_rejects_superseded_legacy_wide_commands(
    command: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="TASK07_LEGACY_WIDE_COMMAND_SUPERSEDED",
    ):
        cli_service.run_data_core_command(
            command,
            object(),  # type: ignore[arg-type]
            SimpleNamespace(),
        )
