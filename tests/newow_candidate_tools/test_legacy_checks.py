"""Isolated legacy gate fixtures; never treated as market acceptance evidence."""

from copy import deepcopy
from pathlib import Path
from urllib.parse import urlencode
import pytest
from scripts.newow_candidate_tools.context import Candidate
from scripts.newow_candidate_tools.curves import expected_curve, EMPTY_CURVE_STATUS
from scripts.newow_candidate_tools.legacy_checks import validate_legacy_capture


def sample(frequency="1w", mode="trend", zero=False):
    candidate = Candidate.from_mapping(
        dict(
            product="cj",
            code_sha="a" * 40,
            worktree=str(Path(__file__).resolve().parents[2]),
            since="2023-01-01",
            through="2026-09-24",
            as_of="2026-09-24T07:00:00.000001+00:00",
            schema="newow_intraday_fixture",
            api_origin="http://127.0.0.1:8012",
            web_origin="http://127.0.0.1:5178",
        )
    )
    expected = candidate.proof(
        rows={
            f: dict(
                source_profiles=[f"trend_{f}", f"oscillation_{f}"],
                source_formula_versions=["trend_formula", "oscillation_formula"],
                reference_model_version="fusion_model",
                base_identities={
                    s: dict(profile_id=f"{s}_{f}", formula_versions=[s + "_formula"])
                    for s in ("trend", "oscillation")
                },
            )
            for f in ("1d", "1w")
        }
    )
    process = dict(
        code_sha=candidate.code_sha,
        as_of=candidate.as_of,
        mode="local_candidate_readonly",
        realtime=False,
    )
    end = "2026-09-24T07:00:00+00:00"
    trades = (
        []
        if zero
        else [
            dict(
                reference_trade_id="one",
                status="CLOSED",
                statistics_membership="entry_in_window_v1",
                exit_bar_end="2026-09-17T07:00:00+00:00",
                exit_trading_day="2026-09-17",
                entry_bar_end="2026-09-15T07:00:00+00:00",
                entry_trading_day="2026-09-15",
                reference_return_pct="1.25",
            )
        ]
    )
    value = dict(
        performance_since=candidate.since,
        performance_through=candidate.through,
        actual_available_through=candidate.through,
        reference_cutoff=end,
        reference_input_sha256="b" * 64,
        page_parity=True,
        executable=False,
        auto_order=False,
        summary=dict(
            closed_count=len(trades),
            sum_return_percentage_points="0" if zero else "1.25",
            membership_policy="entry_in_window_v1",
        ),
        curve_trades=trades,
        items=deepcopy(trades),
    )
    if mode == "dual":
        f = dict(
            product="cj",
            frequency=frequency,
            reference_revision="c" * 64,
            reference_input_sha256="b" * 64,
            reference_cutoff=end,
            items=deepcopy(trades),
            record_since="2025-09-24",
            performance_since=candidate.since,
            performance_through=candidate.through,
            reference_model_version="fusion_model",
            source_profiles=expected["rows"][frequency]["source_profiles"],
            source_formula_versions=expected["rows"][frequency][
                "source_formula_versions"
            ],
            page_parity=True,
            executable=False,
            snapshot_schema="newow_fusion_reference_snapshot_v2",
            groups=[
                dict(
                    model=s,
                    closed_count=len(trades),
                    sum_return_percentage_points="0" if zero else "1.25",
                )
                for s in ("trend", "oscillation", "fusion")
            ],
            curve=trades,
        )
        value["fusion"] = f
    strategy = "oscillation" if mode == "oscillation" else "trend"
    responses = []

    def meta(s, token):
        return dict(
            identity=dict(
                product="cj",
                strategy=s,
                frequency=frequency,
                profile_id=f"{s}_{frequency}",
                formula_versions=[s + "_formula"],
            ),
            as_of=candidate.as_of,
            input_content_sha256="b" * 64,
            snapshot_token=token,
        )

    for phase, token in [("initial", "token1"), ("return", "token2")]:
        for s in ("trend", "oscillation") if mode == "dual" else (strategy,):
            m = meta(s, token)
            query = dict(
                product="cj",
                frequency=frequency,
                strategy=s,
                section="chart",
                as_of=candidate.as_of,
            )
            chart = dict(
                delivery="delivered",
                status=dict(status="ready"),
                value=dict(
                    bars=[
                        dict(
                            bar_end=end,
                            trading_day="2026-09-24",
                            physical_contract="CJ2701",
                            segment_id="segment",
                            source_identity="source",
                            completed=True,
                            observation_eligible=True,
                        )
                    ]
                ),
            )
            responses.append(
                dict(
                    phase=phase,
                    url=candidate.web_origin
                    + "/api/v1/market/newow/strategy-detail?"
                    + urlencode(query),
                    http=200,
                    meta=m,
                    chart=chart,
                )
            )
            query.update(section="reference", snapshot_token=token, history_limit="200")
            v = deepcopy(value)
            if s != strategy:
                v.pop("fusion", None)
            responses.append(
                dict(
                    phase=phase,
                    url=candidate.web_origin
                    + "/api/v1/market/newow/strategy-detail?"
                    + urlencode(query),
                    http=200,
                    meta=m,
                    reference=dict(
                        delivery="delivered", status=dict(status="ready"), value=v
                    ),
                )
            )
    points, _ = expected_curve(
        value["fusion"] if mode == "dual" else value, mode == "dual"
    )
    curves = (
        []
        if zero
        else [
            dict(points=" ".join(f"{x},{y}" for x, y in points), width=700, height=140)
        ]
    )
    dom = dict(
        scopeBusy=False,
        url=candidate.web_origin
        + "/market/chart?"
        + urlencode(
            dict(
                symbol="cj",
                frequency=frequency,
                strategy=strategy,
                **({"newow_mode": "dual"} if mode == "dual" else {}),
            )
        ),
        mode=[{"trend": "趋势策略", "oscillation": "震荡策略", "dual": "双策略"}[mode]],
        cards=[]
        if zero
        else [("fusion-trade-" if mode == "dual" else "trade-") + "one"],
        curves=curves,
        statuses=[EMPTY_CURVE_STATUS] if zero else [],
        all="true",
    )
    auxiliary = [
        dict(component=s, status=dict(status="ready"), meta=meta(strategy, "token1"))
        for s in ("macd", "trend_reversal")
    ]
    for index, row in enumerate(responses):
        row["xhr_binding"] = dict(
            evidence_kind="xhr_response_text_compact",
            url=row["url"],
            http=200,
            xhr_sequence=index + 1,
            node_request_id=index + 1,
            started_order=index * 2 + 1,
            completed_order=index * 2 + 2,
            started_at=1000 + index * 2,
            completed_at=1001 + index * 2,
            response_text_chars=1000,
        )
    observation = dict(
        capture_schema="newow_legacy_xhr_v1",
        identity=process,
        webIdentity=dict(process, candidate_origin=candidate.api_origin),
        initial=deepcopy(dom),
        full=deepcopy(dom),
        before=deepcopy(dom),
        returned=deepcopy(dom),
        returnFloor=len(responses) // 2,
        auxiliary=auxiliary,
        responses=responses,
        bodyErrors=[],
        failures=[],
        pageErrors=[],
        status="OBSERVED_NEEDS_REVIEW",
    )
    return candidate, expected, observation


