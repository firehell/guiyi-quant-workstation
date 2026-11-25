"""Optional isolated consumer of the existing completed Canonical maintenance receipt."""

from argparse import ArgumentParser
from contextlib import contextmanager, nullcontext
import fcntl
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
from time import perf_counter, sleep

from app.market_data.after_market_history import _bytes as read_owned_file, publish_history

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.operational_universe import load_active_products
from app.market_data.product_retirement import load_retired_products
from app.market_data.newow.v2_scope import Scope, validate_scope
from app.services.newow_backtest_job import (
    BacktestJobError, _ENGINE, _LIMIT, _code_fingerprint, _diagnostic, _json, _launch, _read, _seal,
    freeze_research,
)
from app.services.newow_backtest_results import ResultStore, ResultStoreError, SeriesKey
from guiyi_quant.newow.decision_adapter import DECISION_FREQUENCIES, V2Strategy
from guiyi_quant.newow.product_contracts import ProductFrequency


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchInput:
    product: str
    since: date
    facts_path: Path
    facts_sha256: str
    rule2_path: Path | None
    rule2_sha256: str | None
    trial: bool


def research_key(product: str, strategy: str, frequency: str, *, trial: bool = False) -> SeriesKey:
    variant = "_trial" if trial else ""
    return SeriesKey(product, strategy, frequency, f"{strategy}_{frequency}_rqalpha{variant}_v1")


def affected_products(status: dict, trading_day: date, configured: set[str]) -> tuple[str, ...]:
    """An eligible no-op publication can still change a configured combination's dependencies."""
    run = status.get("last_run") or {}
    if status.get("current_run") or (run.get("status"), run.get("trading_day"), status.get("last_successful_trading_day")) != (
        "passed", trading_day.isoformat(), trading_day.isoformat(),
    ) or not isinstance(run.get("historical_publications"), list):
        return ()
    return tuple(sorted(configured.intersection(run["products"])))


def _source_is_current(catalog: MarketCatalog, publication: list[dict], product: str) -> bool:
    relevant = [item for item in publication if item["dataset"][1] == product]
    if not relevant:
        return True
    current = {(part.dataset.kind.value, part.dataset.symbol, part.dataset.series_or_contract,
                part.dataset.frequency.value, part.year, part.month): part.file_path.name
               for part in catalog.product_partitions(product)}
    # A single receipt can contain successive publications for the same month.
    latest = {(*item["dataset"], item["year"], item["month"]): item["file_name"] for item in relevant}
    return all(current.get(identity) == name for identity, name in latest.items())


def _digest(text: object) -> str:
    if not isinstance(text, str) or re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise BacktestJobError("BACKTEST_CONFIG_INVALID")
    return text


def _read_config(path: Path) -> tuple[ResearchInput, ...]:
    raw = json.loads(_read(path, 128 * 1024))
    if not isinstance(raw, list) or not 1 <= len(raw) <= 140:
        raise BacktestJobError("BACKTEST_CONFIG_INVALID")
    active = set(load_active_products())
    result = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict) or set(row) - {
            "product", "since", "facts", "facts_sha256", "rule2", "rule2_sha256", "trial",
        }:
            raise BacktestJobError("BACKTEST_CONFIG_INVALID")
        product = row["product"]
        trial = row.get("trial", False)
        witness = row.get("rule2")
        if (not isinstance(product, str) or not re.fullmatch(r"[a-z]{1,12}", product)
                or type(trial) is not bool or (not trial and product not in active) or (product, trial) in seen
                or bool(witness) != bool(row.get("rule2_sha256"))):
            raise BacktestJobError("BACKTEST_CONFIG_INVALID")
        facts_path = Path(row["facts"])
        witness_path = Path(witness) if witness else None
        if not facts_path.is_absolute() or witness_path is not None and not witness_path.is_absolute():
            raise BacktestJobError("BACKTEST_CONFIG_INVALID")
        seen.add((product, trial))
        result.append(ResearchInput(
            product, date.fromisoformat(row["since"]), facts_path, _digest(row["facts_sha256"]),
            witness_path, _digest(row["rule2_sha256"]) if witness else None, trial,
        ))
    scope = tuple(sorted({item.product for item in result}))
    validate_scope(Scope("isolated-research", scope, ()), supported=scope,
                   retired=load_retired_products(), isolated=True)
    return tuple(result)


