"""Explicit, isolated FU2603 historical replay. The API only loads results."""

from __future__ import annotations

from argparse import ArgumentParser
from bisect import bisect_right
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.aggregation import aggregate_from_1m
from app.market_data.catalog import MarketCatalog
from app.market_data.composition import build_database_coverage_source
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.composition import NewowComposition
from app.market_data.newow.product_query import NewowProductQuery
from app.market_data.newow.rank1_causality import (
    Rank1AsKnownError,
    Rank1CausalInput,
    Rank1PhysicalFact,
    validate_rank1_as_known,
)
from app.market_data.newow.v2_completed import (
    HistoricalAvailability,
    MarketWindow,
    iter_historical_inputs,
    iter_historical_segments,
)
from app.market_data.storage import CanonicalMonthlyStore
from app.models.market_tables import Contract, MainContractMap
from app.private_settings import load_private_readonly_settings
from app.reference_trading.json_spool import encode_product_bar
from guiyi_quant.newow.decision_adapter import DECISION_VERSION, V2Strategy
from guiyi_quant.newow.product_adapters import OSCILLATION_WARMUP_BARS, build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy, lifecycle_input_sha256
from guiyi_quant.newow.product_identity import InputQualityPolicy
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2

_REPO = Path(__file__).resolve().parents[4]
_ENGINE = _REPO / "services/newow-rqalpha"
_DAY = date(2026, 1, 5)
_PRODUCT, _CONTRACT = "fu", "FU2603"
_FREQ = ProductFrequency("5m")
_ZONE = ZoneInfo("Asia/Shanghai")
_AVAILABILITY = "historical_completed_5m_plus_2_seconds_v1"
_MONEY_POLICY = "cny_8_half_even_v1"
_LIMIT = 32 * 1024 * 1024
# From services/newow-rqalpha/fu_sample.py; checked again by the offline engine test.
_FACTS_SHA = "b28f860978fe2d131001f925233d02ffe10c9f5f50111d9a6bf90671e1bd4335"
_FACTS_NAME = "facts-attempt-001/FU2603.json"


class BacktestJobError(ValueError):
    def __init__(self, code: str, *, audit: dict | None = None):
        self.code = code
        self.audit = audit
        super().__init__(code)


def _value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("P3_JSON_VALUE_INVALID")


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_value, allow_nan=False).encode()


def _sha(value) -> str:
    return sha256(_json(value)).hexdigest()


def _read(path: Path, maximum: int = _LIMIT) -> bytes:
    with path.open("rb") as source:
        body = source.read(maximum + 1)
    if len(body) > maximum:
        raise BacktestJobError("P3_ARTIFACT_TOO_LARGE")
    return body


def _rule2_witness(path: Path | None, digest: str | None) -> tuple[str, str] | None:
    if path is None and digest is None:
        return None
    if path is None or digest is None or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BacktestJobError("P3_RULE2_WITNESS_IDENTITY_REQUIRED")
    raw = _read(path, 4096)
    if sha256(raw).hexdigest() != digest:
        raise BacktestJobError("P3_RULE2_WITNESS_DIGEST_MISMATCH")
    witness = json.loads(raw)
    if not isinstance(witness, dict) or witness != {
        "source": "rqdata.futures.get_dominant", "product": _PRODUCT,
        "trading_day": str(_DAY), "rule": 2, "rank": 1, "physical_contract": _CONTRACT,
    }:
        raise BacktestJobError("P3_RULE2_WITNESS_SCOPE_INVALID")
    return witness["physical_contract"], digest


