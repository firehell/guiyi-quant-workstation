from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.market_data import gate_a_operator
from app.market_data.gate_a_operator import GateAOperatorError


def _core_payload(*, candidate_root: str, active_root: str) -> dict:
    return {
        "schema_version": 1,
        "mode": "gate_a_exact_scope_dry_run",
        "read_only": True,
        "through": "2026-08-07",
        "candidate_root": candidate_root,
        "active_canonical_root": active_root,
        "products": ["jm", "ag"],
        "legacy_roots": [
            "/legacy/contracts",
            "/legacy/continuous",
            active_root,
        ],
        "counts": {
            "products": 2,
            "rqdata_windows": 1,
            "legacy_selected_month_targets": 1,
        },
        "legacy_selected_month_targets": [
            {
                "dataset": ["continuous", "jm", "MAIN", "1d"],
                "year": 2026,
                "month": 8,
                "path": "/legacy/continuous/jm.parquet",
                "covered_trading_days": 1,
                "desired_trading_days": 1,
            }
        ],
        "rqdata_windows": [
            {
                "dataset": ["continuous", "jm", "MAIN", "1m"],
                "year": 2026,
                "month": 8,
                "start": "2026-08-01",
                "end": "2026-08-01",
                "missing_trading_days": 1,
                "reason": "LEGACY_WINDOW_UNCOVERED",
            }
        ],
    }


