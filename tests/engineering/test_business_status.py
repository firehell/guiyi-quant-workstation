import importlib.util
import json
import subprocess
from io import BytesIO
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ops/macos/business-status.py"


def load_script():
    spec = importlib.util.spec_from_file_location("business_status", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_status(payloads):
    module = load_script()
    requested = []

    def read(path):
        requested.append(path)
        return payloads.get(path)

    result = module.collect(read)
    assert requested == [
        "/api/runtime/health",
        "/api/v1/subing-portfolio/status",
        "/api/simulation/monitor/overview",
    ]
    assert result["readonly"] is True
    return result["businesses"]


def test_retained_success_and_business_gaps_are_independent_of_service_health():
    stamp = "2026-11-20T06:30:00+00:00"
    rows = inspect_status(
        {
            "/api/runtime/health": {
                "readonly": True,
                "status": "ok",
                "components": {
                    "weekly_audit": {
                        "status": "failed",
                        "error_type": "DATABASE_ERROR",
                        "scope": "operational_full_history",
                        "through": None,
                        "completed": 2,
                        "total": 60,
                    },
                    "live_market": {
                        "status": "ok",
                        "coverage_state": "pending",
                        "operational_count": 60,
                        "subscribed_count": 59,
                        "last_bar_at": stamp,
                    },
                    "after_market": {
                        "status": "ok",
                        "last_successful_trading_day": "2026-11-20",
                    },
                    "alert": {
                        "status": "ok",
                        "coverage_state": "warming_up",
                        "scope_product_count": 60,
                        "last_processing_success_at": stamp,
                        "last_provider_accepted_at": stamp,
                    },
                },
            },
            "/api/v1/subing-portfolio/status": {
                "status": "WAITING_OBSERVATIONS",
                "run_id": None,
                "auto_order": False,
                "worker_code": "PORTFOLIO_INITIAL_PREFIX_INCOMPLETE",
                "products": [],
            },
            "/api/simulation/monitor/overview": {
                "version": "simulation_monitor_v1",
                "status": "partial",
                "readback_status": "stale",
                "readback_at": stamp,
                "trading_scope": {"status": "FLATTEN_PENDING"},
                "observer": {"executable_product_count": 0, "status": "stale"},
            },
        }
    )
    assert rows["historical_research"]["reason"] == "DATABASE_ERROR"
    assert rows["market"]["progress"]["live_coverage"] == "pending"
    assert rows["market"]["last_success"]["canonical_trading_day"] == "2026-11-20"
    assert rows["alerts"]["progress"]["coverage"] == "warming_up"
    assert rows["alerts"]["last_success"]["provider_accepted_at"] == stamp
    assert rows["subing_paper"]["reason"] == "PORTFOLIO_INITIAL_PREFIX_INCOMPLETE"
    assert rows["subing_paper"]["last_success"] is None
    assert rows["tqkq"]["progress"]["readback_status"] == "stale"
    assert rows["tqkq"]["progress"]["scope_status"] == "FLATTEN_PENDING"
    assert rows["tqkq"]["last_success"] is None


def test_missing_or_untrusted_sources_leave_the_affected_business_unknown():
    rows = inspect_status(
        {
            "/api/runtime/health": {
                "readonly": False,
                "components": {"alert": {"status": "ok"}},
            },
            "/api/v1/subing-portfolio/status": {
                "status": "RUNNING",
                "auto_order": True,
            },
            "/api/simulation/monitor/overview": {
                "version": "simulation_monitor_v1",
                "status": "available",
                "readback_status": "verified",
                "position_projection_complete": True,
                "readback_at": "2026-11-20T06:30:00+00:00",
                "issues": ["private"],
            },
        }
    )
    for name in ("historical_research", "market", "alerts", "subing_paper"):
        assert rows[name]["status"] == "unknown"
        assert rows[name]["last_success"] is None
    assert rows["tqkq"]["last_success"] == {
        "account_readback_at": "2026-11-20T06:30:00+00:00"
    }
    assert "private" not in str(rows)


def test_http_reader_uses_only_local_get_and_rejects_redirects_and_oversized_responses(
    monkeypatch,
):
    module = load_script()
    calls = []

    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))

        def request(self, method, path, *, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            return response

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(module, "HTTPConnection", Connection)
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 12)
    for status, content, expected in [
        (200, b'{"test": 1}', {"test": 1}),
        (302, b'{"test": 1}', None),
        (200, b'{"test": 1234}', None),
        (200, b"bad payload", None),
    ]:
        response = BytesIO(content)
        response.status = status
        assert module.read_local(module.RUNTIME) == expected
        assert response.closed
    assert (
        calls
        == [
            ("127.0.0.1", 8000, 20),
            ("GET", module.RUNTIME, {"Accept": "application/json"}),
            "closed",
        ]
        * 4
    )
    response = BytesIO(b"{}")
    response.status = 200
    assert module.read_local(module.PAPER) == {}
    assert calls[-3:] == [
        ("127.0.0.1", 8000, 5),
        ("GET", module.PAPER, {"Accept": "application/json"}),
        "closed",
    ]


def test_completed_offline_replay_is_available_when_all_live_sources_disconnect(
    tmp_path,
):
    module = load_script()
    path = tmp_path / "result.json"
    identity = "a" * 64
    products = ["jm", "rb", "sa"]
    report = {
        "kind": "THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH",
        "products": products,
        "requested": ["2026-11-09", "2026-11-17"],
        "plan_hash": identity,
        "input_id": identity,
        "execution_facts_sha256": dict.fromkeys(products, identity),
        "coverage": [
            {"status": "VERIFIED", "product": product} for product in products
        ],
        "portfolio_runs": {"A": {"policy": {}}, "B": {"policy": {}}},
    }
    path.write_text(json.dumps(report))
    replay = module.read_research_result(path)
    rows = module.collect(lambda _: None, replay=replay)["businesses"]
    assert rows["market"]["status"] == "unknown"
    assert rows["historical_research"]["status"] == "unknown"
    assert rows["historical_research"]["offline_replay"] == {
        "status": "available",
        "scope": {"products": products, "since": "2026-11-09", "through": "2026-11-17"},
        "sha256": replay["sha256"],
    }
    report["coverage"][0]["status"] = "INPUT_MISSING"
    path.write_text(json.dumps(report))
    assert module.read_research_result(path)["status"] == "invalid"


def test_original_status_entry_accepts_business_option():
    result = subprocess.run(
        [str(SCRIPT.with_name("local-services-status.sh")), "--business", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--research-result" in result.stdout


def test_paper_status_reports_first_missing_prefix_without_inventing_legacy_counts():
    module = load_script()
    payload = {"status": "WAITING_OBSERVATIONS", "auto_order": False}
    assert module.subing_paper(payload)["progress"]["observation_gaps"] is None
    gap = {
        "product": "jm",
        "contract": "JM2701",
        "frequency": "1m",
        "count": 15,
        "first_missing_at": "2026-11-20T01:01:00Z",
    }
    payload["missing_observations"] = [gap]
    assert module.subing_paper(payload)["progress"]["observation_gaps"] == {
        "count": 15,
        "groups": [gap],
    }
    payload["missing_observations"] = [gap, gap]
    assert module.subing_paper(payload)["progress"]["observation_gaps"] is None
