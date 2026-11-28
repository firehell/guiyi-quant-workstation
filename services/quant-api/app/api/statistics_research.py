"""The bounded, explicitly requested research workflow."""

from datetime import date, timedelta
import sqlite3
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.backtest_center import get_store as get_backtest_store
from app.api.local_write import require_workstation_origin
from app.backtest_center.codec import digest
from app.backtest_center.contracts import BacktestError, Key, RunConfig
from app.backtest_center.experiments import FoldConfig, create_experiment
from app.backtest_center.store import RunStore
from app.backtest_center.worker import Settings
from app.db.session import get_db
from app.market_data.domain import ContractError
from app.market_data.market_data_service import MarketDataError
from app.research_center import VERSION
from app.research_center.advanced import (
    create_request, event_input, owner_path, panel_input, run_binding, search_input, verified_task,
)
from app.research_center.inputs import ResearchError, backtest_input, comparison_differences, published_runs
from app.research_center.journal import fills_input, journal_input
from app.research_center.market import market_input
from app.research_center.store import Store, compute, input_digest, worker_python, worker_revision
from app.trade_journal.store import JournalError

router = APIRouter(prefix="/api/v1/statistics-research", tags=["statistics-research"])
Database = Annotated[Session, Depends(get_db)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]
Limit = Annotated[int, Query(ge=1, le=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Backtest(Input):
    kind: Literal["backtest"]
    run_id: Key


class Case(Input):
    kind: Literal["case"]
    case_id: UUID


class Market(Input):
    kind: Literal["factor", "event"]
    product: Annotated[str, StringConstraints(pattern=r"^[a-z]{1,8}$")]
    contract: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,8}[0-9]{3,4}$")]
    frequency: Literal["5m", "15m", "30m", "60m"] = "60m"
    since: date
    through: date
    feature: Literal["trend_direction", "atr", "volume_ratio", "obv", "ema10", "ema21", "ema60", "macd", "stddev"] = "trend_direction"

    @model_validator(mode="after")
    def validate_window(self):
        if not timedelta(0) <= self.through - self.since <= timedelta(days=180):
            raise ValueError("Window must span at most 181 calendar days")
        return self


class Fills(Input):
    kind: Literal["fills"]
    book: Literal["SIMNOW", "SUBING_PAPER", "NEWOW_REFERENCE"]
    day: date
    scope: Annotated[str, StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:\-/]+$")]
    contract: Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{1,8}[0-9]{3,4}$")]


class Panel(Input):
    kind: Literal["panel"]
    members: Annotated[list[UUID], Field(min_length=3, max_length=8)]
    hac_lag: int = Field(default=2, ge=0, le=8)

    @model_validator(mode="after")
    def unique_members(self):
        if len(self.members) != len(set(self.members)):
            raise ValueError("Duplicate member")
        return self


class EventTest(Input):
    kind: Literal["event_test"]
    member: UUID
    hac_lag: int = Field(default=2, ge=0, le=8)


class Search(Input):
    kind: Literal["search"]
    base_run_id: Key
    choices: Annotated[list[Literal[0, 1, 2, 3]], Field(min_length=2, max_length=4)]
    budget: int = Field(ge=2, le=4)
    seed: int = Field(default=13, ge=0, le=2 ** 32 - 1)
    folds: Annotated[list[FoldConfig], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def candidate_budget(self):
        if len(set(self.choices)) != len(self.choices) or self.budget > len(self.choices):
            raise ValueError("Candidate budget exceeds distinct registered choices")
        return self


class Task(Input):
    id: UUID
    source: Annotated[Backtest | Case | Market | Fills | Panel | EventTest | Search, Field(discriminator="kind")]
    rerun_of: UUID | None = None


def authorize(request: Request):
    require_workstation_origin(request, "RESEARCH_ORIGIN_FORBIDDEN")


writes = [Depends(authorize)]


def fail(exc):
    if isinstance(exc, (OSError, sqlite3.Error, SQLAlchemyError)):
        return HTTPException(503, detail={"code": "RESEARCH_STORAGE_UNAVAILABLE"})
    if isinstance(exc, ContractError):
        return HTTPException(422, detail={"code": "RESEARCH_CONTRACT_INVALID"})
    code = getattr(exc, "code", None) or str(exc)
    if not code.isidentifier():
        code = "RESEARCH_EVIDENCE_INVALID"
    return HTTPException(404 if code.endswith("NOT_FOUND") else 409, detail={"code": code})


EVIDENCE_ERRORS = (ResearchError, BacktestError, JournalError, ContractError, MarketDataError)


@router.get("/sources")
def sources():
    configured = Settings.local().path.is_file()
    return {"version": VERSION, "worker": worker_python().is_file(), "sources": [
        {"kind": "backtest", "status": "AVAILABLE" if configured else "NOT_CONFIGURED"},
        {"kind": "case", "status": "EXACT_CASE_REQUIRED"},
        {"kind": "factor", "status": "EXACT_MARKET_WINDOW_REQUIRED"},
        {"kind": "event", "status": "EXACT_MARKET_WINDOW_REQUIRED"},
        {"kind": "advanced", "status": "EXACT_PUBLISHED_RESEARCH_REQUIRED"},
        {"kind": "reference", "status": "EXACT_ACCOUNT_SCOPE_REQUIRED"},
        {"kind": "paper", "status": "VERIFIED_ACCOUNT_SETTLEMENT_REQUIRED"},
        {"kind": "simnow", "status": "VERIFIED_ACCOUNT_SETTLEMENT_REQUIRED"},
    ]}


@router.get("/backtests")
def backtests(offset: Offset = 0, limit: Limit = 30, product: str | None = None, strategy_id: Key | None = None,
              frequency: Literal["5m", "15m", "30m", "60m", "1d", "1w"] | None = None):
    try:
        return published_runs(offset, limit, product=product.lower() if product else None,
                              strategy_id=strategy_id, signal_frequency=frequency)
    except FileNotFoundError:
        raise HTTPException(503, detail={"code": "BACKTEST_STORE_NOT_CONFIGURED"}) from None
    except (sqlite3.Error, OSError) as exc:
        raise fail(exc) from None


@router.get("/comparison")
def comparison(left: UUID, right: UUID, db: Database):
    try:
        store = Store(db)
        members = [store.get(key) for key in (left, right)]
        if any(not member or member["status"] != "SUCCEEDED"
               or member["result"]["source"]["kind"] != "backtest" for member in members):
            raise ResearchError("RESEARCH_COMPARISON_REQUIRES_TWO_PUBLISHED_BACKTESTS")
        results = [member["result"] for member in members]
        differences = comparison_differences(*results)
        return {"members": [
            {"id": member["id"], **{key: row[key] for key in ("source", "coverage", "trades", "performance")}}
            for member, row in zip(members, results, strict=True)
        ], "comparable": not differences, "different_or_missing": differences}
    except (ResearchError, SQLAlchemyError, OSError) as exc:
        raise fail(exc) from None


@router.get("/tasks")
def tasks(db: Database, offset: Offset = 0, limit: Limit = 30):
    try:
        return Store(db).list(offset, limit)
    except SQLAlchemyError as exc:
        raise fail(exc) from None


@router.get("/tasks/{task_id}")
def result(task_id: UUID, db: Database):
    try:
        row = Store(db).get(task_id)
        if row is None:
            raise ResearchError("RESEARCH_TASK_NOT_FOUND")
        return row
    except (ResearchError, SQLAlchemyError, OSError) as exc:
        raise fail(exc) from None


@router.get("/tasks/{task_id}/samples")
def samples(task_id: UUID, db: Database, offset: Offset = 0, limit: Limit = 50,
            month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
            group: Annotated[str | None, Query(max_length=30)] = None):
    try:
        return Store(db).samples(task_id, offset, limit, month, group)
    except (ResearchError, SQLAlchemyError, OSError) as exc:
        raise fail(exc) from None


def prepare(request, db, source):
    if isinstance(source, Backtest):
        reader = RunStore.open_reader(Settings.local().path)
        return backtest_input(reader.research_publication(source.run_id))
    if isinstance(source, Case):
        return journal_input(db, request, source.case_id)
    if isinstance(source, Fills):
        return fills_input(request, source)
    if isinstance(source, Panel):
        return panel_input(Store(db), source)
    if isinstance(source, EventTest):
        return event_input(Store(db), source)
    if isinstance(source, Search):
        return search_input(request, source)
    return market_input(db, source, source.kind)


@router.post("/tasks", dependencies=writes)
def submit(body: Task, db: Database, request: Request):
    store = Store(db)
    config = body.model_dump(mode="json", exclude={"id"})
    try:
        existing = store.get(body.id)
        if existing is not None:
            if existing["request"] != config:
                raise ResearchError("RESEARCH_REQUEST_ID_CONFLICT")
            return existing
        previous = store.get(body.rerun_of) if body.rerun_of else None
        if body.rerun_of and previous is None:
            raise ResearchError("RESEARCH_RERUN_SOURCE_INVALID")
        frozen = store.frozen_input(previous) if previous and previous["status"] == "SUCCEEDED" else None
        db.rollback()
        payload = frozen if frozen is not None else prepare(request, db, body.source)
        needs_worker = body.source.kind not in ("case", "fills")
        revision = worker_revision() if needs_worker else {}
        fingerprint = input_digest({"payload": payload, "worker_revision": revision, "version": VERSION})
        if previous and frozen is None and fingerprint != previous["input_digest"]:
            raise ResearchError("RESEARCH_ORIGINAL_INPUT_UNAVAILABLE")
        existing = store.claim(body.id, config, fingerprint, body.rerun_of)
        if existing:
            return existing
        try:
            output = compute(payload, lambda: store.active(body.id)) if needs_worker else {}
            if revision and worker_revision() != revision:
                raise ResearchError("RESEARCH_WORKER_IDENTITY_CHANGED")
        except ResearchError as exc:
            return store.terminate(body.id, str(exc))
        try:
            return store.publish(body.id, payload, output, revision)
        except OSError:
            db.rollback()
            return store.terminate(body.id, "RESEARCH_ARTIFACT_WRITE_FAILED")
    except (*EVIDENCE_ERRORS, ValidationError, sqlite3.Error, SQLAlchemyError, OSError) as exc:
        raise fail(exc) from None


@router.post("/tasks/{task_id}/submit-experiment", dependencies=writes, status_code=202)
def submit_experiment(task_id: UUID, db: Database, request: Request):
    try:
        task = verified_task(Store(db), task_id, "search")
        result = task["result"]
        owner = owner_path(request)
        source = RunStore.open_reader(owner).research_publication(result["source"]["run_id"])
        if run_binding(owner, source) != result["source"]["run_binding"]:
            raise ResearchError("RESEARCH_SEARCH_ORIGINAL_RUN_CHANGED")
        delays = result["experiment_plan"]["delays"]
        policy = result["policy"]
        if len(delays) != policy["budget"] or len(set(delays)) != len(delays) or not set(delays) <= set(policy["choices"]):
            raise ResearchError("RESEARCH_SEARCH_PLAN_INVALID")
        key = "statistics-v02:" + digest([str(task_id), task["result_digest"], result["source"]["run_binding"]])
        config = create_request(RunConfig.model_validate(result["base_config"]), delays, policy["folds"], key)
        backtests = get_backtest_store(request)
        if backtests.path != owner:
            raise ResearchError("RESEARCH_BACKTEST_OWNER_CHANGED")
        if backtests.read_only:
            raise ResearchError("RESEARCH_BACKTEST_OWNER_READ_ONLY")
        return create_experiment(backtests, config)
    except (*EVIDENCE_ERRORS, ValidationError, sqlite3.Error, SQLAlchemyError, OSError) as exc:
        raise fail(exc) from None


@router.post("/tasks/{task_id}/cancel", dependencies=writes)
def cancel(task_id: UUID, db: Database):
    try:
        row = Store(db).request_cancel(task_id)
        if row is None:
            raise ResearchError("RESEARCH_TASK_NOT_FOUND")
        return row
    except (ResearchError, SQLAlchemyError, OSError) as exc:
        raise fail(exc) from None
