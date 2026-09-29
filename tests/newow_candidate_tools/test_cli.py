import json
from scripts.newow_candidate_tools.cli import main
from scripts.newow_candidate_tools.evidence import EvidenceStore
from test_audit import candidate
from test_bundle import complete_index_fixture


def test_capture_requires_explicit_execution_and_does_not_start_browser(
    tmp_path, capsys
):
    c = candidate(tmp_path)
    store = EvidenceStore(tmp_path / "evidence")
    store.write("candidate.json", c.to_mapping())
    result = main(
        [
            "capture",
            "--output",
            str(store.root),
            "--cli",
            "/tmp/unused",
            "--session",
            "candidate",
        ]
    )
    assert (
        result == 1
        and json.loads(capsys.readouterr().out)["code"]
        == "EXPLICIT_CAPTURE_EXECUTION_REQUIRED"
    )
    assert not store.path("collection-start.json").exists()


def test_cli_index_is_exclusive_and_fake_observation_cannot_audit(tmp_path, capsys):
    c, store = complete_index_fixture(tmp_path)
    assert main(["index", "--output", str(store.root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert (
        result["visual_review"] == "PENDING_INDEPENDENT_REVIEW"
        and "evidence" not in result
    )
    assert main(["index", "--output", str(store.root)]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "FileExistsError"
    assert main(["audit", "--output", str(store.root)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert not store.path("offline-audit.json").exists()