def _rank1_evidence(
    mds: MarketDataService, session: Session, product: str, contract_code: str,
    day: date, day_open: datetime, rule2: tuple[str, str] | None,
) -> dict:
    """Qualify a frozen Catalog mapping with prior physical daily facts, without reranking the route."""
    prior = mds.previous_trading_day(product, day)
    prior_end = mds.session_windows(symbol=product, trading_day=prior)[-1].end
    catalog_row = session.scalars(select(MainContractMap).where(
        MainContractMap.symbol == product, MainContractMap.trade_date == day,
    )).one()
    if (catalog_row.contract_code, catalog_row.rank, catalog_row.rule) != (contract_code, 1, "volume_open_interest"):
        raise BacktestJobError("P3_OWNER_MAPPING_CONFLICT")
    universe = tuple(session.scalars(select(Contract.contract_code).where(
        Contract.instrument_symbol == product, Contract.provider == "rqdata",
        Contract.listed_date <= prior, Contract.expired_date > prior,
    ).order_by(Contract.contract_code)))
    facts, missing = [], []
    for contract in universe:
        try:
            (bar,) = mds.query_contract_trading_days(
                ContractTradingDayQuery(product, contract, BarFrequency.D1, prior, prior),
            ).bars
        except Exception as exc:
            if getattr(exc, "code", None) not in {"DATASET_OR_PARTITION_MISSING", "QUERY_WINDOW_EMPTY"}:
                raise
            missing.append(contract)
            continue
        if bar.open_interest is None or bar.bar_end != prior_end:
            missing.append(contract)
            continue
        facts.append(Rank1PhysicalFact(contract, bar.volume, bar.open_interest))
    proof = {
        "prior_trading_day": prior,
        "prior_bar_end": prior_end,
        "first_session_open": day_open,
        "mapping_updated_at": catalog_row.updated_at,
        "provider_rule2_sha256": rule2[1] if rule2 else None,
        "universe": universe,
        "missing_daily_facts": missing,
        "physical_facts": [asdict(fact) for fact in facts],
        "code": "RANK1_AS_KNOWN_UNPROVEN",
        "prior_cross_section_matches": False,
        "as_known_publication_unproven": True,
    }
    if rule2 is not None and not missing and catalog_row.updated_at <= day_open:
        try:
            validate_rank1_as_known((Rank1CausalInput(
                product, day, prior, prior_end, day_open, universe, tuple(facts),
                rule2[0], catalog_row.contract_code,
            ),))
        except Rank1AsKnownError:
            return proof
        # A match against today's Catalog does not timestamp the original
        # physical cross-section or the rule=2 observation before this open.
        proof["prior_cross_section_matches"] = True
    return proof


def _execution_facts(path: Path, digest: str, contract: str, days: tuple[date, ...]) -> tuple[dict, list[dict]]:
    try:
        body = _read(path)
    except FileNotFoundError:
        raise BacktestJobError("P3_DATED_EXECUTION_FACTS_MISSING") from None
    if sha256(body).hexdigest() != digest:
        raise BacktestJobError("P3_DATED_FACTS_DIGEST_MISMATCH")
    facts = json.loads(body)
    instrument = facts["instrument"]
    if instrument["order_book_id"] != contract:
        raise BacktestJobError("P3_DATED_FACTS_CONTRACT_MISMATCH")
    multiplier = Decimal(str(instrument["contract_multiplier"]))
    if not multiplier.is_finite() or multiplier <= 0 or multiplier != multiplier.to_integral_value():
        raise BacktestJobError("BACKTEST_CONTRACT_MULTIPLIER_INVALID")
    instrument = {**instrument, "contract_multiplier": int(multiplier)}
    daily = []
    for day in days:
        rates = [row for row in facts["parameters"] if row["date"] == str(day)]
        settlements = [row for row in facts["daily"] if row["date"] == str(day)]
        if len(rates) != 1 or len(settlements) != 1:
            raise BacktestJobError("P3_DATED_EXECUTION_FACTS_MISSING")
        rate, settlement = rates[0], settlements[0]
        daily.append({
            "day": day,
            "prev_settlement": Decimal(settlement["prev_settlement"]),
            "settlement": Decimal(settlement["settlement"]),
            "limit_down": Decimal(settlement["limit_down"]),
            "limit_up": Decimal(settlement["limit_up"]),
            "fee_type": rate["commission_type"],
            "open_fee": Decimal(rate["open_commission"]),
            "close_fee": Decimal(rate["close_commission"]),
            "close_today_fee": Decimal(rate["close_commission_today"]),
            "long_margin": Decimal(rate["long_margin_ratio"]),
            "short_margin": Decimal(rate["short_margin_ratio"]),
        })
    return instrument, daily


def freeze_fu2603(
    session: Session, canonical: Path, facts_dir: Path, *, rule2: tuple[str, str] | None = None,
) -> tuple[dict, dict]:
    """Compatibility entry for the exact P3 evidence scope."""
    return freeze_research(
        session, canonical, product=_PRODUCT, strategy=V2Strategy.TREND, frequency=_FREQ,
        since=_DAY, through=_DAY, facts_path=facts_dir / _FACTS_NAME, facts_digest=_FACTS_SHA,
        expected_contract=_CONTRACT, witnesses={_DAY: rule2} if rule2 else {},
    )