def recovery_sample():
    candidate, expected, observation = sample(mode="dual")
    cutoff = candidate.as_of
    bar = dict(
        bar_end="2026-09-24T07:00:00+00:00", trading_day="2026-09-24",
        open="9000", high="9100", low="8900", close="9050", volume="123",
        open_interest="456", physical_contract="CJ2701", segment_id="segment",
        calculation_segment_id="segment", source_identity="canonical:cj:60m:CJ2701",
        completed=True, observation_eligible=True,
    )
    chart = dict(delivery="delivered", status=dict(status="ready"), value=dict(
        **{"from": "2026-06-16", "through": candidate.through}, next_before=None,
        bars=[bar],
    ))
    def url(strategy, section, **extra):
        return candidate.web_origin + "/api/v1/market/newow/strategy-detail?" + urlencode(dict(
            product=candidate.product, frequency="60m", strategy=strategy,
            series_kind="actual_dominant", section=section, as_of=cutoff, **extra,
        ))
    def meta(strategy, token, input_hash="d" * 64):
        return dict(identity=dict(
            product=candidate.product, frequency="60m", strategy=strategy,
            series_kind="actual_dominant", profile_id=f"newow_product_{strategy}_60m_v1",
            formula_versions=expected["rows"]["1w"]["base_identities"][strategy]["formula_versions"],
        ), as_of=cutoff, snapshot_token=token, input_content_sha256=input_hash)
    main = dict(phase="away", url=url("trend", "chart"), http=200,
                meta=meta("trend", "main-token"), chart=deepcopy(chart))
    old = dict(phase="away", url=url("oscillation", "chart", **{"from": "2026-06-16", "through": candidate.through, "chart_limit": "500"}),
               http=200, meta=meta("oscillation", "old-token"), chart=deepcopy(chart))
    conflict = dict(phase="away", url=url("oscillation", "reference", snapshot_token="old-token", history_limit="200"),
                    http=409, detail={"code": "NEWOW_SNAPSHOT_GENERATION_CONFLICT"})
    fresh = deepcopy(old); fresh["meta"]["snapshot_token"] = "fresh-token"
    reference = dict(phase="away", url=url("oscillation", "reference", snapshot_token="fresh-token", history_limit="200"),
                     http=200, meta=meta("oscillation", "fresh-token", "e" * 64),
                     reference=dict(delivery="delivered", status=dict(status="ready"), value=dict(
                         performance_since=candidate.since, performance_through=candidate.through,
                         actual_available_through=candidate.through, reference_cutoff=bar["bar_end"],
                         reference_input_sha256="e" * 64, page_parity=True,
                         executable=False, auto_order=False,
                         summary=dict(membership_policy="entry_in_window_v1", closed_count=1),
                         curve_trades=[{"reference_trade_id": "one"}], items=[{"reference_trade_id": "one"}],
                     )))
    fusion_trade = dict(
        reference_trade_id="one", status="CLOSED", statistics_membership="entry_in_window_v1",
        entry_bar_end="2026-09-23T07:00:00+00:00", entry_trading_day="2026-09-23",
        exit_bar_end=bar["bar_end"], exit_trading_day=bar["trading_day"],
        reference_return_pct="1.25",
    )
    fusion = dict(
        product=candidate.product, frequency="60m", reference_revision="a" * 64,
        reference_input_sha256="d" * 64, reference_cutoff=bar["bar_end"],
        items=[fusion_trade], record_since="2025-09-24",
        performance_since=candidate.since, performance_through=candidate.through,
        reference_model_version=expected["rows"]["1w"]["reference_model_version"],
        source_profiles=["newow_product_trend_60m_v1", "newow_product_oscillation_60m_v1"],
        source_formula_versions=expected["rows"]["1w"]["source_formula_versions"],
        page_parity=True, executable=False, snapshot_schema="newow_fusion_reference_snapshot_v2",
        groups=[dict(model="fusion", closed_count=1, sum_return_percentage_points="1.25")],
        curve=[fusion_trade],
    )
    fusion_wire = dict(
        phase="away", url=url("trend", "reference", include_fusion="true",
                              snapshot_token="main-token", performance_since=candidate.since,
                              performance_through=candidate.through), http=200,
        meta=meta("trend", "main-token"),
        reference=dict(delivery="delivered", status=dict(status="ready"), value=dict(
            reference_input_sha256="d" * 64, reference_cutoff=bar["bar_end"], fusion=fusion,
        )),
    )
    observation["responses"][4:4] = [main, old, conflict, fresh, reference, fusion_wire]
    observation["returnFloor"] = 10
    points, _ = expected_curve(fusion, True)
    observation["away"] = dict(
        url=candidate.web_origin + "/market/chart?symbol=cj&frequency=60m&newow_mode=dual",
        mode=["双策略"], scopeBusy=False, cards=["fusion-trade-one"],
        curves=[dict(points=" ".join(f"{x},{y}" for x, y in points), width=700, height=140)],
        statuses=[], all="true",
        observed_at=10_000,
    )
    bind_recovery_rows(observation)
    return candidate, expected, observation