def _witnesses(source: ResearchInput) -> dict[date, tuple[str, str]]:
    if source.rule2_path is None:
        return {}
    raw = _read(source.rule2_path)
    if sha256(raw).hexdigest() != source.rule2_sha256:
        raise BacktestJobError("P3_RULE2_WITNESS_DIGEST_MISMATCH")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise BacktestJobError("P3_RULE2_WITNESS_SCOPE_INVALID")
    witnesses = {}
    for row in rows:
        day = date.fromisoformat(row["trading_day"])
        contract = row["physical_contract"]
        if day in witnesses or row != {
            "source": "rqdata.futures.get_dominant", "product": source.product,
            "trading_day": day.isoformat(), "rule": 2, "rank": 1, "physical_contract": contract,
        } or re.fullmatch(r"[A-Z]{1,12}[0-9]{3,4}", contract) is None:
            raise BacktestJobError("P3_RULE2_WITNESS_SCOPE_INVALID")
        witnesses[day] = (contract, source.rule2_sha256)
    return witnesses


def _run_one(
    store, key, day, freeze, *, output: Path, engine_python: Path, code_identity: str,
    retry_failed: bool = False, source_publication: tuple[datetime, str] | None = None,
    source_is_current=None, publication_fence=nullcontext,
) -> dict | None:
    started = perf_counter()
    with store.job_slot(key, wait_seconds=200 if source_publication is not None else 0) as connection:
        latest = store.latest(key)
        cutoffs = [row["as_of_trading_day"] for row in (latest["result"], latest["last_attempt"]) if row]
        if any(cutoff > day.isoformat() for cutoff in cutoffs):
            return None
        if source_is_current is not None and not source_is_current():
            return None
        if source_publication is not None and not store.observe_source_publication(key, *source_publication, connection):
            return None
        try:
            frozen_input = freeze()
            if frozen_input is None:
                raise BacktestJobError("BACKTEST_CANONICAL_PUBLICATION_CHANGED")
            packet, manifest = frozen_input
            data = _json(packet)
            if len(data) > _LIMIT:
                raise BacktestJobError("P3_ARTIFACT_TOO_LARGE")
            fingerprint = sha256(data).hexdigest()
            manifest.update(input_sha256=fingerprint, code_sha256=code_identity)
            if key.frequency == "1w" and packet.get("result_kind") == "reference_only":
                manifest["bounded_week_sha256"] = _weekly_input_identity(packet, manifest)
        except Exception as exc:
            code = _diagnostic(exc)
            if code == "BACKTEST_CANONICAL_PUBLICATION_CHANGED":
                raise
            admission = store.admit(key, {
                "as_of_trading_day": day, "preflight_error": code, "code_sha256": code_identity,
            }, eligible=False, job_connection=connection, retry_failed=retry_failed)
            if admission.should_run:
                store.fail(admission, code)
            return {"run_id": admission.run_id, "status": "FAILED", "code": code}

        qualified = manifest["rank1"]["code"] == "RANK1_AS_KNOWN_VERIFIED"
        with publication_fence():
            if source_is_current is not None and not source_is_current():
                raise BacktestJobError("BACKTEST_CANONICAL_PUBLICATION_CHANGED")
            published = latest["result"]
            if (published and (bounded_week := manifest.get("bounded_week_sha256"))
                    and published["manifest"].get("bounded_week_sha256") == bounded_week):
                return {"run_id": published["run_id"], "status": "SUCCEEDED", "reused": True}
            admission = store.admit(key, manifest, eligible=qualified and not key.is_trial,
                                    job_connection=connection, retry_failed=retry_failed,
                                    republish_existing=source_publication is not None)
        if not admission.should_run:
            return {"run_id": admission.run_id, "status": admission.status, "reused": True}
        frozen_at = perf_counter()
        try:
            if not key.is_trial and not qualified:
                raise BacktestJobError("RANK1_AS_KNOWN_UNPROVEN")
            frozen = _seal(output, data, fingerprint)
            result = _launch(engine_python, frozen, fingerprint, admission.run_id)
            summary = result.get("summary", {})
            if manifest.get("result_kind") == "reference_only":
                if (summary.get("result_kind"), summary.get("cutoff_trading_day")) != (
                    "reference_only", day.isoformat(),
                ):
                    raise BacktestJobError("P3_COMPLETED_INPUT_MISMATCH")
            elif summary.get("money_policy") != manifest["money_policy"]:
                raise BacktestJobError("P3_MONEY_POLICY_MISMATCH")
        except Exception as exc:
            code = _diagnostic(exc)
            store.fail(admission, code)
            return {"run_id": admission.run_id, "status": "FAILED", "code": code}
        computed_at = perf_counter()
        try:
            with publication_fence():
                if source_is_current is not None and not source_is_current():
                    # Leave the admission recoverable if the source is unsettled.
                    return {"run_id": admission.run_id, "status": "DEFERRED",
                            "code": "BACKTEST_SOURCE_PUBLICATION_SUPERSEDED"}
                store.publish(admission, result["summary"], result["trades"], result["equity"])
        except ResultStoreError as exc:
            if exc.code not in {
                "BACKTEST_RESULT_WRITE_FAILED", "BACKTEST_AMOUNT_INVALID", "BACKTEST_SEQUENCE_INVALID",
                "BACKTEST_TRADE_INVALID", "BACKTEST_EQUITY_INVALID", "BACKTEST_VALUE_INVALID", "BACKTEST_FORMAL_INELIGIBLE",
            }:
                raise
            store.fail(admission, exc.code)
            return {"run_id": admission.run_id, "status": "FAILED", "code": exc.code}
        return {"run_id": admission.run_id, "status": "SUCCEEDED", "input_sha256": fingerprint,
                "freeze_seconds": round(frozen_at - started, 3),
                "engine_seconds": round(computed_at - frozen_at, 3),
                "publish_seconds": round(perf_counter() - computed_at, 3)}


