import copy
import pytest
from scripts.newow_candidate_tools.context import Candidate
from scripts.newow_candidate_tools.preflight import validate_preview, validate_assets
from scripts.newow_candidate_tools.stages import require_stage


def candidate(tmp_path):
    return Candidate.from_mapping(
        dict(
            product="cj",
            code_sha="a" * 40,
            worktree=str(tmp_path),
            since="2023-01-01",
            through="2026-09-24",
            as_of="2026-09-24T07:00:00.000001+00:00",
            schema="newow_intraday_pilot_20260927",
            api_origin="http://127.0.0.1:8012",
            web_origin="http://127.0.0.1:5178",
        )
    )


def preview(c, product="cj", version="v27"):
    identity = dict(
        code_sha=c.code_sha,
        mode="local_candidate_readonly",
        realtime=False,
        as_of=c.as_of,
        candidate_origin=c.api_origin,
    )
    cap = dict(
        schema_version="newow_product_capabilities_" + version,
        release_stage="single_product_intraday_candidate"
        if version == "v27"
        else "black_steel_intraday_candidate",
        intraday_products=[product],
        open_frequencies=["5m", "15m", "30m", "60m", "1d", "1w"],
    )
    return dict(identity=identity, capabilities=cap)


def assets(c):
    return dict(
        code_sha=c.code_sha,
        as_of=c.as_of,
        readonly=True,
        writes=0,
        provider_calls=0,
        status="PASS",
        rows=[
            dict(
                frequency=f,
                prefix_status="INPUT_PREFIX_VERIFIED",
                owners=[
                    dict(
                        contract="CJ2301",
                        status="DATA_READY",
                        actual_bar_count=1,
                        expected_bar_count=1,
                        no_trade_bar_count=0,
                    )
                ],
                streams=[
                    dict(
                        strategy=s,
                        stream=dict(
                            enabled=False,
                            activation_generation=0,
                            product=c.product,
                            frequency=f,
                            strategy_code="newow_" + s,
                            active_revision_id="r1",
                            latest_seq=1,
                        ),
                        summary=dict(
                            revision_id="r1",
                            seq=1,
                            status="READY",
                            coverage=dict(complete_window_proven=False),
                        ),
                    )
                    for s in ("trend", "oscillation", "dual_fusion")
                ],
            )
            for f in c.frequencies
        ],
    )


def test_native_capability_is_validated_without_product_version_hardcode(tmp_path):
    for product, version in (("sm", "v26"), ("cj", "v27")):
        data = candidate(tmp_path).to_mapping()
        data["product"] = product
        c = Candidate.from_mapping(data)
        p = preview(c, product=product, version=version)
        assert validate_preview(c, p, p)["status"] == "PASS"


@pytest.mark.parametrize(
    "key,value",
    [
        ("realtime", True),
        ("code_sha", "b" * 40),
        ("as_of", "2026-09-24T07:00:00+00:00"),
        ("mode", "formal"),
    ],
)
def test_wrong_preview_fails_before_any_capture(tmp_path, key, value):
    c = candidate(tmp_path)
    p = preview(c)
    p["identity"][key] = value
    with pytest.raises(ValueError):
        validate_preview(c, p, preview(c))


def test_wrong_or_unknown_capabilities_fail_closed(tmp_path):
    c = candidate(tmp_path)
    for p in (preview(c, product="sm"), preview(c, version="v99")):
        with pytest.raises(ValueError):
            validate_preview(c, p, p)


def test_web_code_can_be_frozen_separately_without_ignoring_identity(tmp_path):
    data = candidate(tmp_path).to_mapping()
    data["web_code_sha"] = "b" * 40
    c = Candidate.from_mapping(data)
    web = preview(c)
    web["identity"]["code_sha"] = "b" * 40
    assert validate_preview(c, preview(c), web)["status"] == "PASS"


def test_full_assets_required_but_complete_window_false_is_preserved(tmp_path):
    c = candidate(tmp_path)
    a = assets(c)
    assert validate_assets(c, a)["count"] == 12
    a["rows"][0]["streams"][0]["stream"]["enabled"] = True
    with pytest.raises(ValueError):
        validate_assets(c, a)


def test_missing_and_duplicate_asset_combinations_fail(tmp_path):
    c = candidate(tmp_path)
    for change in ("missing", "duplicate"):
        a = assets(c)
        if change == "missing":
            a["rows"].pop()
        else:
            a["rows"][0]["streams"][2] = copy.deepcopy(a["rows"][0]["streams"][0])
        with pytest.raises(ValueError):
            validate_assets(c, a)