def freeze_research(
    session: Session, canonical: Path, *, product: str, strategy: V2Strategy, frequency: ProductFrequency,
    since: date, through: date, facts_path: Path, facts_digest: str,
    witnesses: dict[date, tuple[str, str]], expected_contract: str | None = None,
) -> tuple[dict, dict]:
    """Freeze one bounded, uninterrupted physical segment using MDS and dated facts."""
    market_frequency = BarFrequency(frequency.value)
    mds = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
    final_sessions = mds.session_windows(symbol=product, trading_day=through)
    as_of = final_sessions[-1].end + timedelta(seconds=2)
    day_windows = mds.completed_trading_day_windows(
        symbol=product, start=datetime.combine(since, time.min, _ZONE), as_of=as_of,
        latest=through, calendar_since=since,
    )
    if not day_windows or day_windows[-1][0] != through:
        raise BacktestJobError("BACKTEST_COMPLETE_TRADING_DAY_MISSING")
    owners = mds.actual_dominant_segments(product, since, through)
    if len(owners) != 1:
        raise BacktestJobError("ROLLOVER_INTERRUPTED_OR_QUALITY_GAP")
    owner = owners[0]
    contract_code = owner.contract
    if expected_contract is not None and contract_code != expected_contract:
        raise BacktestJobError("P3_OWNER_MAPPING_CONFLICT")
    contract = mds.catalog.contract_fact(product, contract_code)
    instrument, daily = _execution_facts(facts_path, facts_digest, contract_code,
                                        tuple(day for day, _ in day_windows))
    reader = NewowComposition(
        mds, build_database_coverage_source(session, reuse_session_windows=True),
        (product,), InputQualityPolicy.V1,
    ).reader()
    provenance = reader.historical_source_evidence(
        product=product, frequency=frequency.value, since=since, through=through, as_of=as_of,
    )
    if market_frequency in (BarFrequency.D1, BarFrequency.W1):
        provenance["execution_m1"] = mds.contract_source_evidence(
            symbol=product, contract=contract_code, frequency=BarFrequency.M1, before=as_of,
        )
    rank_facts = tuple(_rank1_evidence(mds, session, product, contract_code, day, windows[0].start,
                                      witnesses.get(day)) for day, windows in day_windows)
    verified = all(fact["code"] == "RANK1_AS_KNOWN_VERIFIED" for fact in rank_facts)
    rank1 = {
        **(rank_facts[0] if len(rank_facts) == 1 else {"trading_days": rank_facts}),
        "code": "RANK1_AS_KNOWN_VERIFIED" if verified else "RANK1_AS_KNOWN_UNPROVEN",
    }
    revision = _sha(provenance)
    owner_ref = _sha((product, contract_code, owner.start_trading_day, owner.end_trading_day, rank1))
    request = ContractTradingDayQuery(product, contract_code, BarFrequency.M1, day_windows[0][0], through)
    minutes = mds.query_contract_trading_days(request).bars
    if not minutes or any(bar.open_interest is None for bar in minutes):
        raise BacktestJobError("P3_M1_OI_OR_COVERAGE_MISSING")
    sessions = tuple(window for _, windows in day_windows for window in windows)
    opens = tuple(bar.bar_end - timedelta(minutes=1) for bar in minutes)
    query_strategy = ProductStrategy.OSCILLATION if strategy is V2Strategy.OSCILLATION else ProductStrategy.TREND
    query = NewowProductQuery(product, query_strategy, frequency, since, through,
                              performance_since=since, performance_through=through)
    read = reader.load_historical(query, as_of)
    try:
        if len(read.owners) != 1 or read.owners[0].contract != contract_code or read.data_interruptions:
            raise BacktestJobError("ROLLOVER_INTERRUPTED_OR_QUALITY_GAP")
        original = tuple(read.replay_bars)
        (lifecycle,) = read.lifecycle_evidence
        if (not original or lifecycle.bar_count != len(original)
            or lifecycle.input_sha256 != lifecycle_input_sha256(original)
            or lifecycle.first_bar_end != original[0].bar.bar_end
            or lifecycle.last_bar_end != original[-1].bar.bar_end):
            raise BacktestJobError("P3_LIFECYCLE_UNVERIFIED")
        evaluation = [item.bar for item in original if since <= item.bar.trading_day <= through]
        if market_frequency not in (BarFrequency.D1, BarFrequency.W1):
            aggregates = aggregate_from_1m(minutes, target_frequency=frequency.value, sessions=sessions)
            fields = ("trading_day", "bar_end", "open", "high", "low", "close", "volume", "open_interest")
            if len(evaluation) != len(aggregates) or any(
                any(getattr(bar, field) != getattr(aggregate, field) for field in fields)
                for bar, aggregate in zip(evaluation, aggregates, strict=True)
            ):
                raise BacktestJobError("BACKTEST_M1_SIGNAL_PARITY_FAILED")
        if any(item.bar.open_interest is None for item in original):
            raise BacktestJobError("BACKTEST_SIGNAL_OI_MISSING")
        bars = tuple(replace(item, bar=replace(item.bar, observation_eligible=False))
                     if item.bar.trading_day < since and item.bar.observation_eligible else item for item in original)
        warmup_count = len(bars) - len(evaluation)
        warmup_required = (NEWOW_TREND_D1_PAGE_V2.trend_signal_period if strategy is V2Strategy.TREND
                           else OSCILLATION_WARMUP_BARS)
        if not evaluation or warmup_count < warmup_required:
            raise BacktestJobError("BACKTEST_WARMUP_INSUFFICIENT")
        windows_by_day: dict[date, MarketWindow] = {}

        def window_for(item):
            bar = item.bar
            if bar.trading_day not in windows_by_day:
                windows_by_day[bar.trading_day] = MarketWindow.from_mds(
                    mds, product=product, contract=contract_code, owner_segment_id=bar.segment_id,
                    owner_ref=owner_ref, trading_day=bar.trading_day, frequency=market_frequency,
                    as_of=as_of, warmup=bar.trading_day < since,
                )
            return windows_by_day[bar.trading_day]

        availability_policy = (_AVAILABILITY if frequency.value == "5m"
                               else f"historical_completed_{frequency.value}_plus_2_seconds_v1")

        def availability_for(item):
            return HistoricalAvailability(item.bar.bar_end + timedelta(seconds=2), availability_policy)

        prepared = replace(read, bars_by_frequency={frequency: bars})
        inputs = iter_historical_inputs(
            prepared, revision=revision, as_of=as_of, window_for=window_for,
            availability_for=availability_for, verified_prefix_for=lambda _: True,
        )
        completed = []
        (segment,) = tuple(tuple(group) for _, group in iter_historical_segments(inputs))
        for item in segment:
            payload = item.payload
            start, end = payload.session
            index = bisect_right(opens, payload.available_at)
            candidate = opens[index] if (payload.bar.bar.observation_eligible
                         and index < len(opens) and start <= opens[index] < end) else None
            completed.append({
                "bar": encode_product_bar(payload.bar), "source_ref": payload.source_ref,
                "owner_ref": payload.owner_ref, "session": payload.session,
                "available_at": payload.available_at, "availability_policy": payload.availability_policy,
                "quality_policy": payload.quality_policy, "verified_lifecycle": payload.verified_lifecycle,
                "fingerprint": item.fingerprint, "candidate_open_at": candidate,
            })
    finally:
        read.close()
    underlying = (ProductStrategy.TREND, ProductStrategy.OSCILLATION) if strategy is V2Strategy.DUAL_FUSION else (query_strategy,)
    identities = tuple(build_product_identity(product, member, frequency,
                       input_quality_policy=read.input_quality_policy) for member in underlying)
    packet = {
        "strategy": strategy.value, "frequency": frequency.value,
        "market_revision": revision, "initial_equity": "10000.00000000",
        "execution_profile": "same_session_first_open_one_long_lot_v1",
        "market": {
            "contract": contract_code, "exchange": contract.exchange, "window_start": owner.start_trading_day,
            "window_end": owner.end_trading_day, "listed_date": contract.listed_date,
            "expired_date": contract.expired_date, "tick": instrument["tick_size"],
            "multiplier": instrument["contract_multiplier"], "daily": daily,
            "sessions": [(day, window.start, window.end) for day, windows in day_windows for window in windows],
            "minutes": [(bar.trading_day, bar.bar_end, bar.open, bar.high, bar.low, bar.close, bar.volume)
                        for bar in minutes],
            "minute_oi": [(bar.bar_end, bar.open_interest) for bar in minutes],
        },
        "completed": completed,
    }
    manifest = {
        "as_of_trading_day": through, "since": since, "through": through, "market_as_of": as_of,
        "physical_contract": contract_code, "market_revision": revision, "source_evidence": provenance,
        "rank1": rank1, "dated_facts_sha256": facts_digest,
        "engine": "RQAlpha", "engine_version": "6.3.0", "decision_version": DECISION_VERSION,
        "execution_profile": packet["execution_profile"], "availability_policy": availability_policy,
        "strategy_profile": identities[0].profile_id,
        "strategy_profiles": [identity.profile_id for identity in identities],
        "formula_versions": list(dict.fromkeys(v for identity in identities for v in identity.formula_versions)),
        "money_policy": _MONEY_POLICY, "initial_equity": packet["initial_equity"],
        "warmup_count": warmup_count, "signal_bar_count": len(evaluation), "execution_bar_count": len(minutes),
        "dated_execution_facts": daily[0] if len(daily) == 1 else daily,
    }
    return packet, manifest


