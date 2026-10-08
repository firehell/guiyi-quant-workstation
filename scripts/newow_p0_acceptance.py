"""Read-only P0 API and full physical-source collection; never visual acceptance.

One product/frequency/read-id per process. Native source and saved candidate
factories are both PostgreSQL read-only; candidate reference reads never fall
back to public saved assets. Failed reads retain evidence; use a new read-id only
after correcting the cause. This script never launches Runtime or writes DB.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
from itertools import groupby
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from scripts.newow_p0_candidate import CANONICAL_ROOT, CONFIG, SCHEMA, _freeze, safe_error_reason, safe_path, write_once


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item)).encode()).hexdigest()


def export_segments(read, identity, resolved):
    """Audit segmentation from raw MDS facts, without strategy/trade pairing."""
    from guiyi_quant.newow.product_adapters import label_calculation_segments
    from guiyi_quant.newow.product_contracts import lifecycle_input_sha256
    labeled = tuple(item for item in label_calculation_segments(identity, read.replay_bars, read.data_interruptions)
                    if item.bar.bar_end <= resolved.cutoff)
    groups = [(owner, tuple(values)) for owner, values in groupby(labeled, key=lambda item: (
        item.bar.physical_contract, item.bar.segment_id, item.calculation_segment_id))]
    latest = max((item.bar.bar_end for item in labeled if item.bar.observation_eligible), default=None)
    terminal = latest is not None and resolved.complete
    if latest is not None:
        terminal = terminal and not any(latest <= gap.effective_at <= resolved.cutoff for gap in read.data_interruptions)
        terminal = terminal and not any(latest <= boundary.effective_at <= resolved.cutoff for boundary in read.boundaries)
    segments = []
    for index, (owner, values) in enumerate(groups):
        segments.append({"owner": "|".join(str(value) for value in owner),
            "physical_contract": owner[0], "owner_segment_id": owner[1], "calculation_segment_id": owner[2],
            "terminal_eligible": bool(index == len(groups) - 1 and terminal and values[-1].bar.observation_eligible),
            "bars": [{"date": item.bar.bar_end.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
                "trading_day": item.bar.trading_day.isoformat(), "open": str(item.bar.open),
                "high": str(item.bar.high), "low": str(item.bar.low), "close": str(item.bar.close),
                "volume": item.bar.volume, "observation_eligible": item.bar.observation_eligible}
                for item in values]})
    return segments, lifecycle_input_sha256(labeled)


def verify_owner_binding(page, segments, input_hash, cutoff):
    owners = {segment["owner"]: segment for segment in segments}
    if page["input_sha256"] != input_hash or page["segment_count"] != len(segments):
        raise ValueError("P0_FULL_PREFIX_INPUT_HASH_MISMATCH")
    eligible = {owner: {bar["date"]: bar for bar in segment["bars"] if bar["observation_eligible"]}
                for owner, segment in owners.items()}
    for mode in ("ordinary", "ideal"):
        result = page[mode]
        if result is None:
            continue
        for stamp, day, owner in zip(result["dates"], result["trading_days"], result["segment_ids"]):
            if (owner not in eligible or stamp not in eligible[owner]
                    or eligible[owner][stamp]["trading_day"] != day
                    or datetime.fromisoformat(stamp) > cutoff):
                raise ValueError("P0_API_OWNER_INPUT_MISMATCH")
        for trade in result["trades"]:
            owner = trade["segment_id"]
            if (owner not in eligible or trade["buyDate"] not in eligible[owner]
                    or trade["sellDate"] not in eligible[owner]):
                raise ValueError("P0_API_TRADE_OWNER_INPUT_MISMATCH")
            if trade["forceClose"] and (mode == "ideal" or not owners[owner]["terminal_eligible"]
                    or trade["sellDate"] != owners[owner]["bars"][-1]["date"]):
                raise ValueError("P0_API_TERMINAL_OWNER_MISMATCH")


def verify_native_actions(points, segments, identity, cutoff):
    """Bind saved source action facts to the full eligible physical input."""
    from decimal import Decimal
    expected_identity = json.loads(json.dumps(asdict(identity)))
    owners = {segment["owner"]: {datetime.fromisoformat(bar["date"]): bar
        for bar in segment["bars"]} for segment in segments}
    seen = set()
    for point in points:
        value = point.get("value")
        if (point.get("kind") != "action" or not isinstance(value, dict)
                or value.get("identity") != expected_identity
                or point.get("formula_versions") != list(identity.formula_versions)):
            raise ValueError("P0_NATIVE_ACTION_IDENTITY_MISMATCH")
        owner = "|".join(str(value.get(key)) for key in
            ("physical_contract", "segment_id", "calculation_segment_id"))
        try:
            at = datetime.fromisoformat(value["bar_end"])
            bar = owners[owner][at]
            price = Decimal(value["reference_price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("P0_NATIVE_ACTION_OWNER_INPUT_MISMATCH") from exc
        eligibility = value.get("trade_eligibility")
        if (bar["observation_eligible"] != (eligibility != "WARMUP_ONLY")):
            raise ValueError("P0_NATIVE_ACTION_ELIGIBILITY_MISMATCH")
        if (at > cutoff or value.get("trading_day") != bar["trading_day"]
                or point.get("trading_day") != bar["trading_day"]
                or not price.is_finite() or price <= 0
                or value.get("kind") not in ("BUILD", "CLEAR")
                or value.get("trade_eligibility") not in
                ("ELIGIBLE", "NO_ELIGIBLE_ENTRY", "INITIAL_CLEAR_NO_ENTRY", "WARMUP_ONLY")):
            raise ValueError("P0_NATIVE_ACTION_FACT_INVALID")
        signal_id = value.get("signal_id")
        if not isinstance(signal_id, str) or not signal_id or signal_id in seen:
            raise ValueError("P0_NATIVE_ACTION_DUPLICATE_OR_MISSING")
        seen.add(signal_id)
    return points


def verify_payload(body, product, frequency, cutoff, strategy=None, *, include_fusion=True):
    from app.schemas.market_newow_product import NewowProductResponse
    typed = NewowProductResponse.model_validate(body)
    if (typed.meta.schema_version != "newow_product_detail_v4"
            or typed.meta.identity.product != product or typed.meta.identity.frequency != frequency
            or typed.meta.as_of != cutoff or typed.reference.delivery != "delivered"
            or typed.reference.value is None
            or (strategy is not None and typed.meta.identity.strategy != strategy)
            or (strategy is not None and typed.reference.value.page_performance.strategy != strategy)
            or (include_fusion and (typed.reference.value.fusion_comparison is None
                or typed.reference.value.fusion_comparison.page_performance.strategy != "fusion"))):
        raise ValueError("P0_API_IDENTITY_MISMATCH")
    return typed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--frequency", choices=("5m", "15m", "30m", "60m", "1d", "1w"), required=True)
    parser.add_argument("--read-id", default="r001")
    args = parser.parse_args()
    manifest, root = _freeze(args.manifest)
    if args.product not in manifest["products"] or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.read_id):
        raise ValueError("P0_ACCEPTANCE_SCOPE_INVALID")
    output = safe_path(args.output, root / "outputs")
    target = safe_path(output / "acceptance" / f"{args.product}-{args.frequency}-{args.read_id}", output)
    from scripts.newow_weekly_recovery import load_private_readonly_settings
    settings, config_identity = load_private_readonly_settings(CONFIG)
    bootstrap = json.loads((output / "bootstrap-completed.json").read_text())
    if (bootstrap.get("manifest_sha256") != sha256(args.manifest.read_bytes()).hexdigest()
            or bootstrap.get("config_identity") != config_identity or bootstrap.get("schema") != SCHEMA):
        raise ValueError("P0_BOOTSTRAP_CONFIG_MISMATCH")
    write_once(target / "read-start.json", {"state": "UNKNOWN", "readonly": True,
        "code_sha": manifest["code_sha"], "schema": SCHEMA, "product": args.product,
        "frequency": args.frequency, "read_id": args.read_id,
        "config_identity_sha256": digest(config_identity)})
    os.environ.update(settings)
    for key in ("GUIYI_INTRADAY_PREVIEW_PRODUCT", "GUIYI_HOURLY_PREVIEW_PRODUCT", "GUIYI_HOURLY_PREVIEW_PRODUCTS", "GUIYI_PREVIEW_DEFAULT_WEEKLY", "GUIYI_AG_PERIOD_PREVIEW", "GUIYI_AU_PERIOD_PREVIEW"):
        os.environ.pop(key, None)
    os.environ.update(GUIYI_CANONICAL_DATA_ROOT=CANONICAL_ROOT, GUIYI_CANDIDATE_PREVIEW="1",
        GUIYI_PREVIEW_AS_OF=manifest["as_of"], GUIYI_PREVIEW_CANDIDATE_ORIGIN="http://127.0.0.1:8012",
        GUIYI_INTRADAY_PREVIEW_PRODUCTS=args.product, REFERENCE_TRADING_READER_MODE="persisted")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from app.db.session import normalize_database_url
    from app.api import market_newow
    from app.preview import create_preview_app
    from fastapi.testclient import TestClient
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service, build_database_coverage_source
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_query import NewowProductQuery
    from app.market_data.newow.product_release import candidate_input_quality_policy, INTRADAY_BATCH_PREVIEW_SYMBOLS, INTRADAY_SINGLE_PREVIEW_SYMBOLS
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductFrequency
    from app.reference_trading.persisted_newow import PersistedNewowReference
    from app.reference_trading.query import HistoricalReferenceQuery
    from app.reference_trading.source_identity import verify_saved_compact_source
    if not set(manifest["products"]) <= (INTRADAY_BATCH_PREVIEW_SYMBOLS | INTRADAY_SINGLE_PREVIEW_SYMBOLS):
        raise ValueError("P0_PREVIEW_UNIVERSE_MISSING")
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]),
        connect_args={"options": "-c default_transaction_read_only=on -c search_path=public"})
    public_factory = sessionmaker(engine, expire_on_commit=False)
    candidate_factory = sessionmaker(engine.execution_options(schema_translate_map={None: SCHEMA}), expire_on_commit=False)
    original_factory, original_builder = market_newow.SessionLocal, market_newow._build_product_service
    market_newow.SessionLocal = candidate_factory
    def scoped_builder(*positional, **keywords):
        if keywords.get("historical_intraday"):
            raise ValueError("P0_PUBLIC_SAVED_READER_FORBIDDEN")
        service = original_builder(*positional, **keywords)
        original_query = service.query
        def query(request):
            if request.frequency.value in ("1d", "1w"):
                service._persisted_reference = None
            return original_query(request)
        service.query = query
        return service
    market_newow._build_product_service = scoped_builder
    try:
        cutoff = datetime.fromisoformat(manifest["as_of"])
        frequency = ProductFrequency(args.frequency)
        minute = args.frequency in manifest["frequencies"]
        policy = candidate_input_quality_policy(args.product, frequency, candidate_weekly=True)
        with Session(engine) as source, readonly_transaction(source, timeout_seconds=1800):
            reader = NewowProductReader(build_market_data_service(source), coverage=build_database_coverage_source(source),
                active_products=(args.product,), now=lambda: cutoff, input_quality_policy=policy)
            saved = PersistedNewowReference(candidate_factory)
            reference_query = HistoricalReferenceQuery(candidate_factory)
            source_start = date.fromisoformat(manifest["since"])
            through = date.fromisoformat(manifest["through"])
            asset_proofs = {}
            if minute:
                for strategy in ("trend", "oscillation", "dual_fusion"):
                    rows = reference_query.streams(strategy=f"newow_{strategy}", product=args.product, frequency=args.frequency)
                    if len(rows) != 1 or rows[0]["enabled"] is not False or rows[0]["activation_generation"] != 0:
                        raise ValueError("P0_ASSET_GENERATION_INVALID")
                    row = rows[0]
                    _, dependency = saved._manifest(row["stream_id"], row["active_revision_id"], row["latest_seq"])
                    if (dependency["query_since"] != manifest["since"] or dependency["query_through"] != manifest["through"]
                            or datetime.fromisoformat(dependency["query_as_of"]) != cutoff):
                        raise ValueError("P0_ASSET_WINDOW_CHANGED")
                    asset_proofs[strategy] = {"stream": row, "dependency_manifest": dependency}
            else:
                source_start = reader.historical_storage_start(args.product)
            # The source proof covers the frozen requested window even when W1
            # resolves an earlier completed period. No provider calls occur.
            def verify_asset(dependency, evidence):
                expected_reader = "newow_fusion_saved_sources_v1" if dependency.get("reader") == "newow_fusion_saved_sources_v1" else "newow_product_reader_intraday_v3"
                if dependency.get("reader") != expected_reader:
                    raise ValueError("P0_ASSET_SOURCE_READER_INVALID")
                verify_saved_compact_source({**dependency, "reader": "newow_product_reader_intraday_v3"}, evidence)
            def evidence(source_reader=reader):
                if minute:
                    return source_reader.historical_source_evidence(product=args.product, frequency=args.frequency,
                        since=source_start, through=through, as_of=cutoff)
                from app.market_data.domain import BarFrequency
                owners = source_reader.dependency_owners(args.product, source_start, through)
                physical = [source_reader._market_data.contract_source_evidence(symbol=args.product,
                    contract=owner.contract, frequency=BarFrequency(args.frequency), before=cutoff) for owner in owners]
                return {"schema": "newow_p0_legacy_source_evidence_v1", "product": args.product,
                    "frequency": args.frequency, "since": source_start.isoformat(), "through": through.isoformat(),
                    "as_of": cutoff.isoformat(), "physical": physical,
                    "metadata": source_reader.historical_metadata_evidence(product=args.product, since=source_start, through=through)}
            before = evidence()
            if minute:
                for proof in asset_proofs.values():
                    verify_asset(proof["dependency_manifest"], before)
            app = create_preview_app(enabled=True, as_of=manifest["as_of"], session_factory=public_factory)
            responses = {}
            with TestClient(app) as client:
                preview = client.get("/api/preview/identity").json()
                if preview.get("code_sha") != manifest["code_sha"] or datetime.fromisoformat(preview["as_of"]) != cutoff:
                    raise ValueError("P0_PREVIEW_CODE_MISMATCH")
                for strategy in (("trend", "oscillation") if minute else ("trend", "oscillation", "main_rise")):
                    include_fusion = strategy != "main_rise"
                    response = client.get("/api/v1/market/newow/strategy-detail", params={"product": args.product,
                        "frequency": args.frequency, "strategy": strategy, "section": "reference", "include_fusion": "true" if include_fusion else "false",
                        "performance_since": manifest["since"], "performance_through": manifest["through"],
                        "as_of": manifest["as_of"], "history_limit": 200})
                    if response.status_code != 200:
                        write_once(target / f"{strategy}-error.json", {"http": response.status_code, "code": safe_error_reason(ValueError((response.json().get("detail") or {}).get("code", "P0_API_READ_FAILED")))})
                        raise ValueError("P0_API_READ_FAILED")
                    body = response.json()
                    verify_payload(body, args.product, args.frequency, cutoff, strategy, include_fusion=include_fusion)
                    if minute and body["reference"]["value"].get("storage_mode") != "persisted":
                        raise ValueError("P0_CANDIDATE_STORAGE_MODE_INVALID")
                    if not minute and "storage_mode" in body["reference"]["value"]:
                        raise ValueError("P0_LEGACY_SAVED_READER_FORBIDDEN")
                    write_once(target / f"{strategy}-api.json", body)
                    responses[strategy] = body
            trend_value = responses["trend"]["reference"]["value"]
            resolved = reader.resolve_performance_window(args.product, frequency, date.fromisoformat(manifest["since"]), through, cutoff)
            if (resolved.cutoff != datetime.fromisoformat(trend_value["reference_cutoff"])
                    or resolved.actual_through.isoformat() != trend_value["actual_available_through"]):
                raise ValueError("P0_API_SOURCE_WINDOW_MISMATCH")
            full = reader.load(NewowProductQuery(args.product, "trend", frequency, source_start,
                resolved.actual_through, source_start, resolved.actual_through, resolved.cutoff), resolved.cutoff)
            identity = build_product_identity(args.product, "trend", frequency, input_quality_policy=full.input_quality_policy)
            segments, input_hash = export_segments(full, identity, resolved)
            pages = {strategy: body["reference"]["value"]["page_performance"] for strategy, body in responses.items()}
            pages["fusion"] = trend_value["fusion_comparison"]["page_performance"]
            for page in pages.values():
                verify_owner_binding(page, segments, input_hash, resolved.cutoff)
            if responses["oscillation"]["reference"]["value"]["fusion_comparison"]["page_performance"] != pages["fusion"]:
                raise ValueError("P0_FUSION_RESPONSE_MISMATCH")
            native_actions = {}
            native_action_generations = {}
            if minute:
                from contextlib import closing
                for strategy in ("trend", "oscillation"):
                    proof = asset_proofs[strategy]
                    stream = proof["stream"]
                    page = reference_query.trades(stream["stream_id"], since=source_start,
                        through=through, cutoff=cutoff, limit=1)
                    if (page["revision_id"], page["seq"]) != (stream["active_revision_id"], stream["latest_seq"]):
                        raise ValueError("P0_NATIVE_ACTION_GENERATION_MISMATCH")
                    with closing(reference_query.historical_actions(stream["stream_id"],
                            snapshot_token=page["snapshot"], since=source_start, through=through,
                            cutoff=cutoff, input_count=proof["dependency_manifest"]["input_count"])) as iterator:
                        points = list(iterator)
                    action_identity = build_product_identity(args.product, strategy, frequency,
                        input_quality_policy=full.input_quality_policy)
                    verify_native_actions(points, segments, action_identity, resolved.cutoff)
                    native_actions[strategy] = points
                    native_action_generations[strategy] = {"stream_id": stream["stream_id"],
                        "revision_id": page["revision_id"], "seq": page["seq"],
                        "snapshot": page["snapshot"], "formula_versions": list(action_identity.formula_versions)}
            # Fresh composition/session for the post-read proof; a resolver or
            # reader memo from the first load cannot hide a changed generation.
            with Session(engine) as independent, readonly_transaction(independent, timeout_seconds=1800):
                fresh_reader = NewowProductReader(build_market_data_service(independent),
                    coverage=build_database_coverage_source(independent), active_products=(args.product,),
                    now=lambda: cutoff, input_quality_policy=policy)
                after = evidence(fresh_reader)
            if before != after:
                raise ValueError("P0_SOURCE_CHANGED_DURING_READ")
            if minute:
                for strategy, proof in asset_proofs.items():
                    verify_asset(proof["dependency_manifest"], after)
                    rows = reference_query.streams(strategy=f"newow_{strategy}", product=args.product, frequency=args.frequency)
                    if rows != [proof["stream"]]:
                        raise ValueError("P0_ASSET_GENERATION_CHANGED_DURING_READ")
                if any(page["source_evidence_sha256"] != digest(before) for page in pages.values()):
                    raise ValueError("P0_API_SOURCE_HASH_MISMATCH")
            write_once(target / "source-proof.json", {"before": before, "after": after, "assets": asset_proofs})
            write_once(target / "oracle-input.json", {"code_sha": manifest["code_sha"], "product": args.product,
                "frequency": args.frequency, "cutoff": resolved.cutoff.isoformat(),
                "performance_since": manifest["since"], "performance_through": manifest["through"],
                "source_evidence_sha256": digest(before), "input_sha256": input_hash,
                "segments": segments, "responses": pages, "native_actions": native_actions,
                "native_action_generations": native_action_generations})
            _freeze(args.manifest)
            write_once(target / "read-completed.json", {"status": "READONLY_API_AND_INPUT_COLLECTED",
                "readonly": True, "db_writes": 0, "provider_calls": 0, "visual_acceptance": "PENDING",
                "numeric_oracle_acceptance": "PENDING", "code_sha": manifest["code_sha"],
                "hashes": {name: sha256(safe_path(target / name, output).read_bytes()).hexdigest()
                    for name in ("read-start.json", "source-proof.json", "oracle-input.json",
                        *(f"{strategy}-api.json" for strategy in responses))}})
        return 0
    finally:
        market_newow.SessionLocal, market_newow._build_product_service = original_factory, original_builder
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        safe = safe_error_reason(exc)
        print(json.dumps({"status": "BLOCKED", "reason": safe}), flush=True)
        raise SystemExit(1)