def bind_recovery_rows(observation):
    for index, row in enumerate(observation["responses"]):
        row["xhr_binding"] = dict(
            evidence_kind="xhr_response_text_compact", url=row["url"], http=row["http"],
            xhr_sequence=index + 1, node_request_id=index + 1,
            started_order=index * 2 + 1, completed_order=index * 2 + 2,
            started_at=1000 + index * 2, completed_at=1001 + index * 2,
            response_text_chars=1000,
        )


def test_exact_bound_partner_recovery_accepts_one_same_window_chain():
    c, p, o = recovery_sample()
    report = validate_legacy_capture(c, p, o, "1w", "dual")
    assert report["checks"]["away_snapshot_recovery"] == "PASS"
    assert report["historical_actual_xhr_binding"] is True


@pytest.mark.parametrize("change", [
    "missing_binding", "wrong_code", "second_409", "cross_window", "old_token",
    "wrong_order", "fresh_bar", "main_bar", "wrong_source", "wrong_reference_hash",
    "away_error", "away_before_reference", "away_missing_time", "away_boolean_time",
    "away_missing_busy", "away_busy", "away_missing_cards", "wrong_frequency", "wrong_formula",
    "missing_fresh_reference", "wrong_reference_token", "wrong_both_formula", "away_unrelated_card",
    "away_invalid_curve", "fusion_before_fresh", "fusion_stale_token", "fusion_wrong_hash",
])
def test_partner_recovery_rejects_unproven_chain(change):
    c, p, o = recovery_sample()
    rows = o["responses"]
    main, old, conflict, fresh, reference = rows[4:9]
    if change == "missing_binding": conflict.pop("xhr_binding")
    elif change == "wrong_code": conflict["detail"]["code"] = "OTHER_CONFLICT"
    elif change == "second_409":
        rows.insert(8, deepcopy(conflict)); bind_recovery_rows(o)
    elif change == "cross_window":
        fresh["url"] = fresh["url"].replace("from=2026-06-16", "from=2026-06-17")
        fresh["xhr_binding"]["url"] = fresh["url"]
    elif change == "old_token": reference["url"] = reference["url"].replace("fresh-token", "old-token"); reference["xhr_binding"]["url"] = reference["url"]
    elif change == "wrong_order": fresh["xhr_binding"]["started_order"] = conflict["xhr_binding"]["completed_order"] - 1
    elif change == "fresh_bar": fresh["chart"]["value"]["bars"][0]["close"] = "9999"
    elif change == "main_bar": main["chart"]["value"]["bars"][0]["close"] = "9999"
    elif change == "wrong_source": fresh["meta"]["input_content_sha256"] = "f" * 64
    elif change == "wrong_reference_hash": reference["reference"]["value"]["reference_input_sha256"] = "f" * 64
    elif change == "away_error": o["away"]["statuses"] = ["另一策略参考收益暂不可用"]
    elif change == "away_before_reference": o["away"]["observed_at"] = 1
    elif change == "away_missing_time": o["away"].pop("observed_at")
    elif change == "away_boolean_time": o["away"]["observed_at"] = True
    elif change == "away_missing_busy": o["away"].pop("scopeBusy")
    elif change == "away_busy": o["away"]["scopeBusy"] = True
    elif change == "away_missing_cards": o["away"]["cards"] = []
    elif change == "away_unrelated_card": o["away"]["cards"] = ["fusion-trade-unrelated"]
    elif change == "away_invalid_curve": o["away"]["curves"][0]["points"] = "0,NaN 712,140"
    elif change == "wrong_frequency": conflict["url"] = conflict["url"].replace("frequency=60m", "frequency=15m"); conflict["xhr_binding"]["url"] = conflict["url"]
    elif change == "wrong_formula": fresh["meta"]["identity"]["formula_versions"] = ["changed"]
    elif change == "wrong_both_formula":
        main["meta"]["identity"]["formula_versions"] = ["wrong-trend"]
        old["meta"]["identity"]["formula_versions"] = ["wrong-oscillation"]
        fresh["meta"]["identity"]["formula_versions"] = ["wrong-oscillation"]
        rows[9]["reference"]["value"]["fusion"]["source_formula_versions"] = ["wrong-trend", "wrong-oscillation"]
    elif change == "missing_fresh_reference": rows.pop(8)
    elif change == "wrong_reference_token": reference["meta"]["snapshot_token"] = "old-token"
    elif change == "fusion_before_fresh": rows.insert(8, rows.pop(9)); bind_recovery_rows(o)
    elif change == "fusion_stale_token": rows[9]["url"] = rows[9]["url"].replace("main-token", "stale-token"); rows[9]["xhr_binding"]["url"] = rows[9]["url"]
    elif change == "fusion_wrong_hash": rows[9]["reference"]["value"]["fusion"]["reference_input_sha256"] = "f" * 64
    with pytest.raises((ValueError, KeyError, TypeError)):
        validate_legacy_capture(c, p, o, "1w", "dual")