def _seal(root: Path, data: bytes, fingerprint: str) -> Path:
    target = root / (fingerprint + ".json")
    with NamedTemporaryFile(dir=root) as scratch:
        scratch.write(data)
        scratch.flush()
        os.fsync(scratch.fileno())
        try:
            os.link(scratch.name, target, follow_symlinks=False)
        except FileExistsError:
            if target.is_symlink() or sha256(_read(target)).hexdigest() != fingerprint:
                raise BacktestJobError("P3_FROZEN_ARTIFACT_CONFLICT") from None
    return target


def _launch(engine_python: Path, frozen: Path, fingerprint: str, run_id: str) -> dict:
    sandbox = Path("/usr/bin/sandbox-exec")
    if not sandbox.is_file():
        raise BacktestJobError("P3_OFFLINE_SANDBOX_UNAVAILABLE")
    if not engine_python.is_absolute() or not engine_python.is_file():
        raise BacktestJobError("P3_ENGINE_INTERPRETER_MISSING")
    profile = '(version 1) (allow default) (deny network*) (deny file-read* (subpath (param "LEGACY")))'
    with TemporaryDirectory(prefix="guiyi-p3-offline-") as directory:
        output = Path(directory) / "result.json"
        command = [
            str(sandbox), "-D", f"LEGACY={Path.home() / '.rqalpha'}", "-p", profile, str(engine_python), "-B",
            str(_ENGINE / "replay.py"), str(frozen), fingerprint, run_id, str(output),
        ]
        process = subprocess.run(
            command, cwd=directory,
            env={"PYTHONPATH": os.pathsep.join(str(_REPO / path) for path in ("packages/quant-core", "services/quant-api"))},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False,
        )
        result = json.loads(_read(output)) if output.is_file() else {}
        if process.returncode:
            error = result.get("error", "")
            raise BacktestJobError(
                error if _safe_code(error) else "P3_ENGINE_REPLAY_FAILED", audit=result.get("audit"),
            )
        if result.get("run_id") != run_id or result.get("input_sha256") != fingerprint:
            raise BacktestJobError("P3_ENGINE_RESULT_IDENTITY_MISMATCH")
        return result


