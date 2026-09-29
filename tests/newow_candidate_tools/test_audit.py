import copy
import pytest
from scripts.newow_candidate_tools.context import Candidate
from scripts.newow_candidate_tools.audit import validate_full_capture, validate_index
from scripts.newow_candidate_tools.curves import expected_curve
from scripts.newow_candidate_tools.evidence import EvidenceStore
from test_curves import value


def candidate(tmp_path):
    return Candidate.from_mapping(
        dict(
            product="cj",
            code_sha="a" * 40,
            worktree=str(tmp_path),
            since="2026-09-01",
            through="2026-09-24",
            as_of="2026-09-24T07:00:00.000001Z",
            schema="newow_intraday_pilot_test",
            api_origin="http://127.0.0.1:8012",
            web_origin="http://127.0.0.1:5178",
        )
    )


def binding(url, http=200):
    return dict(
        evidence_kind="xhr_response_text_compact",
        url=url,
        http=http,
        xhr_sequence=1,
        node_request_id=1,
        started_order=1,
        completed_order=2,
        started_at=1,
        completed_at=2,
        response_text_chars=10,
    )


def capture(c):
    v = value()
    v.update(
        reference_input_sha256="1" * 64,
        reference_cutoff="2026-09-24T07:00:00Z",
        executable=False,
        auto_order=False,
        items=v["curve_trades"],
    )
    meta = dict(
        identity=dict(product="cj", frequency="5m", strategy="trend"),
        as_of=c.as_of,
        snapshot_token="token1",
        input_content_sha256="1" * 64,
    )
    raw = dict(
        meta=meta,
        reference=dict(delivery="delivered", status=dict(status="ready"), value=v),
    )
    base = (
        c.web_origin
        + "/api/v1/market/newow/strategy-detail?product=cj&frequency=5m&strategy=trend&section=reference&history_limit=200&as_of=2026-09-24T07%3A00%3A00.000001Z&snapshot_token=token1"
    )
    wire = dict(http=200, url=base, xhr_binding=binding(base), payload=raw)
    read = dict(
        http=200,
        observed_url=base,
        transport_url=base.replace(c.web_origin, c.api_origin),
        payload=copy.deepcopy(raw),
    )
    chart = copy.deepcopy(wire)
    chart["url"] = base.replace("section=reference", "section=chart")
    chart["xhr_binding"] = binding(chart["url"])
    chart["payload"] = dict(
        meta=copy.deepcopy(meta),
        chart=dict(
            delivery="delivered",
            status=dict(status="ready"),
            value=dict(
                bars=[
                    dict(
                        bar_end="2026-09-24T07:00:00Z",
                        completed=True,
                        observation_eligible=True,
                        physical_contract="CJ2605",
                        segment_id="segment",
                        source_identity="source",
                        trading_day="2026-09-24",
                    )
                ]
            ),
        ),
    )
    points, _ = expected_curve(v)
    coords = " ".join(f"{x},{y}" for x, y in points)
    ids = ["row-" + t["reference_trade_id"] for t in v["items"]]
    ident = dict(
        code_sha=c.code_sha,
        as_of=c.as_of,
        realtime=False,
        mode="local_candidate_readonly",
        candidate_origin=c.api_origin,
    )
    dom = dict(
        product="cj",
        frequency="5m",
        mode=["趋势策略"],
        all=True,
        closed=True,
        busy=False,
        ids=ids,
        curves=[dict(points=coords, rect=dict(width=712, height=140))],
        statuses=[],
    )
    return dict(
        frequency="5m",
        mode="trend",
        identity=ident,
        webIdentity=ident,
        errors=[],
        chart=chart,
        reference=wire,
        records=wire,
        fullReadback=read,
        recordsReadback=copy.deepcopy(read),
        dom=dom,
        after=dict(ids=ids, curves=[coords]),
    )


def test_full_capture_binds_complete_array_and_all_dom_points(tmp_path):
    c = candidate(tmp_path)
    p = validate_full_capture(c, capture(c), "5m", "trend")
    assert p["closed_count"] == 3 and p["all_svg_points"] == 5


@pytest.mark.parametrize(
    "change",
    [
        "product",
        "snapshot",
        "microsecond",
        "internal_point",
        "record_id",
        "raw_return",
        "get_origin",
        "raw_records",
        "bad_binding",
        "future_bar",
        "incomplete_bar",
        "other_contract",
        "request_asof",
    ],
)
def test_wire_and_dom_tampering_fails(tmp_path, change):
    c = candidate(tmp_path)
    raw = capture(c)
    if change == "product":
        raw["fullReadback"]["payload"]["meta"]["identity"]["product"] = "sm"
    elif change == "snapshot":
        raw["chart"]["payload"]["meta"]["snapshot_token"] = "other"
    elif change == "microsecond":
        raw["identity"]["as_of"] = "2026-09-24T07:00:00Z"
    elif change == "internal_point":
        raw["dom"]["curves"][0]["points"] = "0,140 1,99 2,1 3,20 712,20"
    elif change == "record_id":
        raw["dom"]["ids"][1] = "row-wrong"
    elif change == "raw_return":
        raw["fullReadback"]["payload"]["reference"]["value"]["curve_trades"][1][
            "reference_return_pct"
        ] = "5"
    elif change == "get_origin":
        raw["fullReadback"]["transport_url"] = "http://external.test/steal"
    elif change == "raw_records":
        raw["records"] = copy.deepcopy(raw["records"])
        raw["records"]["payload"]["reference"]["value"]["items"] = []
    elif change == "bad_binding":
        raw["reference"]["xhr_binding"] = dict(url="http://wrong.test/", http=500)
    elif change == "future_bar":
        raw["chart"]["payload"]["chart"]["value"]["bars"][0]["bar_end"] = (
            "2099-01-01T00:00:00Z"
        )
    elif change == "incomplete_bar":
        raw["chart"]["payload"]["chart"]["value"]["bars"][0]["completed"] = False
    elif change == "other_contract":
        raw["chart"]["payload"]["chart"]["value"]["bars"][0]["physical_contract"] = (
            "OTHER2605"
        )
    elif change == "request_asof":
        raw["reference"]["url"] = raw["reference"]["url"].replace(".000001Z", "Z")
        raw["reference"]["xhr_binding"]["url"] = raw["reference"]["url"]
    with pytest.raises(ValueError):
        validate_full_capture(c, raw, "5m", "trend")


def test_index_rechecks_raw_hash_instead_of_trusting_pass(tmp_path):
    c = candidate(tmp_path)
    store = EvidenceStore(tmp_path / "evidence")
    reference = store.write(
        "observed.json", dict(product="cj", status="OBSERVED_NEEDS_VISUAL_REVIEW")
    )
    index = c.proof(
        evidence=[dict(kind="capture", **reference)], visual_review="NOT_PERFORMED"
    )
    assert validate_index(c, store, index)["visual_review"] == "NOT_PERFORMED"
    (store.root / "observed.json").write_text("{}")
    with pytest.raises(ValueError):
        validate_index(c, store, index)
