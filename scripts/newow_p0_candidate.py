"""Frozen, serial Newow P0 private candidate builds; no source writes or retries.

Run with PYTHONPATH=services/quant-api:packages/quant-core:. from the frozen
checkout. The manifest binds code_sha, worktree, products, universe_sha256 and
canonical_root. Commands: bootstrap, plan, build, readback; stage commands take
one product/frequency/strategy. A new schema is created exactly once. No command
downloads data, enables streams, resumes attempts or changes Runtime.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from time import monotonic

SCHEMA = "newow_p0_v3379_20261008"
CUTOFF = "2026-09-24T07:00:00.000001+00:00"
FREQUENCIES = ("5m", "15m", "30m", "60m")
STRATEGIES = ("trend", "oscillation", "dual_fusion")
CANONICAL_ROOT = "/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical"
CONFIG = Path("/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env")


def safe_error_reason(error: Exception) -> str:
    reason = str(error)
    return reason if re.fullmatch(r"(?:P0_|SOURCE_|REFERENCE_|NEWOW_|MARKET_)[A-Z0-9_]+", reason) else "P0_UNCLASSIFIED_STOP_READBACK_REQUIRED"


def safe_path(path: Path, root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("P0_ARTIFACT_SYMLINK")
    root = root.resolve()
    absolute = path.absolute()
    if not absolute.is_relative_to(root) or not absolute.resolve(strict=False).is_relative_to(root):
        raise ValueError("P0_ARTIFACT_PATH_ESCAPE")
    current = root
    for component in absolute.relative_to(root).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("P0_ARTIFACT_SYMLINK")
    return absolute


def write_once(path: Path, value: object) -> None:
    # Descriptor-anchor every directory: no component can be redirected between
    # validation and creation. Existing final files are never followed/overwritten.
    path = path.absolute()
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parent.parts[1:]:
            try:
                next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=directory)
                os.fsync(directory)
                next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)


def validate_manifest(manifest: dict, *, head: str, root: Path, universe: bytes) -> None:
    if manifest.get("schema") != SCHEMA or manifest.get("as_of") != CUTOFF:
        raise ValueError("P0_SCHEMA_OR_CUTOFF_MISMATCH")
    if manifest.get("code_sha") != head or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("P0_CODE_MISMATCH")
    if Path(manifest["worktree"]).resolve() != root.resolve():
        raise ValueError("P0_WORKTREE_MISMATCH")
    if manifest.get("canonical_root") != CANONICAL_ROOT:
        raise ValueError("P0_CANONICAL_ROOT_MISMATCH")
    if manifest.get("universe_sha256") != sha256(universe).hexdigest():
        raise ValueError("P0_UNIVERSE_CHANGED")
    products = tuple(line.strip() for line in universe.decode().splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))
    if len(products) != 60 or len(set(products)) != 60 or list(products) != manifest.get("products"):
        raise ValueError("P0_EXACT_60_PRODUCTS_REQUIRED")
    if manifest.get("since") != "2023-01-01" or manifest.get("through") != "2026-09-24":
        raise ValueError("P0_WINDOW_MISMATCH")
    if manifest.get("frequencies") != list(FREQUENCIES) or manifest.get("strategies") != list(STRATEGIES):
        raise ValueError("P0_MATRIX_MISMATCH")


def _freeze(manifest_path: Path) -> tuple[dict, Path]:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(manifest_path.read_text())
    head = subprocess.check_output(["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    validate_manifest(manifest, head=head, root=root, universe=(root / "data/universe/operational_products.txt").read_bytes())
    dirty = subprocess.check_output(["git", "-c", "core.fsmonitor=false", "diff", "--name-only", "HEAD", "--", "services", "packages", "scripts", "tools", "apps"], cwd=root, text=True).strip()
    if dirty:
        raise ValueError("P0_FROZEN_TRACKED_DIRTY")
    untracked = subprocess.check_output(["git", "-c", "core.fsmonitor=false", "ls-files", "--others", "--exclude-standard", "--", "services", "packages", "scripts", "tools"], cwd=root, text=True).strip()
    if untracked:
        raise ValueError("P0_FROZEN_UNTRACKED_EXECUTION_SOURCE")
    # Do not allow importing an installed core or API from another checkout.
    import app.reference_trading.query as query
    import guiyi_quant.newow.product_adapters as adapters
    for module in (query, adapters):
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise ValueError("P0_FOREIGN_IMPORT")
    return manifest, root


def stage_key(product: str, frequency: str, strategy: str, products: list[str]) -> str:
    if product not in products or frequency not in FREQUENCIES or strategy not in STRATEGIES:
        raise ValueError("P0_STAGE_SCOPE_INVALID")
    return f"{product}-{frequency}-{strategy}"


def stage_order(products: list[str]) -> tuple[tuple[str, str, str], ...]:
    return tuple((product, frequency, strategy) for product in products
                 for strategy in STRATEGIES for frequency in FREQUENCIES)


@contextmanager
def exclusive_campaign(output: Path):
    import fcntl
    output.mkdir(parents=True, exist_ok=True)
    lock_path = safe_path(output / "campaign.lock", output)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("P0_CAMPAIGN_BUSY") from exc
        yield


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "plan", "build", "readback"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product")
    parser.add_argument("--frequency", choices=FREQUENCIES)
    parser.add_argument("--strategy", choices=STRATEGIES)
    args = parser.parse_args()
    manifest, root = _freeze(args.manifest)
    output = safe_path(args.output, root / "outputs")
    if not output.is_relative_to(root / "outputs"):
        raise ValueError("P0_OUTPUT_OUTSIDE_CANDIDATE")
    # Existing loader reads secrets internally; none are emitted or serialized.
    from scripts.newow_weekly_recovery import load_private_readonly_settings
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session, sessionmaker
    from app.db.session import normalize_database_url
    settings, config_identity = load_private_readonly_settings(CONFIG)
    os.environ.update(settings)
    os.environ["GUIYI_CANONICAL_DATA_ROOT"] = CANONICAL_ROOT
    url = normalize_database_url(settings["DATABASE_URL"])
    readonly_engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on -c search_path=public"})
    # All native reference ORM metadata is translated into the candidate schema;
    # public MDS queries use only the separate readonly engine.
    candidate_engine = create_engine(url, connect_args={"options": f"-c search_path={SCHEMA}"})
    scoped = candidate_engine.execution_options(schema_translate_map={None: SCHEMA})
    factory = sessionmaker(scoped, expire_on_commit=False)
    readonly_factory = sessionmaker(readonly_engine.execution_options(schema_translate_map={None: SCHEMA}), expire_on_commit=False)
    from app.reference_trading.query import HistoricalReferenceQuery
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.models import REFERENCE_TABLES
    from app.db.base import Base
    with exclusive_campaign(output):
        if args.command == "bootstrap":
            # No IF NOT EXISTS: preexisting/foreign schemas must never be adopted.
            attempt = output / "bootstrap-attempt.json"
            write_once(attempt, {"state": "UNKNOWN", "retry_allowed": False, "schema": SCHEMA, "code_sha": manifest["code_sha"]})
            with candidate_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
                Base.metadata.create_all(connection.execution_options(schema_translate_map={None: SCHEMA}), tables=[Base.metadata.tables[name] for name in sorted(REFERENCE_TABLES)], checkfirst=False)
            write_once(output / "bootstrap-completed.json", {"schema": SCHEMA, "reference_tables": sorted(REFERENCE_TABLES), "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(), "config_identity": config_identity})
            return 0
        completed = json.loads((output / "bootstrap-completed.json").read_text())
        if completed.get("config_identity") != config_identity:
            raise ValueError("P0_DATABASE_CONFIG_CHANGED")
        if completed["manifest_sha256"] != sha256(args.manifest.read_bytes()).hexdigest():
            raise ValueError("P0_BOOTSTRAP_MANIFEST_CHANGED")
        key = stage_key(args.product, args.frequency, args.strategy, manifest["products"])
        stage = safe_path(output / "assets" / key, output)
        stage.mkdir(parents=True, exist_ok=True)
        cutoff = datetime.fromisoformat(CUTOFF)
        from guiyi_quant.newow.product_contracts import ProductStrategy, ProductFrequency
        from guiyi_quant.newow.product_adapters import build_product_identity
        from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
        from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
        from guiyi_quant.reference_trading import StreamIdentity
        if args.strategy == "dual_fusion":
            identity = build_fusion_stream_identity(args.product, args.frequency)
        else:
            p = build_product_identity(args.product, ProductStrategy(args.strategy), ProductFrequency(args.frequency))
            identity = StreamIdentity(strategy_code=f"newow_{args.strategy}", formula_versions=p.formula_versions, profile_id=p.profile_id, reference_model_version=REFERENCE_MODEL_VERSION, futures_adaptation_version=futures_adaptation_version(args.frequency), product=args.product, frequency=args.frequency, series_kind="actual_dominant", recording_mode="historical_replay", observation_policy_version=None)
        query = HistoricalReferenceQuery(readonly_factory)
        if args.command == "readback":
            streams = query.streams(strategy=identity.strategy_code, product=args.product, frequency=args.frequency)
            if len(streams) != 1 or streams[0]["stream_id"] != identity.stream_id or streams[0]["enabled"] is not False or streams[0]["activation_generation"] != 0:
                raise ValueError("P0_READBACK_STREAM_INVALID")
            summary = query.summary(identity.stream_id, since=date.fromisoformat(manifest["since"]), through=date.fromisoformat(manifest["through"]), cutoff=cutoff)
            if summary["status"] != "READY" or summary["revision_id"] != streams[0]["active_revision_id"] or summary["seq"] != streams[0]["latest_seq"]:
                raise ValueError("P0_READBACK_NOT_READY")
            plan = json.loads((stage / "plan.json").read_text())
            report = json.loads((stage / "native-report.json").read_text())
            if report["status"] != "completed" or summary["coverage"]["computed_through"] != plan["streams"][0]["target_completed_through"]:
                raise ValueError("P0_READBACK_COVERAGE_MISMATCH")
            write_once(stage / "readback.json", {"stream": streams[0], "summary": summary, "native_plan_sha256": sha256((stage / "plan.json").read_bytes()).hexdigest(), "native_report_sha256": sha256((stage / "native-report.json").read_bytes()).hexdigest()})
            return 0
        if (stage / "attempt.json").exists():
            raise ValueError("P0_PRIOR_ATTEMPT_NO_RETRY")
        if query.streams(strategy=identity.strategy_code, product=args.product, frequency=args.frequency):
            raise ValueError("P0_EXISTING_STREAM_NO_OVERWRITE")
        from app.market_data.composition import build_market_data_service, build_database_coverage_source, canonical_root
        from app.market_data.catalog import MarketCatalog
        from app.market_data.newow.product_reader import NewowProductReader
        from app.reference_trading.inputs import MarketDataHistoricalInputReader
        from app.reference_trading.newow_fusion import SavedFusionSources
        from app.reference_trading.planning import HistoricalReferencePlanner, HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget, plan_to_dict
        from app.reference_trading.service import HistoricalReferenceService
        with Session(readonly_engine) as source:
            catalog = MarketCatalog(source, canonical_root())
            @contextmanager
            def guard():
                lease = catalog.acquire_maintenance_lock()
                if lease is None:
                    raise ValueError("SOURCE_BUSY")
                try:
                    yield
                finally:
                    lease.release()
            native = NewowProductReader(build_market_data_service(source), coverage=build_database_coverage_source(source), active_products=(args.product,), now=lambda: cutoff)
            reader = MarketDataHistoricalInputReader(newow_reader=native, subing_service=None, read_guard=guard, pin_verified_inputs=True, compact_intraday_inputs=True, fusion_sources=SavedFusionSources(readonly_factory))
            repository = ReferenceRepository(factory)
            request = HistoricalReferenceRequest("build", (HistoricalStreamRequest(identity, date.fromisoformat(manifest["since"]), date.fromisoformat(manifest["through"]), cutoff),), WorkBudget(1, 4_000_000, 900, 16_000_000_000), batch_size=256)
            started = monotonic()
            plan = HistoricalReferencePlanner(reader, repository=repository).plan(request)
            serialized = plan_to_dict(plan)
            # The complete native plan includes physical lineage, input hashes,
            # verified prefix and source_evidence_sha256. Apply replans it exactly.
            if args.command == "plan":
                write_once(stage / "plan.json", serialized)
            else:
                if json.loads((stage / "plan.json").read_text()) != serialized:
                    raise ValueError("P0_FROZEN_PLAN_CHANGED")
                write_once(stage / "attempt.json", {"state": "UNKNOWN", "retry_allowed": False, "plan_hash": plan.plan_hash, "code_sha": manifest["code_sha"]})
                report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)
                write_once(stage / "native-report.json", asdict(report))
                if report.status != "completed":
                    raise ValueError("P0_NATIVE_BUILD_INCOMPLETE")
            print(json.dumps({"stage": args.command, "key": key, "plan_hash": plan.plan_hash, "input_count": plan.streams[0].input_count, "seconds": round(monotonic() - started, 3)}), flush=True)
    readonly_engine.dispose()
    candidate_engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        safe = safe_error_reason(exc)
        print(json.dumps({"status": "BLOCKED", "reason": safe}), flush=True)
        raise SystemExit(1)