def _write_report(path: Path, *, candidate_root: str, active_root: str, tweak=None) -> str:
    core = _core_payload(candidate_root=candidate_root, active_root=active_root)
    if tweak is not None:
        tweak(core)
    digest = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report = {
        **core,
        "scope_digest": digest,
        "candidate_catalog": "guiyi_canonical_candidate_20260807",
        "dry_run_evidence": {"canonical_written": False},
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return digest


def test_load_exact_scope_strips_wrapper_fields_and_verifies_digest(tmp_path: Path) -> None:
    candidate = (tmp_path / "candidate").resolve()
    active = (tmp_path / "active").resolve()
    candidate.mkdir()
    active.mkdir()
    path = tmp_path / "scope.json"
    digest = _write_report(path, candidate_root=candidate.as_posix(), active_root=active.as_posix())
    report_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    loaded = gate_a_operator.load_exact_scope(
        path,
        expected_scope_digest=digest,
        expected_report_sha256=report_sha,
    )

    assert loaded.candidate_catalog == "guiyi_canonical_candidate_20260807"
    assert loaded.through.isoformat() == "2026-08-07"
    assert loaded.scope_digest == digest
    assert "candidate_catalog" not in loaded.exact_scope
    assert "dry_run_evidence" not in loaded.exact_scope
    assert "scope_digest" not in loaded.exact_scope
    assert len(loaded.exact_scope["rqdata_windows"]) == 1
    assert loaded.products == ("jm", "ag")


def test_load_exact_scope_rejects_tampered_windows(tmp_path: Path) -> None:
    candidate = (tmp_path / "candidate").resolve()
    active = (tmp_path / "active").resolve()
    candidate.mkdir()
    active.mkdir()
    path = tmp_path / "scope.json"
    digest = _write_report(path, candidate_root=candidate.as_posix(), active_root=active.as_posix())
    report = json.loads(path.read_text(encoding="utf-8"))
    report["rqdata_windows"][0]["end"] = "2026-08-02"
    path.write_text(json.dumps(report), encoding="utf-8")
    report_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(GateAOperatorError, match="GATE_A_SCOPE_DIGEST_MISMATCH"):
        gate_a_operator.load_exact_scope(
            path,
            expected_scope_digest=digest,
            expected_report_sha256=report_sha,
        )


def test_load_exact_scope_rejects_report_sha_mismatch(tmp_path: Path) -> None:
    candidate = (tmp_path / "candidate").resolve()
    active = (tmp_path / "active").resolve()
    candidate.mkdir()
    active.mkdir()
    path = tmp_path / "scope.json"
    digest = _write_report(path, candidate_root=candidate.as_posix(), active_root=active.as_posix())

    with pytest.raises(GateAOperatorError, match="GATE_A_REPORT_SHA256_MISMATCH"):
        gate_a_operator.load_exact_scope(
            path,
            expected_scope_digest=digest,
            expected_report_sha256="0" * 64,
        )


def test_assert_isolated_database_requires_exact_catalog_name() -> None:
    url = "postgresql+psycopg://guiyi:secret@127.0.0.1:5432/guiyi_canonical_candidate_20260807"
    gate_a_operator.assert_isolated_database(url, "guiyi_canonical_candidate_20260807")
    with pytest.raises(GateAOperatorError, match="GATE_A_DATABASE_NAME_MISMATCH"):
        gate_a_operator.assert_isolated_database(
            "postgresql+psycopg://guiyi:secret@127.0.0.1:5432/guiyi_quant",
            "guiyi_canonical_candidate_20260807",
        )


def test_assert_candidate_root_ready_blocks_nonempty_without_resume(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "marker.txt").write_text("x", encoding="utf-8")
    with pytest.raises(GateAOperatorError, match="GATE_A_CANDIDATE_ROOT_NOT_EMPTY"):
        gate_a_operator.assert_candidate_root_ready(root, resume=False)
    gate_a_operator.assert_candidate_root_ready(root, resume=True)


def test_assert_candidate_root_isolated_rejects_overlap(tmp_path: Path) -> None:
    active = tmp_path / "active"
    active.mkdir()
    nested = active / "nested"
    nested.mkdir()
    with pytest.raises(GateAOperatorError, match="GATE_A_CANDIDATE_ROOT_OVERLAPS_ACTIVE"):
        gate_a_operator.assert_candidate_root_isolated(nested, active)


def test_build_candidate_manager_receives_exact_scope(monkeypatch, tmp_path: Path) -> None:
    candidate = (tmp_path / "candidate").resolve()
    active = (tmp_path / "active").resolve()
    candidate.mkdir()
    active.mkdir()
    path = tmp_path / "scope.json"
    digest = _write_report(path, candidate_root=candidate.as_posix(), active_root=active.as_posix())
    report_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = gate_a_operator.load_exact_scope(
        path,
        expected_scope_digest=digest,
        expected_report_sha256=report_sha,
    )

    captured: dict = {}

    def fake_build(session, candidate_root, *, exact_scope=None):
        captured["session"] = session
        captured["candidate_root"] = candidate_root
        captured["exact_scope"] = exact_scope

        class Manager:
            def bootstrap(self, request):
                return {"action": "bootstrap", "apply": request.apply, "through": request.through}

        return Manager()

    monkeypatch.setattr(
        "app.market_data.gate_a_operator.build_candidate_bootstrap_manager",
        fake_build,
    )
    monkeypatch.setattr(
        "app.market_data.gate_a_operator.canonical_root",
        lambda: active,
    )

    class Session:
        pass

    result = gate_a_operator.run_apply(
        loaded,
        session=Session(),
        resume=False,
        require_intent_token=True,
        intent_confirmed=True,
    )

    assert captured["exact_scope"] == loaded.exact_scope
    assert captured["candidate_root"] == candidate
    assert result["apply"] is True


def test_run_apply_requires_intent_confirmation(tmp_path: Path) -> None:
    candidate = (tmp_path / "candidate").resolve()
    active = (tmp_path / "active").resolve()
    candidate.mkdir()
    active.mkdir()
    path = tmp_path / "scope.json"
    digest = _write_report(path, candidate_root=candidate.as_posix(), active_root=active.as_posix())
    report_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = gate_a_operator.load_exact_scope(
        path,
        expected_scope_digest=digest,
        expected_report_sha256=report_sha,
    )
    with pytest.raises(GateAOperatorError, match="GATE_A_APPLY_INTENT_REQUIRED"):
        gate_a_operator.run_apply(
            loaded,
            session=object(),
            resume=False,
            require_intent_token=True,
            intent_confirmed=False,
        )
