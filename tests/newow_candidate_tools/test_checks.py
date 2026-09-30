from test_audit import candidate as make_candidate, binding
import pytest
from scripts.newow_candidate_tools.checks import (
    functional_checks,
    validate_earlier,
    validate_recovery,
)


def test_missing_functional_observation_fails(tmp_path):
    candidate = make_candidate(tmp_path)
    with pytest.raises(ValueError, match="FUNCTIONAL_GATE"):
        functional_checks(candidate, "5m", "trend", {})


def test_earlier_requires_actual_pages(tmp_path):
    candidate = make_candidate(tmp_path)
    with pytest.raises(ValueError):
        validate_earlier(candidate, "5m", "trend", {})


def test_recovery_requires_actual_cancel_and_conflict(tmp_path):
    candidate = make_candidate(tmp_path)
    with pytest.raises(ValueError):
        validate_recovery(candidate, {})


def meta(c, f="5m"):
    return dict(
        identity=dict(product=c.product, frequency=f, strategy="trend"),
        as_of=c.as_of,
        snapshot_token="token-" + f,
        input_content_sha256="1" * 64,
    )


def identities(c):
    native = dict(
        code_sha=c.code_sha,
        as_of=c.as_of,
        mode="local_candidate_readonly",
        realtime=False,
    )
    return dict(
        api=native,
        web=dict(native, candidate_origin=c.api_origin),
        apiHttp=200,
        webHttp=200,
    )


def url(c, f, section, **params):
    from urllib.parse import urlencode

    return (
        c.api_origin
        + "/api/v1/market/newow/strategy-detail?"
        + urlencode(
            dict(
                product=c.product,
                frequency=f,
                section=section,
                strategy="trend",
                as_of=c.as_of,
                **params,
            )
        )
    )


def chart(c, at):
    return dict(
        delivery="delivered",
        status=dict(status="ready"),
        value=dict(
            bars=[
                dict(
                    bar_end=at,
                    physical_contract="CJ2605",
                    completed=True,
                    observation_eligible=True,
                    segment_id="segment",
                    source_identity="source",
                    trading_day=at[:10],
                )
            ],
            chart_from="2026-09-01",
            chart_through="2026-09-24",
        ),
    )


def earlier(c):
    old = chart(c, "2026-08-31T07:00:00Z")
    old["value"]["chart_through"] = "2026-08-31"
    return dict(
        errors=[],
        identities=identities(c),
        initial=dict(meta=meta(c), chart=chart(c, "2026-09-01T07:00:00Z")),
        pages=[
            dict(
                url=url(c, "5m", "chart", chart_older_window="1"),
                http=200,
                binding=binding(url(c, "5m", "chart", chart_older_window="1")),
                payload=dict(meta=meta(c), chart=old),
            )
        ],
        final=dict(chartVisible=True),
        topPriceBefore="123",
        topPriceAfter="123",
        settling=[dict(active=0, ready=True, price="123")] * 5,
        visibleActions=[
            dict(time="2026-08-31T07:00:00Z", rect=dict(width=4, height=4))
        ],
    )


def recovery(c):
    calls = []
    for f, section, http, token in (
        ("5m", "chart", 200, None),
        ("15m", "chart", 409, "token-5m"),
        ("15m", "reference", 409, "token-5m"),
        ("15m", "chart", 200, None),
        ("15m", "reference", 200, "token-15m"),
    ):
        params = dict(
            product=c.product,
            frequency=f,
            section=section,
            strategy="trend",
            as_of=c.as_of,
        )
        if token:
            params["snapshot_token"] = token
        payload = (
            dict(detail=dict(code="NEWOW_SNAPSHOT_GENERATION_CONFLICT"))
            if http == 409
            else dict(meta=meta(c, f), **{section: chart(c, "2026-09-24T06:00:00Z")})
        )
        calls.append(
            dict(
                url=url(c, f, section, **({"snapshot_token": token} if token else {})),
                http=http,
                params=params,
                payload=payload,
            )
        )
    target = url(c, "5m", "reference")
    return dict(
        identity_valid=True,
        pendingAtSwitch=True,
        identity=identities(c),
        targetUrl=target,
        targetId=3,
        events=[dict(event="failed", id=3, url=target, error="net::ERR_ABORTED")],
        timeout=dict(outcome="ACTUAL_CLIENT_TIMEOUT", error="AbortError", seconds=0.25),
        returnedChart=dict(
            http=200,
            xhr_binding=binding(url(c, "5m", "chart", chart_older_window="1")),
            meta=meta(c),
            chart=chart(c, "2026-09-24T06:00:00Z"),
        ),
        final=dict(
            url=c.web_origin + "/market/chart?symbol=cj&frequency=5m",
            cards=1,
            curves=1,
            statuses=[],
        ),
        snapshot_recovery=dict(http_calls=calls),
    )


def test_earlier_and_recovery_actual_shapes(tmp_path):
    c = make_candidate(tmp_path)
    assert validate_earlier(c, "5m", "trend", earlier(c))["status"] == "PASS"
    assert validate_recovery(c, recovery(c))["status"] == "PASS"


@pytest.mark.parametrize(
    "change",
    [
        "origin",
        "snapshot",
        "page_overlap",
        "incomplete_bar",
        "unstable",
        "no_visible_action",
        "changed_price",
    ],
)
def test_earlier_tamper_rejected(tmp_path, change):
    c = make_candidate(tmp_path)
    raw = earlier(c)
    if change == "origin":
        raw["pages"][0]["url"] = raw["pages"][0]["url"].replace(
            c.api_origin, "http://external.test"
        )
    elif change == "snapshot":
        raw["pages"][0]["payload"]["meta"]["snapshot_token"] = "other"
    elif change == "page_overlap":
        raw["pages"][0]["payload"]["chart"]["value"]["bars"][0]["bar_end"] = (
            "2026-09-01T07:00:00Z"
        )
    elif change == "incomplete_bar":
        raw["pages"][0]["payload"]["chart"]["value"]["bars"][0]["completed"] = False
    elif change == "unstable":
        raw["settling"][-1] = dict(active=1, ready=False, price="123")
    elif change == "no_visible_action":
        raw["visibleActions"] = []
    elif change == "changed_price":
        raw["topPriceAfter"] = "124"
    with pytest.raises(ValueError):
        validate_earlier(c, "5m", "trend", raw)


@pytest.mark.parametrize(
    "change",
    [
        "not_pending",
        "wrong_target",
        "fake_timeout",
        "stale_recovery",
        "wrong409",
        "missing409",
        "missing_bound_request",
    ],
)
def test_recovery_tamper_rejected(tmp_path, change):
    c = make_candidate(tmp_path)
    raw = recovery(c)
    if change == "not_pending":
        raw["pendingAtSwitch"] = False
    elif change == "wrong_target":
        raw["events"][0]["id"] = 99
    elif change == "fake_timeout":
        raw["timeout"]["seconds"] = 2
    elif change == "stale_recovery":
        raw["snapshot_recovery"]["http_calls"][4]["payload"]["meta"][
            "snapshot_token"
        ] = "token-5m"
    elif change == "wrong409":
        raw["snapshot_recovery"]["http_calls"][1]["payload"]["detail"]["code"] = "OTHER"
    elif change == "missing409":
        raw["snapshot_recovery"]["http_calls"].pop(2)
    elif change == "missing_bound_request":
        raw["returnedChart"]["xhr_binding"] = None
    with pytest.raises(ValueError):
        validate_recovery(c, raw)
