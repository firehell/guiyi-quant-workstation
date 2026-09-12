"""Real independent HTTP connections exercise process-local Newow navigation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from decimal import Decimal

import httpx2 as httpx

from newow.socket_app_support import socket_app

DETAIL = "/api/v1/market/newow/strategy-detail"
IDENTITY = {"product": "rb", "strategy": "trend", "frequency": "1d"}
BASE = {**IDENTITY, "as_of": "2024-06-04T08:00:00+00:00"}


def get(client, params, status=200, code=None):
    response = client.get(DETAIL, params=params)
    assert response.status_code == status, response.text
    body = response.json()
    if code:
        assert body == {"detail": {"code": code}}
    return body


def stable(body):
    """Wall-clock read_at is observational; business payload and tokens are stable."""
    return {**body, "meta": {k: v for k, v in body["meta"].items() if k != "read_at"}}


def client_for(stack, url):
    return stack.enter_context(
        httpx.Client(
            base_url=url,
            trust_env=False,
            timeout=30,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
    )


def test_four_socket_connections_keep_navigation_and_history_bound_to_snapshot():
    with socket_app() as (url, _pid), ExitStack() as stack:
        clients = [client_for(stack, url) for _ in range(4)]
        chart_params = {**BASE, "chart_limit": 25}
        # Independent clients request the same cold chart concurrently.
        with ThreadPoolExecutor(max_workers=4) as pool:
            charts = list(pool.map(lambda client: get(client, chart_params), clients))
        first = charts[0]
        assert all(stable(chart) == stable(first) for chart in charts)
        token = first["meta"]["snapshot_token"]
        assert token and len(first["meta"]["input_content_sha256"]) == 64
        chart = first["chart"]["value"]
        assert len(chart["bars"]) == 25
        assert {bar["physical_contract"] for bar in chart["bars"]} == {"RB2605"}
        assert len(chart["frames"]) == 25
        assert all(bar["completed"] for bar in chart["bars"])
        assert all(Decimal(bar["close"]) > 0 for bar in chart["bars"])
        assert chart["next_older_window"]
        reference_params = {
            **BASE,
            "section": "reference",
            "performance_since": "2023-01-04",
            "performance_through": "2024-06-04",
            "history_limit": 1,
            "snapshot_token": token,
        }
        auxiliary_params = {
            **BASE,
            "section": "auxiliary",
            "component": "zhaoyao_mirror",
            "snapshot_token": token,
            "from": chart["chart_from"],
            "through": chart["chart_through"],
        }
        references = []
        auxiliaries = []
        # Rotate which connection follows each chart with reference and subplot.
        for index in range(4):
            references.append(get(clients[(index + 1) % 4], reference_params))
            auxiliaries.append(get(clients[(index + 2) % 4], auxiliary_params))
        assert all(stable(value) == stable(references[0]) for value in references)
        assert all(stable(value) == stable(auxiliaries[0]) for value in auxiliaries)
        assert all(
            value["meta"]["snapshot_token"] == token
            for value in (*references, *auxiliaries)
        )
        reference = references[0]["reference"]["value"]
        assert reference["summary"]["closed_count"] > 2
        assert reference["executable"] is reference["auto_order"] is False
        assert reference["next_before"]
        trade = reference["items"][0]
        assert trade["entry_signal_id"] and trade["reference_trade_id"]
        assert trade["physical_contract"] == "RB2605"
        assert Decimal(trade["entry_reference_price"]) > 0
        auxiliary = auxiliaries[0]["auxiliary"]["value"]
        assert auxiliary["component"] == "zhaoyao_mirror"
        assert auxiliary["page_parity"] is True
        assert auxiliary["formal_signal_eligible"] is False
        subplot_ends = [
            end for segment in auxiliary["segments"] for end in segment["bar_ends"]
        ]
        # Auxiliary keeps its physical warm-up prefix; the visible suffix aligns.
        assert subplot_ends[-len(chart["bars"]) :] == [
            bar["bar_end"] for bar in chart["bars"]
        ]
        for segment in auxiliary["segments"]:
            assert len(segment["data"]["entry"]) == len(segment["bar_ends"])
            assert segment["physical_contract"] == "RB2605"
        next_reference = get(
            clients[3],
            {
                **reference_params,
                "history_before": reference["next_before"],
            },
        )
        older_trade = next_reference["reference"]["value"]["items"][0]
        assert older_trade["reference_trade_id"] != trade["reference_trade_id"]
        assert older_trade["entry_bar_end"] < trade["entry_bar_end"]
        assert next_reference["reference"]["value"]["summary"] == reference["summary"]
        assert next_reference["meta"]["snapshot_token"] == token
        older = get(
            clients[1],
            {
                **chart_params,
                "snapshot_token": token,
                "chart_older_window": chart["next_older_window"],
            },
        )
        assert older["meta"]["snapshot_token"] == token
        assert (
            older["chart"]["value"]["bars"][-1]["bar_end"] < chart["bars"][0]["bar_end"]
        )
        # Explicit range plus cursor exercises chart paging within one window.
        window_params = {
            **chart_params,
            "snapshot_token": token,
            "from": "2023-01-04",
            "through": "2024-06-04",
        }
        window = get(clients[2], window_params)["chart"]["value"]
        assert window["next_before"]
        previous = get(
            clients[0], {**window_params, "chart_before": window["next_before"]}
        )
        assert previous["meta"]["snapshot_token"] == token
        assert (
            previous["chart"]["value"]["bars"][-1]["bar_end"]
            < window["bars"][0]["bar_end"]
        )
        # Locate an actual reference entry by day and verify its stable marker ID.
        located = get(
            clients[3],
            {
                **chart_params,
                "snapshot_token": token,
                "from": older_trade["entry_trading_day"],
                "through": older_trade["entry_trading_day"],
            },
        )
        actions = located["chart"]["value"]["actions"]
        entry = next(
            action
            for action in actions
            if action["signal_id"] == older_trade["entry_signal_id"]
        )
        assert entry["reference_price"] == older_trade["entry_reference_price"]
        assert entry["segment_id"] == older_trade["segment_id"]
        assert located["meta"]["snapshot_token"] == token
        for change in (
            {"strategy": "oscillation"},
            {"as_of": "2024-06-03T08:00:00+00:00"},
        ):
            get(
                clients[0],
                {**chart_params, "snapshot_token": token, **change},
                409,
                "NEWOW_SNAPSHOT_GENERATION_CONFLICT",
            )
        for change in (
            {"strategy": "oscillation"},
            {"frequency": "60m"},
            {"product": "ag"},
            {"as_of": "2024-06-03T08:00:00+00:00"},
        ):
            get(
                clients[1],
                {
                    **chart_params,
                    "snapshot_token": token,
                    "chart_older_window": chart["next_older_window"],
                    **change,
                },
                409,
                "NEWOW_CHART_CURSOR_INVALID",
            )


def test_same_facts_in_another_process_and_restart_do_not_accept_old_token():
    with (
        socket_app() as (url_a, pid_a),
        socket_app() as (url_b, pid_b),
        ExitStack() as stack,
    ):
        assert pid_a != pid_b
        a, b = client_for(stack, url_a), client_for(stack, url_b)
        params = {**BASE, "chart_limit": 25}
        first, second = get(a, params), get(b, params)
        token_a, token_b = (
            first["meta"]["snapshot_token"],
            second["meta"]["snapshot_token"],
        )
        assert token_a and token_b and token_a != token_b
        assert (
            first["meta"]["input_content_sha256"]
            == second["meta"]["input_content_sha256"]
        )
        assert first["chart"]["value"]["bars"] == second["chart"]["value"]["bars"]
        assert first["chart"]["value"]["frames"] == second["chart"]["value"]["frames"]
        get(
            b,
            {**params, "snapshot_token": token_a},
            409,
            "NEWOW_SNAPSHOT_GENERATION_CONFLICT",
        )
        reference_params = {
            **BASE,
            "section": "reference",
            "performance_since": "2023-01-04",
            "performance_through": "2024-06-04",
            "history_limit": 1,
        }
        get(
            b,
            {**reference_params, "snapshot_token": token_a},
            409,
            "NEWOW_SNAPSHOT_GENERATION_CONFLICT",
        )
        own_reference = get(b, {**reference_params, "snapshot_token": token_b})
        assert own_reference["meta"]["snapshot_token"] == token_b
        assert own_reference["reference"]["value"]["summary"]["closed_count"] > 2
        assert (
            get(a, {**params, "snapshot_token": token_a})["meta"]["snapshot_token"]
            == token_a
        )
        assert (
            get(b, {**params, "snapshot_token": token_b})["meta"]["snapshot_token"]
            == token_b
        )
    with socket_app() as (url_restart, _pid), ExitStack() as stack:
        restarted = client_for(stack, url_restart)
        get(
            restarted,
            {**params, "snapshot_token": token_a},
            409,
            "NEWOW_SNAPSHOT_GENERATION_CONFLICT",
        )
        get(
            restarted,
            {
                **params,
                "snapshot_token": token_a,
                "chart_older_window": first["chart"]["value"]["next_older_window"],
            },
            409,
            "NEWOW_CHART_CURSOR_INVALID",
        )
        fresh = get(restarted, params)
        assert fresh["meta"]["snapshot_token"] not in (token_a, token_b)
        assert (
            fresh["meta"]["input_content_sha256"]
            == first["meta"]["input_content_sha256"]
        )