def test_stage_gate_requires_positive_previous_checks(tmp_path):
    c = candidate(tmp_path)
    with pytest.raises(ValueError):
        require_stage("capture", {})
    checks = {k: c.proof() for k in ("context", "legacy", "assets", "preview")}
    checks["legacy"]["rows"] = {
        f: dict(
            source_profiles=["t", "o"],
            source_formula_versions=["v1"],
            reference_model_version="r1",
        )
        for f in ("1d", "1w")
    }
    assert require_stage("capture", checks, c) == "READY_TO_CAPTURE"
    checks["assets"]["status"] = "UNKNOWN"
    with pytest.raises(ValueError):
        require_stage("capture", checks, c)


@pytest.mark.parametrize(
    "field,value",
    [
        ("product", "cj;touch /tmp/no"),
        ("product", "ALL"),
        ("schema", "public"),
        ("api_origin", "http://example.com:8012"),
        ("web_origin", "http://user:pass@127.0.0.1:5178"),
        ("as_of", "2026-09-24T07:00:00"),
        ("since", "2027-01-01"),
        ("frequencies", ["1m", "15m", "30m", "60m"]),
    ],
)
def test_invalid_task_configuration_is_rejected(tmp_path, field, value):
    data = candidate(tmp_path).to_mapping()
    data[field] = value
    with pytest.raises(ValueError):
        Candidate.from_mapping(data)


def test_declared_pass_from_other_product_or_time_is_not_asset_proof(tmp_path):
    c = candidate(tmp_path)
    for field, value in (("product", "sm"), ("as_of", "2026-09-24T07:00:00Z")):
        a = assets(c)
        a[field] = value
        with pytest.raises(ValueError):
            validate_assets(c, a)


def test_same_code_with_wrong_physical_owners_is_rejected(tmp_path):
    c = candidate(tmp_path)
    a = assets(c)
    a["rows"][0]["owners"][0]["contract"] = "SM2301"
    with pytest.raises(ValueError):
        validate_assets(c, a)


def test_owner_prefix_is_not_same_product_identity(tmp_path):
    data = candidate(tmp_path).to_mapping()
    data["product"] = "j"
    c = Candidate.from_mapping(data)
    a = assets(c)
    for row in a["rows"]:
        row["owners"][0]["contract"] = "J2301"
    a["rows"][0]["owners"][0]["contract"] = "JM2301"
    with pytest.raises(ValueError):
        validate_assets(c, a)


def test_missing_owner_counts_are_not_proof_of_complete_input(tmp_path):
    c = candidate(tmp_path)
    a = assets(c)
    for row in a["rows"]:
        for owner in row["owners"]:
            owner.pop("actual_bar_count")
            owner.pop("expected_bar_count")
    with pytest.raises(ValueError):
        validate_assets(c, a)


def test_missing_web_candidate_origin_is_not_a_match(tmp_path):
    c = candidate(tmp_path)
    api = preview(c)
    web = preview(c)
    web["identity"].pop("candidate_origin", None)
    with pytest.raises(ValueError):
        validate_preview(c, api, web)


def test_cli_cannot_resolve_away_symlink_output_protection(tmp_path, capsys):
    from scripts.newow_candidate_tools.cli import main

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    assert (
        main(
            ["preflight", "--output", str(link), "--assets", str(tmp_path / "missing")]
        )
        == 1
    )
    assert "OUTPUT_SYMLINK_FORBIDDEN" in capsys.readouterr().out


def test_capture_gate_binds_entire_task_and_legacy_preparation(tmp_path):
    c = candidate(tmp_path)
    checks = {
        k: dict(
            status="PASS",
            product=c.product,
            code_sha=c.code_sha,
            as_of=c.as_of,
            task_sha256=c.task_sha256,
        )
        for k in ("context", "legacy", "assets", "preview")
    }
    checks["legacy"]["rows"] = {}
    with pytest.raises(ValueError):
        require_stage("capture", checks, c)


def test_multi_product_preview_cannot_expand_single_product_task(tmp_path):
    data = candidate(tmp_path).to_mapping()
    data["product"] = "sm"
    c = Candidate.from_mapping(data)
    p = preview(c, product="sm", version="v26")
    p["capabilities"]["intraday_products"] = [
        "hc",
        "i",
        "j",
        "jm",
        "rb",
        "sf",
        "sm",
        "ss",
    ]
    with pytest.raises(ValueError):
        validate_preview(c, p, p)