@pytest.mark.parametrize("f", ["1d", "1w"])
@pytest.mark.parametrize("m", ["trend", "oscillation", "dual"])
@pytest.mark.parametrize("zero", [False, True])
def test_all_legacy_shapes(f, m, zero):
    c, p, o = sample(f, m, zero)
    report = validate_legacy_capture(c, p, o, f, m)
    assert report["status"] == "PASS"
    assert report["checks"]["complete_closed_curve"] == (
        "NOT_APPLICABLE" if zero else "PASS"
    )
    assert report["visual_review"] == "NOT_RUN"


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_profile",
        "wrong_formula",
        "wrong_product",
        "future_bar",
        "uncompleted",
        "curve_point",
        "duplicate_record",
        "return_card",
        "missing_empty",
        "wrong_fusion_model",
        "wrong_native_proof",
        "missing_aux",
    ],
)
def test_legacy_tampering_rejected(mutation):
    c, p, o = sample(
        mode="dual" if mutation == "wrong_fusion_model" else "trend",
        zero=mutation == "missing_empty",
    )
    if mutation == "wrong_profile":
        o["responses"][0]["meta"]["identity"]["profile_id"] = "trend_5m"
    elif mutation == "wrong_formula":
        o["responses"][0]["meta"]["identity"]["formula_versions"] = [
            "oscillation_formula"
        ]
    elif mutation == "wrong_product":
        o["responses"][0]["meta"]["identity"]["product"] = "sm"
    elif mutation == "future_bar":
        o["responses"][0]["chart"]["value"]["bars"][0]["bar_end"] = c.as_of
    elif mutation == "uncompleted":
        o["responses"][0]["chart"]["value"]["bars"][0]["completed"] = False
    elif mutation == "curve_point":
        o["before"]["curves"][0]["points"] = "0,0 712,0"
    elif mutation == "duplicate_record":
        o["responses"][1]["reference"]["value"]["items"] *= 2
    elif mutation == "return_card":
        o["returned"]["cards"] = ["trade-someone_else"]
    elif mutation == "missing_empty":
        o["before"]["statuses"] = []
    elif mutation == "wrong_fusion_model":
        o["responses"][1]["reference"]["value"]["fusion"]["reference_model_version"] = (
            "minute_candidate"
        )
    elif mutation == "wrong_native_proof":
        p["code_sha"] = "f" * 40
    elif mutation == "missing_aux":
        o["auxiliary"].pop()
    with pytest.raises((ValueError, KeyError)):
        validate_legacy_capture(
            c, p, o, "1w", "dual" if mutation == "wrong_fusion_model" else "trend"
        )