def _isolated_market_url(value: str):
    url = make_url(normalize_database_url(value))
    if (url.drivername != "postgresql+psycopg" or url.query or url.host != "127.0.0.1"
            or not url.port or url.port == 5432 or url.database != "guiyi_newow_market_test"):
        raise BacktestJobError("BACKTEST_ISOLATED_CATALOG_REQUIRED")
    return url


def _weekly_input_identity(packet: dict, manifest: dict) -> str:
    # Monthly file identity also changes for new rows after the weekly cutoff.
    # Compare the bounded values and eligibility that actually drive the replay.
    values = dict(packet)
    values.pop("market_revision")
    values["completed"] = [
        {name: value for name, value in row.items() if name not in {"source_ref", "fingerprint", "owner_ref"}}
        for row in packet["completed"]
    ]
    return sha256(_json({"packet": values, "rank1": manifest["rank1"],
                         "formula_versions": manifest["formula_versions"],
                         "code_sha256": manifest["code_sha256"]})).hexdigest()


def _weekly_cutoff(session, canonical, product, day, published_at, publication):
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore

    mds = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
    monday = day - timedelta(days=day.weekday())
    week = mds.completed_calendar_week(symbol=product, week_monday=monday, as_of=published_at)
    if week is None:
        prior = mds.previous_trading_day(product, monday)
        changed = [item for item in publication if item["dataset"][1] == product]
        if not changed or any(item["dataset"][3] in {"1m", "1d", "1w"}
                              and (item["year"], item["month"]) <= (prior.year, prior.month) for item in changed):
            week = mds.completed_calendar_week(symbol=product, week_monday=prior - timedelta(days=prior.weekday()),
                                               as_of=published_at)
    return week[0] if week is not None and week[0] <= day else None


