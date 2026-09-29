import pytest
from test_audit import candidate
from scripts.newow_candidate_tools.bundle import build_index, audit_bundle
from scripts.newow_candidate_tools.evidence import EvidenceStore


def test_index_refuses_empty_or_incomplete_matrix(tmp_path):
    c = candidate(tmp_path)
    store = EvidenceStore(tmp_path / "evidence")
    store.write(
        "collection-observations.json",
        dict(
            c.proof(),
            rows=[],
            status="OBSERVED_NEEDS_VISUAL_REVIEW",
            readonly=True,
            provider_calls=0,
            production_writes=0,
        ),
    )
    with pytest.raises(ValueError, match="EXACT_SCENE_MATRIX"):
        build_index(c, store)


def test_audit_requires_unmodified_index_and_raw_files(tmp_path):
    c = candidate(tmp_path)
    store = EvidenceStore(tmp_path / "evidence")
    store.write(
        "evidence-index.json", c.proof(evidence=[], visual_review="NOT_PERFORMED")
    )
    with pytest.raises(ValueError):
        audit_bundle(c, store)


def complete_index_fixture(tmp_path):
    """Synthetic storage fixture; never presented as browser/product evidence."""
    import hashlib
    from scripts.newow_candidate_tools.bundle import SCENES

    c = candidate(tmp_path)
    store = EvidenceStore(tmp_path / "evidence")
    proof = c.proof()
    native = c.proof(
        rows={
            f: dict(
                source_profiles=["t", "o"],
                source_formula_versions=["v1", "v2"],
                reference_model_version="v1",
                base_identities={"trend": {}, "oscillation": {}},
            )
            for f in ("1d", "1w")
        }
    )
    checks = dict(context=proof, assets=proof, preview=proof, legacy=native)
    for name, body in (
        ("candidate.json", c.to_mapping()),
        ("context-check.json", proof),
        ("legacy-expected-identities.json", native),
        ("preflight-check.json", c.proof(checks=checks)),
        ("collection-start.json", dict(proof, status="STARTED")),
        ("capture-preview-check.json", proof),
    ):
        store.write(name, body)
    rows = []
    for scenario, f, m in SCENES:
        label = f"{scenario}-{f}-{m}"
        script = "unit-fixture-" + label
        sha = hashlib.sha256(script.encode()).hexdigest()
        raw = dict(
            proof,
            scenario=scenario,
            frequency=f,
            mode=m,
            status="OBSERVED_NEEDS_VISUAL_REVIEW",
            visual_review="NOT_RUN",
            observed={"unit_fixture": True},
            browser_script_sha256=sha,
        )
        raw_ref = store.write("browser/" + label + ".json", raw)
        cli_ref = store.write(
            "browser/" + label + "-cli.json",
            dict(
                browser_script=script,
                browser_script_sha256=sha,
                stdout="fixture",
                stderr="",
                exit_code=0,
                failure=None,
            ),
        )
        kinds = (
            ("main", "curve", "earlier")
            if scenario == "minute"
            else ("main", "curve")
            if scenario == "legacy"
            else ("main",)
        )
        images = [
            store.write(
                "browser/" + label + "-" + kind + ".png", {"unit_fixture": True}
            )
            for kind in kinds
        ]
        rows.append(dict(raw, raw=raw_ref, cli=cli_ref, images=images))
    store.write(
        "collection-observations.json",
        dict(
            proof,
            status="OBSERVED_NEEDS_VISUAL_REVIEW",
            rows=rows,
            readonly=True,
            provider_calls=0,
            production_writes=0,
        ),
    )
    return c, store


def test_complete_index_preserves_visual_gate_and_recomputes_every_hash(tmp_path):
    c, store = complete_index_fixture(tmp_path)
    result = build_index(c, store)
    assert (
        result["scene_count"] == 19
        and result["visual_review"] == "PENDING_INDEPENDENT_REVIEW"
    )
    assert sum(r["kind"] == "screenshot" for r in result["evidence"]) == 49
    store.write("evidence-index.json", result)
    # Deliberately fake scene data cannot pass the actual numerical audit.
    with pytest.raises((ValueError, KeyError)):
        audit_bundle(c, store)


@pytest.mark.parametrize(
    "change",
    ["missing_row", "wrong_frequency", "raw_hash", "missing_screenshot", "script_hash"],
)
def test_complete_index_rejects_scene_or_evidence_tamper(tmp_path, change):
    import json

    c, store = complete_index_fixture(tmp_path)
    body = store.read("collection-observations.json")
    if change == "missing_row":
        body["rows"].pop()
    elif change == "wrong_frequency":
        body["rows"][0]["frequency"] = "1m"
    elif change == "raw_hash":
        body["rows"][0]["raw"]["sha256"] = "0" * 64
    elif change == "missing_screenshot":
        body["rows"][0]["images"].pop()
    elif change == "script_hash":
        body["rows"][0]["browser_script_sha256"] = "0" * 64
    store.path("collection-observations.json").write_text(json.dumps(body))
    with pytest.raises(ValueError):
        build_index(c, store)
