"""Read-only formal SR W1 API smoke on the current development code."""

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
        if cap.status_code != 200:
            raise ValueError("CAPABILITY_FAILED")
        capability = cap.json()
        if (capability["schema_version"] != "newow_product_capabilities_v13"
                or len(capability["weekly_products"]) != 51
                or "sr" not in capability["weekly_products"]
                or any(product in capability["weekly_products"] for product in (
                    "pf", "pk", "pl", "pr", "px", "rs", "sf", "sh", "sm"
                ))):
            raise ValueError("CAPABILITY_SCOPE_INVALID")
        results = []
        for strategy in ("trend", "oscillation", "main_rise"):
            token = None
            for section in ("chart", "reference", "auxiliary"):
                params = {
                    "product": "sr", "strategy": strategy,
                    "frequency": "1w", "section": section,
                    "as_of": "2026-09-18T07:00:00.000001Z",
                }
                if token:
                    params["snapshot_token"] = token
                if section == "auxiliary":
                    params["component"] = "macd"
                response = client.get(
                    "/api/v1/market/newow/strategy-detail", params=params
                )
                if response.status_code != 200:
                    raise ValueError(f"FORMAL_SECTION_FAILED:{strategy}:{section}:{response.status_code}")
                payload = response.json()
                if payload[section]["status"]["status"] != "ready":
                    raise ValueError(f"FORMAL_SECTION_NOT_READY:{strategy}:{section}:{payload[section]['status']['status']}")
                token = payload["meta"]["snapshot_token"]
                results.append((strategy, section, "READY"))
        closed = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={"product": "pf", "strategy": "trend", "frequency": "1w", "section": "chart"},
        )
        if (closed.status_code != 409
                or closed.json().get("detail", {}).get("code") != "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            raise ValueError("OTHER_PRODUCT_SCOPE_OPEN")
        result = {"status": "passed", "scope_count": 51, "schema_version": capability["schema_version"],
                  "formal_sections": results, "pf_still_closed": True,
                  "database_mode": "read_only"}
        (Path(__file__).parent / "sr-formal-scope-smoke.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))
finally:
    app.dependency_overrides.clear()