def consume_status(
    raw_status: dict, day: date, config_path: Path, *,
    retry_series: tuple[str, str, str] | None = None,
    retry_trial: bool = False,
    latest_days: dict[str, date] | None = None,
    publication_is_stable=lambda: True,
    publication_fence=nullcontext,
) -> list[dict]:
    from app.market_data.after_market import public_after_market_status

    status = public_after_market_status(raw_status)
    config = _read_config(config_path)
    products = affected_products(status, day, {item.product for item in config})
    if not products:
        return []
    publication = status["last_run"]["historical_publications"]
    url = _isolated_market_url(os.getenv("GUIYI_NEWOW_EOD_MARKET_DSN", ""))
    canonical = Path(os.environ["GUIYI_NEWOW_EOD_CANONICAL_ROOT"]).resolve(strict=True)
    output = Path(os.environ["GUIYI_NEWOW_EOD_INPUT_DIR"]).resolve(strict=True)
    if not canonical.is_dir() or not output.is_dir() or output.is_relative_to(canonical) or canonical.is_relative_to(output):
        raise BacktestJobError("P3_INPUT_DIRECTORY_UNSAFE")
    engine_python = Path(os.getenv("GUIYI_NEWOW_EOD_ENGINE", str(_ENGINE / ".venv/bin/python")))
    published_at = datetime.fromisoformat(status["last_run"]["finished_at"])
    if published_at > datetime.now(UTC):
        raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_INVALID")
    receipt = (published_at, sha256(_json(status["last_run"])).hexdigest())
    identity = _code_fingerprint()
    market_engine = create_engine(url, hide_parameters=True,
                                  connect_args={"connect_timeout": 5, "hostaddr": "127.0.0.1"})
    rows = []
    try:
        store = ResultStore(os.getenv("GUIYI_NEWOW_BACKTEST_WRITE_DSN", ""))
        try:
            for source in config:
                if source.product not in products:
                    continue
                through = (latest_days or {}).get(source.product, day)
                if source.since > through:
                    continue
                for frequency in sorted(DECISION_FREQUENCIES):
                    cutoff = through
                    week_error = None
                    if frequency.value == "1w":
                        try:
                            with Session(market_engine) as session, readonly_transaction(session):
                                cutoff = _weekly_cutoff(session, canonical, source.product, through, published_at, publication)
                        except Exception as exc:
                            week_error = exc
                        if cutoff is None or cutoff < source.since:
                            continue
                    for strategy in V2Strategy:
                        key = research_key(source.product, strategy.value, frequency.value, trial=source.trial)

                        if retry_series is not None and (
                            (key.product, key.strategy, key.frequency) != retry_series or key.is_trial != retry_trial
                        ):
                            continue

                        def verify_source():
                            if not publication_is_stable():
                                raise BacktestJobError("BACKTEST_CANONICAL_PUBLICATION_CHANGED")
                            with Session(market_engine) as session, readonly_transaction(session, timeout_seconds=30):
                                return _source_is_current(MarketCatalog(session, canonical), publication, source.product)

                        def freeze():
                            if week_error is not None:
                                raise week_error
                            with Session(market_engine) as session, readonly_transaction(session, timeout_seconds=60):
                                if (not publication_is_stable()
                                        or not _source_is_current(MarketCatalog(session, canonical), publication, source.product)):
                                    return None
                                from app.market_data.market_data_service import MarketDataService
                                from app.market_data.storage import CanonicalMonthlyStore

                                mds = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
                                owners = mds.actual_dominant_segments(source.product, source.since, cutoff)
                                if not owners:
                                    raise BacktestJobError("ROLLOVER_INTERRUPTED_OR_QUALITY_GAP")
                                owner = owners[-1]
                                packet, manifest = freeze_research(
                                    session, canonical, product=source.product, strategy=strategy,
                                    frequency=ProductFrequency(frequency),
                                    since=max(source.since, owner.start_trading_day), through=cutoff,
                                    facts_path=source.facts_path, facts_digest=source.facts_sha256,
                                    witnesses=_witnesses(source),
                                )
                                manifest["configured_since"] = source.since
                                if len(owners) > 1:
                                    manifest["prior_owner_boundary"] = {
                                        "status": "ROLLOVER_INTERRUPTED",
                                        "physical_contract": owners[-2].contract,
                                        "through": owners[-2].end_trading_day,
                                    }
                                if frequency.value in ("1d", "1w"):
                                    packet["result_kind"] = manifest["result_kind"] = "reference_only"
                                return packet, manifest

                        try:
                            result = _run_one(store, key, cutoff, freeze, output=output, engine_python=engine_python,
                                              code_identity=identity, retry_failed=retry_series is not None,
                                              source_publication=receipt, source_is_current=verify_source,
                                              publication_fence=publication_fence)
                        except Exception as exc:
                            code = _diagnostic(exc)
                            result = {"status": "DEFERRED" if code in {
                                "BACKTEST_JOB_BUSY", "BACKTEST_CANONICAL_PUBLICATION_CHANGED", "LIVE_RECOVERY_BUSY",
                            } else "UNKNOWN", "code": code}
                        if result is not None:
                            rows.append({"product": key.product, "strategy": key.strategy, "frequency": key.frequency,
                                         "trial": key.is_trial, **result})
        finally:
            store.close()
    finally:
        market_engine.dispose()
    return rows