def _safe_code(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z_0-9]{1,79}", value) is not None


def _diagnostic(exc: Exception) -> str:
    code = getattr(exc, "code", str(exc))
    return code if _safe_code(code) else "P3_JOB_FAILED"


def _code_fingerprint() -> str:
    engine_files = ("replay.py", "runner.py", "frozen_market.py", "reconcile.py", "uv.lock")
    core_files = ("decision_adapter.py", "product_adapters.py", "trend_band.py", "profile.py", "escape_d123.py",
                  "product_contracts.py", "product_identity.py", "reference_pricing.py", "models.py",
                  "oscillation_trueup.py", "oscillation_channel.py", "fusion_reference.py")
    api_root = _REPO / "services/quant-api/app"
    paths = (
        Path(__file__),
        *(_ENGINE / file for file in engine_files),
        *(_REPO / "packages/quant-core/guiyi_quant/newow" / file for file in core_files),
        _REPO / "packages/quant-core/guiyi_quant/reference_trading/adapters.py",
        api_root / "market_data/newow/v2_completed.py",
        api_root / "market_data/newow/rank1_causality.py",
        api_root / "market_data/newow/product_reader.py",
        api_root / "market_data/market_data_service.py",
        api_root / "market_data/aggregation.py",
        api_root / "reference_trading/json_spool.py",
    )
    return _sha({str(path.relative_to(_REPO)): sha256(_read(path)).hexdigest() for path in paths})


