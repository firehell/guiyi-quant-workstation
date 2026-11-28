"""API for the workstation's personal plans, execution notes and reviews."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.local_write import require_workstation_origin
from app.db.readonly import readonly_transaction
from app.db.session import get_db
from app.trade_journal import TRADE_JOURNAL_CENTER_VERSION
from app.trade_journal.contracts import (
    CaseCreate, CaseUpdate, Contract, EventRemoval, Identity, Link, ManualEvent, Period, Plan,
    Product, Source, Summary, Tag,
)
from app.trade_journal.sources import read_evidence, resolve
from app.trade_journal.store import JournalError, JournalStore

router = APIRouter(prefix="/api/v1/trade-journal", tags=["trade-journal-center"])
Database = Annotated[Session, Depends(get_db)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def ensure_local_origin(request: Request):
    require_workstation_origin(request, "JOURNAL_ORIGIN_FORBIDDEN")


writes = [Depends(ensure_local_origin)]


def run(operation):
    try:
        return {"component_version": TRADE_JOURNAL_CENTER_VERSION, **operation()}
    except JournalError as exc:
        raise HTTPException(exc.status, detail={"code": str(exc)}) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "JOURNAL_STORAGE_UNAVAILABLE"}) from None


def validate_anchor(period: Period, anchor: date):
    if period == "week" and anchor.weekday() != 0:
        raise JournalError("JOURNAL_WEEK_ANCHOR_MUST_BE_MONDAY", 422)


@router.get("")
def overview(db: Database, anchor: date, period: Period = "day", product: Product | None = None,
             source: Source | Literal["MANUAL"] | None = None, tag: Tag | None = None,
             offset: Annotated[int, Query(ge=0)] = 0):
    def read():
        validate_anchor(period, anchor)
        with readonly_transaction(db, timeout_seconds=5):
            return JournalStore(db).overview(period, anchor, product, source, tag, offset)
    return run(read)


@router.put("/plans/{plan_id}", dependencies=writes)
def save_plan(plan_id: UUID, data: Plan, db: Database, key: Key):
    store = JournalStore(db)
    return run(lambda: store.mutate(key, f"plan:{plan_id}", data, lambda: store.save_plan(plan_id, data)))


@router.put("/cases/{case_id}/create", dependencies=writes)
def create_case(case_id: UUID, data: CaseCreate, db: Database, key: Key):
    store = JournalStore(db)
    return run(lambda: store.mutate(key, f"create:{case_id}", data, lambda: store.create_case(case_id, data)))


@router.put("/cases/{case_id}", dependencies=writes)
def update_case(case_id: UUID, data: CaseUpdate, db: Database, key: Key):
    store = JournalStore(db)
    return run(lambda: store.mutate(key, f"case:{case_id}", data, lambda: store.update_case(case_id, data)))


def project_timeline(request: Request, events, contract):
    evidence = {}
    timeline = []
    for event in events:
        projection = dict(event)
        if event["source"] and not event["removed_at"]:
            source, scope, day = event["source"], event["scope"], event["trading_day"]
            group = (source, scope, day)
            if group not in evidence:
                evidence[group] = read_evidence(request, source, day, scope, contract=contract)
            result = evidence[group]
            matches = [item for item in result["items"] if item["native_id"] == event["native_id"]]
            if not matches and result["has_more"]:
                result = read_evidence(request, source, day, scope, contract=contract, native_id=event["native_id"])
                matches = result["items"]
            if len(matches) == 1 and result["scope"] == scope:
                item = matches[0]
                status = "AVAILABLE" if item["native_id"] == event["native_id"] else "NO_EVIDENCE"
                projection["evidence"] = item if status == "AVAILABLE" else None
                projection["evidence_status"] = status
            else:
                projection["evidence_status"] = (
                    "NO_EVIDENCE" if result["status"] in ("AVAILABLE", "VERIFIED_EMPTY") else result["status"]
                )
        timeline.append(projection)
    return timeline


@router.get("/cases/{case_id}")
def case_detail(request: Request, case_id: UUID, db: Database):
    def read():
        store = JournalStore(db)
        with readonly_transaction(db, timeout_seconds=5):
            case = store.case(case_id)
            plan = store.plan_revision(case["plan_id"], case["plan_version"]) if case["plan_id"] else None
            events = store.timeline(case_id)
        return {"case": case, "plan": plan, "timeline": project_timeline(request, events, case["contract"])}
    return run(read)


@router.put("/cases/{case_id}/events/{event_id}", dependencies=writes)
def add_manual(case_id: UUID, event_id: UUID, data: ManualEvent, db: Database, key: Key):
    store = JournalStore(db)
    return run(lambda: store.mutate(key, f"manual:{case_id}:{event_id}", data,
                                    lambda: store.add_manual(case_id, event_id, data)))


@router.put("/cases/{case_id}/links/{event_id}", dependencies=writes)
def add_link(request: Request, case_id: UUID, event_id: UUID, data: Link, db: Database, key: Key):
    store = JournalStore(db)

    def write():
        case = store.case(case_id)
        evidence = resolve(request, data, case["contract"])
        return store.add_link(case_id, event_id, data, evidence)

    return run(lambda: store.mutate(key, f"link:{case_id}:{event_id}", data, write))


@router.put("/cases/{case_id}/events/{event_id}/removal", dependencies=writes)
def remove_event(case_id: UUID, event_id: UUID, data: EventRemoval, db: Database, key: Key):
    store = JournalStore(db)
    return run(lambda: store.mutate(key, f"remove:{case_id}:{event_id}", data,
                                    lambda: store.remove_event(case_id, event_id, data)))


@router.get("/evidence")
def evidence(request: Request, source: Source, trading_day: date, scope: Identity | None = None,
             contract: Contract | None = None, native_id: Identity | None = None):
    return run(lambda: read_evidence(request, source, trading_day, scope, contract=contract, native_id=native_id))


@router.put("/summaries/{period}/{anchor}", dependencies=writes)
def save_summary(period: Period, anchor: date, data: Summary, db: Database, key: Key):
    store = JournalStore(db)

    def write():
        validate_anchor(period, anchor)
        return store.mutate(key, f"summary:{period}:{anchor}", data, lambda: store.save_summary(period, anchor, data))

    return run(write)