def _receipt(status: dict) -> tuple[date, str] | None:
    from app.market_data.after_market import public_after_market_status

    public = public_after_market_status(status)
    run = public.get("last_run")
    if not run or run["status"] != "passed":
        return None
    day = date.fromisoformat(run["trading_day"])
    if not affected_products(public, day, set(run["products"])):
        return None
    if datetime.fromisoformat(run["finished_at"]) > datetime.now(UTC):
        raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_INVALID")
    return day, sha256(_json(run)).hexdigest()


def retain_publication(path: Path) -> None:
    """Make a successful status recoverable across subsequent maintenance runs."""
    from app.market_data.after_market import _load_status

    if (status := _load_status(path)) and _receipt(status):
        archive_publication(path, status)


def archive_publication(path: Path, status: dict, *, late: bool = False) -> str:
    from app.market_data.after_market import public_after_market_status

    receipt = _receipt(status)
    if receipt is None:
        raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_INVALID")
    _, identity = receipt
    public = public_after_market_status(status)
    content = {
        "schema_version": 4,
        "last_run": public["last_run"],
        "last_successful_trading_day": public["last_successful_trading_day"],
    }
    if _receipt(content) != receipt:
        raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_INVALID")
    root = path.parent / "newow-publications"
    publish_history((root / "late" if late else root) / f"{identity}.json", content)
    return identity


def _late_recovery_rows(status_path: Path) -> list[dict]:
    from app.market_data.late_provider_recovery import _read

    path = status_path.with_name("late-provider-recovery-status.json")
    return list(_read(path)["runs"].values()) if path.exists() else []


def _late_publication(status_path: Path, row: dict) -> dict:
    identity = row.get("newow_publication_sha256")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        return {}
    status = json.loads(read_owned_file(status_path.parent / "newow-publications" / "late" / f"{identity}.json"))
    receipt = _receipt(status)
    if receipt is None or receipt[1] != identity:
        raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_INVALID")
    run = status.get("last_run") or {}
    if (row["state"] == "passed" and row.get("checks") == 1
            and run.get("finished_at") == row.get("finished_at")
            and run.get("started_at") == row.get("claimed_at")
            and run.get("products") == row.get("products")):
        return status
    return {}