def main() -> None:
    from app.services.newow_backtest_results import FORMAL_PROFILE, TRIAL_PROFILE, ResultStore, SeriesKey

    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--facts-dir", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--engine-python", type=Path, default=_ENGINE / ".venv/bin/python")
    parser.add_argument("--market-settings", type=Path,
                        default=Path.home() / "Library/Application Support/GuiyiQuant/project.env")
    parser.add_argument("--rule2-witness", type=Path, help="An independently captured RQData rule=2 witness.")
    parser.add_argument("--rule2-sha256", help="Expected SHA-256 of the original rule=2 witness bytes.")
    parser.add_argument("--trial", action="store_true", help="Publish in the isolated trial series only.")
    args = parser.parse_args()
    store = None
    admission = None
    job_slot = ExitStack()
    job_connection = None
    publishing = False
    key = SeriesKey(_PRODUCT, "trend", _FREQ.value, TRIAL_PROFILE if args.trial else FORMAL_PROFILE)
    try:
        store = ResultStore(os.environ.get("GUIYI_NEWOW_BACKTEST_WRITE_DSN", ""))
        job_connection = job_slot.enter_context(store.job_slot(key))
        settings, _ = load_private_readonly_settings(args.market_settings)
        market_engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), connect_args={"connect_timeout": 5})
        try:
            canonical = Path(settings["GUIYI_CANONICAL_DATA_ROOT"]).resolve(strict=True)
            output = args.input_dir.resolve(strict=True)
            if not output.is_dir() or output.is_relative_to(canonical) or canonical.is_relative_to(output):
                raise BacktestJobError("P3_INPUT_DIRECTORY_UNSAFE")
            with Session(market_engine) as market_read, readonly_transaction(market_read, timeout_seconds=60):
                packet, manifest = freeze_fu2603(
                    market_read, canonical, args.facts_dir,
                    rule2=_rule2_witness(args.rule2_witness, args.rule2_sha256),
                )
        finally:
            market_engine.dispose()
        data = _json(packet)
        if len(data) > _LIMIT:
            raise BacktestJobError("P3_ARTIFACT_TOO_LARGE")
        fingerprint = sha256(data).hexdigest()
        frozen = _seal(output, data, fingerprint)
        manifest["input_sha256"] = fingerprint
        manifest["code_sha256"] = _code_fingerprint()
        eligible = manifest["rank1"]["code"] == "RANK1_AS_KNOWN_VERIFIED"
        admission = store.admit(key, json.loads(_json(manifest)), eligible=eligible and not args.trial,
                                job_connection=job_connection)
        if not admission.should_run:
            if admission.status != "SUCCEEDED":
                raise BacktestJobError("P3_RUN_ALREADY_ACTIVE")
            print(json.dumps({"run_id": admission.run_id, "disposition": "ALREADY_SUCCEEDED"}))
            return
        if not eligible and not args.trial:
            raise BacktestJobError(manifest["rank1"]["code"])
        result = _launch(args.engine_python, frozen, fingerprint, admission.run_id)
        if result.get("summary", {}).get("money_policy") != manifest["money_policy"]:
            raise BacktestJobError("P3_MONEY_POLICY_MISMATCH")
        publishing = True
        store.publish(admission, result["summary"], result["trades"], result["equity"])
        print(json.dumps({"run_id": admission.run_id, "disposition": "SUCCEEDED",
                          "qualification": "TRIAL" if args.trial else "QUALIFIED", "input_sha256": fingerprint}))
    except Exception as exc:
        code = _diagnostic(exc)
        failed_before_commit = code in {
            "BACKTEST_RESULT_WRITE_FAILED", "BACKTEST_AMOUNT_INVALID", "BACKTEST_SEQUENCE_INVALID",
            "BACKTEST_TRADE_INVALID", "BACKTEST_EQUITY_INVALID", "BACKTEST_VALUE_INVALID", "BACKTEST_FORMAL_INELIGIBLE",
        }
        if store is not None and job_connection is not None and (not publishing or failed_before_commit):
            if admission is None:
                failed = {"as_of_trading_day": str(_DAY), "physical_contract": _CONTRACT, "preflight_error": code}
                try:
                    admission = store.admit(key, failed, eligible=False, job_connection=job_connection)
                except ValueError:
                    admission = None
            if admission is not None and admission.should_run:
                try:
                    store.fail(admission, code)
                except ValueError as recording_error:
                    code = _diagnostic(recording_error)
        failure = {"disposition": "FAILED", "code": code, "run_id": admission.run_id if admission else None}
        if isinstance(exc, BacktestJobError) and exc.audit is not None:
            failure["audit"] = exc.audit
        print(json.dumps(failure))
        raise SystemExit(1) from None
    finally:
        job_slot.close()
        if store is not None:
            store.close()


if __name__ == "__main__":
    main()
