from __future__ import annotations

from contextlib import nullcontext
from datetime import date
import importlib
import io
import json

import pytest

from app.guiyi_cli.main import build_parser, main
from app.guiyi_cli.research_requests import build_research_request
from app.market_data.subing_watch.contracts import load_subing_watch_policy


def _module():
    try:
        return importlib.import_module(
            "app.research.subing.subing_watch_research_service"
        )
    except ModuleNotFoundError:
        pytest.fail("SuBing Watch research service is not implemented")


def _arguments(*, symbols: str = "jm,ag") -> list[str]:
    return [
        "research",
        "subing-watch",
        "--symbols",
        symbols,
        "--since",
        "2026-08-01",
        "--through",
        "2026-08-31",
        "--forward-bars",
        "1,2,4,8",
    ]


def test_parser_builds_deterministic_watch_request_and_json_is_default() -> None:
    module = _module()
    args = build_parser().parse_args(_arguments())

    assert args.format == "json"
    assert build_research_request(args) == module.SubingWatchResearchRequest(
        since=date(2026, 8, 1),
        through=date(2026, 8, 31),
        symbols=("ag", "jm"),
        forward_bars=(1, 2, 4, 8),
    )
    active_args = build_parser().parse_args(_arguments(symbols="active"))
    assert build_research_request(active_args).symbols == "active"


class _WatchService:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[object] = []

    def run(self, request: object) -> object:
        self.requests.append(request)
        return self.result


def test_cli_routes_only_to_watch_service_and_prints_json_stdout() -> None:
    module = _module()
    product = module.empty_subing_watch_product_diagnostics("jm", (1,))
    service = _WatchService(module.SubingWatchResearchResult((product,)))
    stdout = io.StringIO()
    stderr = io.StringIO()

    def forbidden(_session):
        raise AssertionError("unrelated research service must not be constructed")

    code = main(
        [
            "research",
            "subing-watch",
            "--symbols",
            "jm",
            "--since",
            "2026-08-01",
            "--through",
            "2026-08-31",
            "--forward-bars",
            "1",
        ],
        session_factory=lambda: nullcontext(object()),
        research_service_factory=forbidden,
        lifecycle_research_service_factory=forbidden,
        performance_service_factory=forbidden,
        watch_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert len(service.requests) == 1
    payload = json.loads(stdout.getvalue())
    assert payload["command"] == "research.subing-watch"
    assert payload["readonly"] is True
    assert payload["symbols"] == ["jm"]
    assert payload["products"][0]["symbol"] == "jm"


def test_symbol_outside_active_scope_returns_exact_public_readonly_error() -> None:
    module = _module()

    class _NoReadMarketData:
        def query_actual_dominant_trading_days(self, _request):
            raise AssertionError("invalid scope must fail before market read")

    service = module.SubingWatchResearchService(
        _NoReadMarketData(),
        products=("jm",),
        policy=load_subing_watch_policy(),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "research",
            "subing-watch",
            "--symbols",
            "ag",
            "--since",
            "2026-08-01",
            "--through",
            "2026-08-31",
        ],
        session_factory=lambda: nullcontext(object()),
        watch_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.subing-watch",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "SUBING_WATCH_RESEARCH_SYMBOL_INVALID",
            "type": "SubingWatchResearchError",
        },
    }


@pytest.mark.parametrize(
    "arguments",
    (
        ["research", "subing-watch", "--symbols", "jm", "--since", "2026-08-01"],
        [*_arguments(), "--cache"],
        [*_arguments(), "--publish"],
        [*_arguments(), "--write"],
        [*_arguments(), "--warm-cache"],
        [*_arguments(), "--format", "csv"],
        _arguments(symbols="jm,,ag"),
        [*_arguments(), "--forward-bars", "1,3"],
        [
            "research",
            "subing-watch",
            "--symbols",
            "jm",
            "--since",
            "2026-09-01",
            "--through",
            "2026-08-31",
        ],
    ),
)
def test_invalid_or_mutating_watch_cli_input_fails_before_service_construction(
    arguments: list[str],
) -> None:
    calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        arguments,
        session_factory=lambda: nullcontext(object()),
        watch_research_service_factory=lambda session: calls.append(session),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert calls == []
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["command"] == "research.subing-watch"
    assert payload["readonly"] is True
    assert payload["error"]["code"] == "CLI_ARGUMENT_INVALID"