def weekly_partial():
    c, p, o = sample()
    last = "2026-09-18T07:00:00+00:00"
    for row in o["responses"]:
        if row.get("chart"):
            row["chart"]["value"]["bars"][0].update(
                bar_end=last, trading_day="2026-09-18"
            )
        if row.get("reference"):
            value = row["reference"]["value"]
            value.update(reference_cutoff=last, actual_available_through="2026-09-18")
            row["reference"]["status"] = dict(
                status="warming", reason_code="NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL"
            )
    expected, _ = expected_curve(o["responses"][1]["reference"]["value"])
    for key in ("full", "before", "returned"):
        o[key]["curves"][0]["points"] = " ".join(f"{x},{y}" for x, y in expected)
    return c, p, o


def test_native_weekly_partial_retains_warming():
    c, p, o = weekly_partial()
    report = validate_legacy_capture(c, p, o, "1w", "trend")
    assert report["completed_week_window_warming"] is True


def test_weekly_partial_without_native_reason_rejected():
    c, p, o = weekly_partial()
    o["responses"][1]["reference"]["status"]["reason_code"] = "IGNORE_MISSING_DATA"
    with pytest.raises(ValueError, match="LEGACY_WEEKLY_PARTIAL_REASON"):
        validate_legacy_capture(c, p, o, "1w", "trend")


@pytest.mark.parametrize(
    "change",
    [
        "snapshot",
        "query_token",
        "explicit_page_false",
        "all_false",
        "aux_wrong_frequency",
        "return_wire",
    ],
)
def test_additional_legacy_identity_edges(change):
    c, p, o = sample()
    if change == "snapshot":
        o["responses"][1]["meta"]["snapshot_token"] = "wrong"
    elif change == "query_token":
        o["responses"][1]["url"] = o["responses"][1]["url"].replace(
            "snapshot_token=token1", "snapshot_token=wrong"
        )
    elif change == "explicit_page_false":
        o["responses"][1]["reference"]["value"]["page_parity"] = False
    elif change == "all_false":
        o["returned"]["all"] = "false"
    elif change == "aux_wrong_frequency":
        o["auxiliary"][0]["meta"]["identity"]["frequency"] = "5m"
    elif change == "return_wire":
        o["responses"] = [row for row in o["responses"] if row["phase"] != "return"]
    with pytest.raises((ValueError, KeyError)):
        validate_legacy_capture(c, p, o, "1w", "trend")


