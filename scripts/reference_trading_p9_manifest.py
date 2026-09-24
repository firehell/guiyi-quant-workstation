#!/usr/bin/env python3
"""Enumerate the formal P9 ReferenceTrading scope without reading or writing market data.

The output is an identity inventory, not a data-readiness or activation plan.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile

from sqlalchemy import text

from app.market_data.newow.product_release import (
    CAPABILITY_SCHEMA_VERSION, OPEN_WEEKLY_PRODUCTS, candidate_input_quality_policy,
)
from app.market_data.operational_universe import load_active_products, load_operational_products
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import (
    REFERENCE_MODEL_VERSION as NEWOW_MODEL_VERSION, futures_adaptation_version,
)
from guiyi_quant.reference_trading import RecordingMode, StreamIdentity
from guiyi_quant.subing_reference import (
    FORMULA_VERSIONS, REFERENCE_MODEL_VERSION as SUBING_MODEL_VERSION,
    REFERENCE_MODEL_VERSION_V2 as SUBING_MODEL_VERSION_V2,
)


ROOT = Path(__file__).resolve().parents[1]
NEWOW_STRATEGIES = (ProductStrategy.TREND, ProductStrategy.OSCILLATION, ProductStrategy.MAIN_RISE)
SUBING_HISTORICAL = ("15m", "30m", "60m", "1d")
SUBING_FORWARD = ("15m", "30m", "60m")


def _newow(product: str, strategy: ProductStrategy, frequency: str, *, forward: bool) -> StreamIdentity:
    identity = build_product_identity(
        product, strategy, ProductFrequency(frequency),
        input_quality_policy=candidate_input_quality_policy(
            product, frequency, candidate_weekly=False,
        ),
    )
    return StreamIdentity(
        f"newow_{strategy.value}", identity.formula_versions, identity.profile_id,
        NEWOW_MODEL_VERSION, futures_adaptation_version(frequency), product,
        frequency, "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION if forward else RecordingMode.HISTORICAL_REPLAY,
        "completed_canonical_v1" if forward else None,
    )


def _subing(product: str, frequency: str, *, forward: bool) -> StreamIdentity:
    return StreamIdentity(
        "subing_reference", (FORMULA_VERSIONS[frequency],),
        f"subing_reference_{frequency}_v1",
        SUBING_MODEL_VERSION_V2 if frequency == "1d" else SUBING_MODEL_VERSION,
        "subing_actual_dominant_v1", product.upper(), frequency,
        "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION if forward else RecordingMode.HISTORICAL_REPLAY,
        "completed_live_v1" if forward else None,
    )


def enumerate_scope(
    active: tuple[str, ...], operational: tuple[str, ...], weekly: tuple[str, ...],
    existing: dict[str, dict[str, object]],
) -> dict[str, object]:
    if (
        len(active) != 60 or len(set(active)) != 60
        or len(operational) != 60 or set(operational) != set(active)
        or len(weekly) != 60 or set(weekly) != set(active)
    ):
        raise ValueError("P9_SCOPE_UNIVERSE_INVALID")
    rows: list[dict[str, object]] = []

    def add(identity: StreamIdentity, gate: str) -> None:
        stored = existing.get(identity.stream_id)
        rows.append({
            "stream_id": identity.stream_id,
            "product": identity.product,
            "strategy_code": identity.strategy_code,
            "frequency": identity.frequency,
            "recording_mode": identity.recording_mode.value,
            "formula_versions": list(identity.formula_versions),
            "profile_id": identity.profile_id,
            "reference_model_version": identity.reference_model_version,
            "futures_adaptation_version": identity.futures_adaptation_version,
            "observation_policy_version": identity.observation_policy_version,
            "gate": gate,
            "existing": stored,
            "data_gate": "UNVERIFIED" if gate == "FORMAL_CANDIDATE" else "NOT_APPLICABLE",
        })

    for product in active:
        for strategy in NEWOW_STRATEGIES:
            for frequency in ("1d", "1w"):
                add(_newow(product, strategy, frequency, forward=False), "FORMAL_CANDIDATE")
            add(_newow(product, strategy, "60m", forward=False), "CAPABILITY_CLOSED")
            for frequency in ("1d", "1w"):
                add(_newow(product, strategy, frequency, forward=True), "FORMAL_CANDIDATE")
            add(_newow(product, strategy, "60m", forward=True), "CAPABILITY_CLOSED")
    for product in operational:
        for frequency in SUBING_HISTORICAL:
            add(_subing(product, frequency, forward=False), "FORMAL_CANDIDATE")
        for frequency in SUBING_FORWARD:
            add(_subing(product, frequency, forward=True), "FORMAL_CANDIDATE")
        rows.append({
            "stream_id": None, "product": product.upper(), "strategy_code": "htdy",
            "frequency": "15m", "recording_mode": "forward_observation",
            "gate": "MODEL_NOT_APPROVED", "existing": None,
            "data_gate": "NOT_APPLICABLE",
        })
    rows.sort(key=lambda row: (
        str(row["recording_mode"]), str(row["product"]),
        str(row["strategy_code"]), str(row["frequency"]),
    ))
    identities = [row["stream_id"] for row in rows if row["stream_id"] is not None]
    if len(identities) != len(set(identities)):
        raise ValueError("P9_SCOPE_IDENTITY_DUPLICATE")
    counts = {
        "historical_formal": sum(row["recording_mode"] == "historical_replay" and row["gate"] == "FORMAL_CANDIDATE" for row in rows),
        "forward_formal": sum(row["recording_mode"] == "forward_observation" and row["gate"] == "FORMAL_CANDIDATE" for row in rows),
        "historical_capability_closed": sum(row["recording_mode"] == "historical_replay" and row["gate"] == "CAPABILITY_CLOSED" for row in rows),
        "forward_capability_closed": sum(row["recording_mode"] == "forward_observation" and row["gate"] == "CAPABILITY_CLOSED" for row in rows),
        "model_not_approved": sum(row["gate"] == "MODEL_NOT_APPROVED" for row in rows),
        "existing_formal": sum(row["gate"] == "FORMAL_CANDIDATE" and row["existing"] is not None for row in rows),
    }
    unmatched_existing = sorted(set(existing) - set(identities))
    counts["unmatched_existing"] = len(unmatched_existing)
    return {"counts": counts, "streams": rows, "unmatched_existing_stream_ids": unmatched_existing}


def _existing_from_db(expected_database: str) -> tuple[str, str, dict[str, dict[str, object]]]:
    from app.db.session import engine

    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN READ ONLY")
        try:
            database = connection.execute(text("SELECT current_database()")).scalar_one()
            if database != expected_database:
                raise ValueError("P9_DATABASE_IDENTITY_MISMATCH")
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if version not in {"20260919_0047", "20260923_0048"}:
                raise ValueError("P9_SCHEMA_VERSION_UNEXPECTED")
            rows = connection.execute(text(
                "SELECT stream_id, recording_mode, enabled, health, active_revision_id, "
                "latest_seq, row_version FROM reference_streams"
            )).mappings().all()
            return database, version, {
                row["stream_id"]: {
                    "recording_mode": row["recording_mode"], "enabled": row["enabled"],
                    "health": row["health"], "active_revision_id": row["active_revision_id"],
                    "latest_seq": row["latest_seq"], "row_version": row["row_version"],
                }
                for row in rows
            }
        finally:
            connection.rollback()


def write_new_manifest(path: Path, body: dict[str, object]) -> Path:
    if not path.is_absolute():
        raise ValueError("P9_OUTPUT_PATH_INVALID")
    parent = path.parent.resolve(strict=True)
    if not parent.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not parent.is_dir():
        raise ValueError("P9_OUTPUT_PATH_INVALID")
    output = parent / path.name
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(body, sort_keys=True, indent=2) + "\n")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-code-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-db", action="store_true")
    parser.add_argument("--expected-database-name")
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.expected_code_sha != commit or len(commit) != 40:
        parser.error("exact code SHA mismatch")
    if subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain=v1"],
        cwd=ROOT, text=True,
    ).strip():
        parser.error("manifest requires a clean worktree")
    if args.with_db != bool(args.expected_database_name):
        parser.error("--with-db requires --expected-database-name and vice versa")
    active, operational = load_active_products(), load_operational_products()
    database, existing_version, existing = (
        _existing_from_db(args.expected_database_name)
        if args.with_db else ("NOT_QUERIED", "NOT_QUERIED", {})
    )
    body = enumerate_scope(active, operational, tuple(OPEN_WEEKLY_PRODUCTS), existing)
    body.update({
        "schema_version": 1, "readonly": True, "code_sha": commit,
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "queried_database_name": database,
        "queried_schema_version": existing_version,
        "active_products_file_sha256": sha256((ROOT / "data/universe/active_products.txt").read_bytes()).hexdigest(),
        "operational_products_file_sha256": sha256((ROOT / "data/universe/operational_products.txt").read_bytes()).hexdigest(),
        "data_ready": False, "activation_authorized": False,
    })
    try:
        output = write_new_manifest(args.output, body)
    except (OSError, ValueError):
        parser.error("output must be a new file under the system temporary directory")
    print(json.dumps({
        "status": "inventory_only", "readonly": True, "code_sha": commit,
        "output": str(output), "counts": body["counts"],
        "queried_database_name": database,
        "queried_schema_version": existing_version,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
