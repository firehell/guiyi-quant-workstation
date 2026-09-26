"""Read-only formal PF W1 API smoke on development code and actual Catalog."""

import json
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

load_dotenv(Path.home() / "Library/Application Support/GuiyiQuant/project.env", override=False)

from app.db.readonly import readonly_transaction  # noqa: E402
from app.db.session import SessionLocal, get_db  # noqa: E402
from app.main import app  # noqa: E402


def readonly_db() -> Generator[Session]:
    with SessionLocal() as session, readonly_transaction(session):
        yield session


app.dependency_overrides[get_db] = readonly_db
try:
    with TestClient(app) as client:
        cap = client.get("/api/v1/market/newow/product-capabilities")
        capability = cap.json()
        if (cap.status_code != 200
                or capability["schema_version"] != "newow_product_capabilities_v16"
                or len(capability["weekly_products"]) != 54
                or "pf" not in capability["weekly_products"]
                or any(p in capability["weekly_products"] for p in (
                    "pl", "pr", "px", "sf", "sh", "sm"
                ))):
            raise ValueError("CAPABILITY_SCOPE_INVALID")
        expected = {
            "trend": {"chart": "ready", "reference": "ready", "auxiliary": "warming", "comparator": "not_applicable"},
            "oscillation": {"chart": "ready", "reference": "ready", "auxiliary": "warming", "comparator": "unavailable"},
            "main_rise": {"chart": "ready", "reference": "ready", "auxiliary": "warming", "comparator": "not_applicable"},
        }
        sections = []
        for strategy, statuses in expected.items():
            for section, expected_status in statuses.items():
                params = {
                    "product": "pf", "strategy": strategy, "frequency": "1w", "section": section,
                    "as_of": "2026-09-18T07:00:00.000001Z",
                }
                if section == "auxiliary":
                    params["component"] = "macd"
                response = client.get("/api/v1/market/newow/strategy-detail", params=params)
                if response.status_code != 200:
                    raise ValueError(f"SECTION_HTTP_INVALID:{strategy}:{section}")
                payload = response.json()
                actual = payload[section]["status"]["status"]
                if actual != expected_status:
                    raise ValueError(f"SECTION_STATUS_INVALID:{strategy}:{section}")
                sections.append([strategy, section, actual])
        closed = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={"product": "pl", "strategy": "trend", "frequency": "1w", "section": "chart"},
        )
        if (closed.status_code != 409
                or closed.json().get("detail", {}).get("code") != "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            raise ValueError("OTHER_PRODUCT_SCOPE_OPEN")
        result = {"status": "passed", "scope_count": 54, "schema_version": capability["schema_version"],
                  "sections": sections, "pl_still_closed": True, "database_mode": "read_only"}
        (Path(__file__).parent / "pf-formal-scope-smoke.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))
finally:
    app.dependency_overrides.clear()