def _retained_statuses(status_path: Path) -> tuple[Path, list[tuple], dict[str, date]]:
    retain_publication(status_path)
    root = status_path.parent / "newow-publications"
    statuses = []
    latest_days: dict[str, date] = {}
    sources = []
    late_rows = _late_recovery_rows(status_path)
    for path in root.glob("*.json"):
        sources.append((path.stem, json.loads(read_owned_file(path))))
    for row in late_rows:
        if row["state"] == "passed":
            status = _late_publication(status_path, row)
            if status:
                sources.append((row["newow_publication_sha256"], status))
    for identity, status in sources:
        receipt = _receipt(status)
        if receipt is None or identity != receipt[1]:
            raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_INVALID")
        day, digest = receipt
        run = status["last_run"]
        statuses.append((datetime.fromisoformat(run["finished_at"]), digest, day, status))
        for product in run["products"]:
            latest_days[product] = max(day, latest_days.get(product, day))
    return root, statuses, latest_days


def _current_authority(status_path: Path) -> tuple[date, str] | None:
    from app.market_data.after_market import _load_status, public_after_market_status
    from app.market_data.late_provider_recovery import SAFE_FAILURES

    raw = _load_status(status_path)
    normal = public_after_market_status(raw)
    last = normal.get("last_run")
    failure = normal.get("last_failure")
    if last and last["status"] == "failed" and failure is None:
        return None
    late_rows = _late_recovery_rows(status_path)
    if normal.get("current_run") or status_path.exists() and not normal:
        return None

    operations = []
    if last and last["status"] == "passed":
        operations.append((datetime.fromisoformat(last["finished_at"]), _receipt(raw)))
    elif last and last["status"] == "skipped" and failure is None:
        successful_day = normal.get("last_successful_trading_day")
        for path in (status_path.parent / "newow-publications").glob("*.json"):
            archived = json.loads(read_owned_file(path))
            receipt = _receipt(archived)
            if receipt and successful_day and receipt[0].isoformat() <= successful_day:
                operations.append((datetime.fromisoformat(archived["last_run"]["finished_at"]), receipt))
    for row in late_rows:
        if row["state"] == "claimed":
            operations.append((datetime.fromisoformat(row["claimed_at"]), None))
            continue
        touches_canonical = row.get("stage") in {"metadata", "plan", "apply", "readback", "live_cleanup"}
        if row["state"] not in {"passed", "failed"} or not touches_canonical:
            continue
        receipt = _receipt(_late_publication(status_path, row))
        if failure and (receipt is None or receipt[0].isoformat() != failure["trading_day"]
                        or failure["error_code"] not in SAFE_FAILURES
                        or row["error_code"] != failure["error_code"]):
            continue
        operations.append((datetime.fromisoformat(row["finished_at"]), receipt))
    if last and last["status"] == "interrupted":
        return None
    return max(operations, key=lambda operation: operation[0])[1] if operations else None


