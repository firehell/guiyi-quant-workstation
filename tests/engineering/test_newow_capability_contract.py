"""Frozen historical scopes plus actual Python response -> TypeScript validation."""
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess

from fastapi import Request
from starlette.responses import Response

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "services/quant-api/app/market_data/newow/capability_contracts.json"


def test_existing_32_capability_contracts_remain_frozen():
    contracts = json.loads(REGISTRY.read_text())
    frozen = {f"newow_product_capabilities_v{number}": contracts[f"newow_product_capabilities_v{number}"]
              for number in range(3, 35)}
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == "e794a557731cdaafc6878a4a58772b756b4311be2b3c4a4b248c6706baf04bf7"


def test_generated_web_contract_is_current():
    subprocess.run(["node", "tools/generate_newow_capabilities.mjs", "--check"],
                   cwd=ROOT, check=True, capture_output=True, text=True)


def test_real_backend_capabilities_pass_the_actual_web_validator():
    from app.api.market_newow import newow_product_capabilities

    cutoff = datetime(2026, 9, 3, 7, tzinfo=UTC)
    scenarios = [
        {},
        {"candidate_preview_as_of": cutoff},
        {"candidate_preview_as_of": cutoff, "au_period_preview": True},
        {"candidate_preview_as_of": cutoff, "hourly_preview_products": frozenset({"pd", "pt"})},
        {"candidate_preview_as_of": cutoff, "hourly_preview_products": frozenset({"ap"})},
        {"intraday_preview_products": frozenset({"rb"})},
        {"intraday_preview_products": frozenset({"rb", "jm"}), "intraday_preview_batch": True},
        {"intraday_preview_products": frozenset({"fu"}), "intraday_preview_batch": True},
    ]
    cases = []
    for state in scenarios:
        request = Request({"type": "http", "state": state, "headers": []})
        result = newow_product_capabilities(request)
        payload = (json.loads(result.body) if isinstance(result, Response)
                   else result.model_dump(mode="json", exclude_none=True))
        cases.append({"payload": payload, "valid": True})
        for mutation in [
            {"release_stage": "unknown"},
            {"schema_version": "newow_product_capabilities_v9999"},
            {"open_frequencies": payload["open_frequencies"] + ["1m"]},
            {"unexpected": True},
            {"open_sections": []},
        ]:
            cases.append({"payload": payload | mutation, "valid": False})
        if payload.get("weekly_products"):
            cases.append({"payload": payload | {"weekly_products": payload["weekly_products"][::-1]}, "valid": False})
        if "intraday_products" in payload:
            cases.append({"payload": payload | {"intraday_products": []}, "valid": False})
    subprocess.run(["node", "apps/quant-web/scripts/checkCapabilityContract.mjs"],
                   input=json.dumps(cases), cwd=ROOT, check=True, capture_output=True, text=True)