@pytest.mark.parametrize(
    "change",
    [
        "other_contract",
        "truthy_binding",
        "wrong_url",
        "wrong_http",
        "wrong_kind",
        "missing_binding",
        "invalid_order",
        "invalid_timestamp",
    ],
)
def test_physical_contract_and_real_xhr_binding_edges(change):
    c, p, o = sample()
    if change == "other_contract":
        o["responses"][0]["chart"]["value"]["bars"][0]["physical_contract"] = "SM2701"
    elif change == "truthy_binding":
        o["responses"][0]["xhr_binding"] = {"observed": True}
    elif change == "wrong_url":
        o["responses"][0]["xhr_binding"]["url"] = "http://127.0.0.1:8012/other"
    elif change == "wrong_http":
        o["responses"][0]["xhr_binding"]["http"] = 409
    elif change == "wrong_kind":
        o["responses"][0]["xhr_binding"]["evidence_kind"] = "snapshot_get"
    elif change == "missing_binding":
        del o["responses"][0]["xhr_binding"]
    elif change == "invalid_order":
        o["responses"][0]["xhr_binding"]["started_order"] = o["responses"][0][
            "xhr_binding"
        ]["completed_order"]
    elif change == "invalid_timestamp":
        o["responses"][0]["xhr_binding"]["completed_at"] = 0
    with pytest.raises(ValueError):
        validate_legacy_capture(c, p, o, "1w", "trend")


def test_historical_unbound_rows_explicitly_keep_limitation():
    c, p, o = sample()
    p.pop("task_sha256")
    o.pop("capture_schema")
    for row in o["responses"]:
        row.pop("xhr_binding")
    report = validate_legacy_capture(c, p, o, "1w", "trend")
    assert report["historical_actual_xhr_binding"] is False
    assert report["historical_unbound_compatibility"] is True


def test_new_prepare_cannot_downgrade_by_removing_capture_schema():
    c, p, o = sample()
    o.pop("capture_schema")
    for row in o["responses"]:
        row.pop("xhr_binding")
    with pytest.raises(ValueError):
        validate_legacy_capture(c, p, o, "1w", "trend")


def rewarming_sample(frequency="1d", mode="oscillation"):
    c, p, o = sample(frequency=frequency, mode=mode)
    for row in o["responses"]:
        if row["meta"]["identity"]["strategy"] != "oscillation":
            continue
        if row.get("chart"):
            row["chart"]["status"] = dict(
                status="warming", evidence_status="ACTIVE_CODE_VERIFIED",
                reason_code="NEWOW_OSCILLATION_WARMING",
            )
        if row.get("reference") and mode == "oscillation":
            row["reference"]["status"] = dict(
                status="warming", evidence_status="ACTIVE_CODE_VERIFIED",
                reason_code="NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING",
            )
    for phase in ("full", "before", "returned"):
        o[phase]["statuses"] = [
            "当前数据不足，待每日增量积累；历史部分仍在预热（2 个区段）",
            "历史覆盖不完整；仅统计有效区段内已完成的参考交易，跨中断记录不计入收益。"
            "2023-01-03 → 2026-09-17 · CJ2701 · 有效计算区段"
            "2026-09-18 → 2026-09-18 · CJ2701 · 来源价格不可用"
            "2026-09-19 → 2026-09-24 · CJ2701 · 重新预热中",
            "来源价格不可用后，当前策略参考正在重新预热；历史已验证记录继续展示。",
        ]
    return c, p, o


@pytest.mark.parametrize("frequency", ["1d", "1w"])
@pytest.mark.parametrize("mode", ["oscillation", "dual"])
def test_native_legacy_current_warming_preserves_history(frequency, mode):
    c, p, o = rewarming_sample(frequency, mode)
    report = validate_legacy_capture(c, p, o, frequency, mode)
    assert report["curve"]["closed_count"] == 1


