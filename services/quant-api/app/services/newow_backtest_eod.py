"""Optional isolated consumer of the existing completed Canonical maintenance receipt."""

from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
from time import perf_counter

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
    if (run.get("status"), run.get("trading_day"), status.get("last_successful_trading_day")) != (
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
    source_is_current=None,
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
                return None
            packet, manifest = frozen_input
            data = _json(packet)
            if len(data) > _LIMIT:
                raise BacktestJobError("P3_ARTIFACT_TOO_LARGE")
            fingerprint = sha256(data).hexdigest()
            manifest.update(input_sha256=fingerprint, code_sha256=code_identity)
        except Exception as exc:
            code = _diagnostic(exc)
            admission = store.admit(key, {
                "as_of_trading_day": day, "preflight_error": code, "code_sha256": code_identity,
            }, eligible=False, job_connection=connection, retry_failed=retry_failed)
            if admission.should_run:
                store.fail(admission, code)
            return {"run_id": admission.run_id, "status": "FAILED", "code": code}

        qualified = manifest["rank1"]["code"] == "RANK1_AS_KNOWN_VERIFIED"
        admission = store.admit(key, manifest, eligible=qualified and not key.is_trial,
                                job_connection=connection, retry_failed=retry_failed)
        if not admission.should_run:
            return {"run_id": admission.run_id, "status": admission.status, "reused": True}
        frozen_at = perf_counter()
        try:
            if not key.is_trial and not qualified:
                raise BacktestJobError("RANK1_AS_KNOWN_UNPROVEN")
            if key.frequency in ("1d", "1w"):
                raise BacktestJobError("BACKTEST_EXECUTION_POLICY_UNAVAILABLE")
            frozen = _seal(output, data, fingerprint)
            result = _launch(engine_python, frozen, fingerprint, admission.run_id)
            if result.get("summary", {}).get("money_policy") != manifest["money_policy"]:
                raise BacktestJobError("P3_MONEY_POLICY_MISMATCH")
        except Exception as exc:
            code = _diagnostic(exc)
            store.fail(admission, code)
            return {"run_id": admission.run_id, "status": "FAILED", "code": code}
        computed_at = perf_counter()
        try:
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


def consume_status(raw_status: dict, day: date, config_path: Path, *, retry_series: tuple[str, str, str] | None = None) -> list[dict]:
    from app.market_data.after_market import public_after_market_status

    status = public_after_market_status(raw_status)
    config = _read_config(config_path)
    products = affected_products(status, day, {item.product for item in config})
    if not products:
        return []
    url = _isolated_market_url(os.getenv("GUIYI_NEWOW_EOD_MARKET_DSN", ""))
    canonical = Path(os.environ["GUIYI_NEWOW_EOD_CANONICAL_ROOT"]).resolve(strict=True)
    output = Path(os.environ["GUIYI_NEWOW_EOD_INPUT_DIR"]).resolve(strict=True)
    if not canonical.is_dir() or not output.is_dir() or output.is_relative_to(canonical) or canonical.is_relative_to(output):
        raise BacktestJobError("P3_INPUT_DIRECTORY_UNSAFE")
    engine_python = Path(os.getenv("GUIYI_NEWOW_EOD_ENGINE", str(_ENGINE / ".venv/bin/python")))
    publication = status["last_run"]["historical_publications"]
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
                if source.product not in products or source.since > day:
                    continue
                for frequency in sorted(DECISION_FREQUENCIES):
                    for strategy in V2Strategy:
                        key = research_key(source.product, strategy.value, frequency.value, trial=source.trial)

                        if retry_series is not None and (key.product, key.strategy, key.frequency) != retry_series:
                            continue

                        def verify_source():
                            with Session(market_engine) as session, readonly_transaction(session, timeout_seconds=30):
                                return _source_is_current(MarketCatalog(session, canonical), publication, source.product)

                        def freeze():
                            with Session(market_engine) as session, readonly_transaction(session, timeout_seconds=60):
                                if not _source_is_current(MarketCatalog(session, canonical), publication, source.product):
                                    return None
                                return freeze_research(
                                    session, canonical, product=source.product, strategy=strategy,
                                    frequency=ProductFrequency(frequency), since=source.since, through=day,
                                    facts_path=source.facts_path, facts_digest=source.facts_sha256,
                                    witnesses=_witnesses(source),
                                )

                        try:
                            result = _run_one(store, key, day, freeze, output=output, engine_python=engine_python,
                                              code_identity=identity, retry_failed=retry_series is not None,
                                              source_publication=receipt, source_is_current=verify_source)
                        except Exception as exc:
                            code = _diagnostic(exc)
                            result = {"status": "DEFERRED" if code == "BACKTEST_JOB_BUSY" else "UNKNOWN",
                                      "code": code}
                        if result is not None:
                            rows.append({"product": key.product, "strategy": key.strategy, "frequency": key.frequency,
                                         "trial": key.is_trial, **result})
        finally:
            store.close()
    finally:
        market_engine.dispose()
    return rows


def run_configured(path: Path, day: date, config_path: Path) -> None:
    """A derived consumer failure never changes the saved Canonical outcome."""
    from app.market_data.after_market import _load_status

    try:
        for item in consume_status(_load_status(path), day, config_path):
            _LOGGER.info("newow_eod_backtest %s", json.dumps(item))
    except Exception as exc:
        _LOGGER.warning("newow_eod_backtest_consumer_failed code=%s", _diagnostic(exc))


def main() -> None:
    from app.market_data.after_market import _load_status

    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--trading-day", type=date.fromisoformat, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--retry-series", nargs=3, metavar=("PRODUCT", "STRATEGY", "FREQUENCY"))
    args = parser.parse_args()
    try:
        print(json.dumps(consume_status(_load_status(args.status), args.trading_day,
                                       args.config, retry_series=tuple(args.retry_series) if args.retry_series else None)))
    except Exception as exc:
        print(json.dumps({"code": _diagnostic(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