@contextmanager
def _batch_slot(root: Path):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(root / ".consumer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


def _publication_fence(status_path: Path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard

    # Only guard the compare-and-publish boundary; the engine stays outside.
    return after_market_recovery_guard(root=status_path.parent / "live-recovery-guards",
                                       legacy_root=True, wait=False)


def reconcile_publications(status_path: Path, config_path: Path) -> list[dict]:
    """Consume completed publications using the current settled Canonical authority."""
    authority = _current_authority(status_path)
    if authority is None:
        return []
    with _batch_slot(status_path.parent / "newow-publications") as acquired:
        if not acquired:
            return []
        return _reconcile_publications(status_path, config_path, authority)


def _reconcile_publications(status_path: Path, config_path: Path, authority: tuple[date, str]) -> list[dict]:
    """Poll the durable publication outbox, with completed batches keyed by config and code."""
    from app.market_data.after_market import _atomic_write_status

    root, statuses, latest_days = _retained_statuses(status_path)
    config_identity = sha256(_read(config_path, 128 * 1024) + _code_fingerprint().encode()).hexdigest()
    completed = root / "completed" / config_identity
    reports = []
    # The newest complete publication can subsume older work for the same
    # product. Per-series publication ordering prevents old receipts regressing it.
    for finished_at, identity, day, status in sorted(statuses, reverse=True):
        done = completed / f"{identity}.json"
        if done.exists():
            continue
        start = perf_counter()
        def stable():
            return _current_authority(status_path) == authority

        if not stable():
            break
        rows = consume_status(status, day, config_path, latest_days=latest_days, publication_is_stable=stable,
                              publication_fence=lambda: _publication_fence(status_path))
        report = {
            "trigger": "canonical_publication", "publication_sha256": identity,
            "as_of_trading_day": day.isoformat(), "series": len(rows),
            "computed": sum(row["status"] == "SUCCEEDED" and not row.get("reused") for row in rows),
            "failed": [row for row in rows if row["status"] != "SUCCEEDED"],
            "deferred": sum(row["status"] in ("DEFERRED", "UNKNOWN") for row in rows),
            "work_seconds": round(perf_counter() - start, 3),
            "publication_to_completion_seconds": (
                datetime.now(UTC) - finished_at).total_seconds(),
        }
        if not report["deferred"] and stable():
            _atomic_write_status(done, report)
        _LOGGER.info("newow_eod_backtest %s", json.dumps(report))
        reports.append(report)
    return reports


def run_configured(status_path: Path, _day: date | None, config_path: Path) -> None:
    """Run outside the maintenance guard, without changing the Canonical outcome."""
    try:
        reconcile_publications(status_path, config_path)
    except Exception as exc:
        _LOGGER.warning("newow_eod_backtest_consumer_failed code=%s", _diagnostic(exc))


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--trading-day", type=date.fromisoformat)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--retry-series", nargs=3, metavar=("PRODUCT", "STRATEGY", "FREQUENCY"))
    parser.add_argument("--retry-trial", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--receipt")
    args = parser.parse_args()
    if args.receipt and not re.fullmatch(r"[0-9a-f]{64}", args.receipt):
        parser.error("Invalid receipt SHA-256")
    if (args.trading_day and args.receipt or args.watch and (args.trading_day or args.receipt)
            or args.retry_series and not (args.trading_day or args.receipt)
            or args.retry_trial and not args.retry_series):
        parser.error("Pin a trading day or receipt for a targeted retry")
    if args.watch:
        logging.basicConfig(level=logging.INFO)
        while True:
            try:
                reconcile_publications(args.status, args.config)
            except Exception as exc:
                _LOGGER.warning("newow_eod_backtest_consumer_failed code=%s", _diagnostic(exc))
            sleep(30)
    try:
        retry = tuple(args.retry_series) if args.retry_series else None
        if args.receipt or args.trading_day:
            authority = _current_authority(args.status)
            if authority is None:
                raise BacktestJobError("BACKTEST_CANONICAL_PUBLICATION_UNSETTLED")
            _, statuses, latest_days = _retained_statuses(args.status)
            target = args.receipt or authority[1]
            selected = next(((day, status) for _, digest, day, status in statuses if digest == target), None)
            if selected is None or args.trading_day and selected[0] != args.trading_day:
                raise BacktestJobError("BACKTEST_SOURCE_PUBLICATION_NOT_FOUND")
            rows = consume_status(selected[1], selected[0], args.config, retry_series=retry, retry_trial=args.retry_trial,
                                   latest_days=latest_days, publication_is_stable=lambda: _current_authority(args.status) == authority,
                                   publication_fence=lambda: _publication_fence(args.status))
        else:
            rows = reconcile_publications(args.status, args.config)
        print(json.dumps(rows))
    except Exception as exc:
        print(json.dumps({"code": _diagnostic(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