@pytest.mark.parametrize("change", [
    "chart_reason", "chart_evidence", "reference_reason", "reference_evidence",
    "missing_coverage", "missing_price_gap", "foreign_contract", "out_of_window",
    "unbounded_tail", "overlapping_intervals", "missing_return_disclosure",
    "incomplete_bar", "source_identity", "token", "curve_decimal",
])
def test_legacy_warming_cannot_bypass_evidence(change):
    c, p, o = rewarming_sample()
    if change.startswith("chart_"):
        o["responses"][0]["chart"]["status"][
            "reason_code" if change.endswith("reason") else "evidence_status"
        ] = "UNKNOWN"
    elif change.startswith("reference_"):
        o["responses"][1]["reference"]["status"][
            "reason_code" if change.endswith("reason") else "evidence_status"
        ] = "UNKNOWN"
    elif change == "incomplete_bar":
        o["responses"][0]["chart"]["value"]["bars"][0]["completed"] = False
    elif change == "source_identity":
        o["responses"][0]["chart"]["value"]["bars"][0]["source_identity"] = ""
    elif change == "token":
        o["responses"][1]["meta"]["snapshot_token"] = "foreign"
    elif change == "curve_decimal":
        o["responses"][1]["reference"]["value"]["summary"]["sum_return_percentage_points"] = "2.50"
    elif change == "missing_return_disclosure":
        o["returned"]["statuses"] = []
    else:
        old = o["full"]["statuses"][1]
        replacement = {
            "missing_coverage": "",
            "missing_price_gap": old.replace("来源价格不可用", "有效计算区段"),
            "foreign_contract": old.replace("CJ2701", "RS2701"),
            "out_of_window": old.replace("2023-01-03", "2022-12-31"),
            "unbounded_tail": old.replace("2026-09-24", "2026-09-23"),
            "overlapping_intervals": old.replace("2026-09-19", "2026-09-17"),
        }[change]
        o["full"]["statuses"][1] = replacement
    with pytest.raises(ValueError):
        validate_legacy_capture(c, p, o, "1d", "oscillation")


@pytest.mark.parametrize("frequency", [None, "1m", "5m", "15m", "30m", "60m"])
def test_minute_chart_still_requires_ready(frequency):
    from scripts.newow_candidate_tools.wire import validate_bars
    c, _, o = rewarming_sample()
    with pytest.raises(ValueError, match="ACTUAL_CHART_NOT_READY"):
        validate_bars(c, o["responses"][0]["chart"], frequency=frequency, strategy="oscillation")


def separate_partner_sample(frequency="1d"):
    c, p, dual = rewarming_sample(frequency, "dual")
    _, _, partner = rewarming_sample(frequency, "oscillation")
    dual["responses"] = [r for r in dual["responses"] if not (
        r["meta"]["identity"]["strategy"] == "oscillation" and r.get("reference")
    )]
    return c, p, dual, partner


@pytest.mark.parametrize("frequency", ["1d", "1w"])
def test_dual_uses_explicit_same_snapshot_separate_scene(frequency):
    c, p, dual, partner = separate_partner_sample(frequency)
    result = validate_legacy_capture(c, p, dual, frequency, "dual", partner_observation=partner)
    assert result["checks"]["partner_reference_evidence"] == "SAME_SNAPSHOT_SEPARATE_SCENE"


@pytest.mark.parametrize("change", ["token", "hash", "physical_bar", "frequency", "code", "curve", "missing_source"])
def test_separate_partner_must_pass_full_scene_and_exact_snapshot(change):
    c, p, dual, partner = separate_partner_sample()
    if change in ("token", "hash", "physical_bar"):
        charts = [r for r in dual["responses"] if r.get("chart") and r["meta"]["identity"]["strategy"] == "oscillation"]
        for row in charts:
            if change == "token": row["meta"]["snapshot_token"] = "different"
            elif change == "hash": row["meta"]["input_content_sha256"] = "f" * 64
            else: row["chart"]["value"]["bars"][0]["physical_contract"] = "CJ2609"
    elif change == "frequency":
        for row in partner["responses"]: row["meta"]["identity"]["frequency"] = "1w"
    elif change == "code": partner["identity"]["code_sha"] = "f" * 40
    elif change == "curve": partner["full"]["curves"][0]["points"] = "0,0"
    else: partner = None
    with pytest.raises(ValueError):
        validate_legacy_capture(c, p, dual, "1d", "dual", partner_observation=partner)
