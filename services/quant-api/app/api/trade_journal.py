"""API for the workstation's personal plans, execution notes and reviews."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
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
from app.trade_journal.observation_links import (
    LinkKind, ObservationTarget, link_observation, linked_observations, observation_candidates, observation_links,
)
from app.trade_journal.observations import (
    BODY_LIMIT, decode_capture, get_observation, list_observations, write_observation,
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


async def observation_body(request: Request):
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, detail={"code": "JOURNAL_OBSERVATION_CONTENT_TYPE"})
    size = request.headers.get("content-length")
    if size is not None and (not size.isascii() or not size.isdecimal() or len(size) > 10 or int(size) > BODY_LIMIT):
        raise HTTPException(413, detail={"code": "JOURNAL_OBSERVATION_TOO_LARGE"})
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > BODY_LIMIT:
            raise HTTPException(413, detail={"code": "JOURNAL_OBSERVATION_TOO_LARGE"})
        body.extend(chunk)
    return body


@router.put("/observations/{observation_id}", dependencies=writes)
def save_observation(observation_id: UUID, db: Database, key: Key, body=Depends(observation_body)):
    def write():
        capture, image = decode_capture(body)
        return write_observation(JournalStore(db), observation_id, key, capture, image)
    return run(write)


@router.get("/observations")
def observations(db: Database, anchor: date, period: Period = "day", offset: Annotated[int, Query(ge=0)] = 0):
    def read():
        validate_anchor(period, anchor)
        with readonly_transaction(db, timeout_seconds=5):
            return list_observations(JournalStore(db), period, anchor, offset)
    return run(read)


@router.get("/observations/{observation_id}")
def observation_detail(observation_id: UUID, db: Database):
    def read():
        with readonly_transaction(db, timeout_seconds=5):
            return {"observation": get_observation(JournalStore(db), observation_id)}
    return run(read)


@router.get("/observations/{observation_id}/image")
def observation_image(observation_id: UUID, db: Database):
    def read():
        with readonly_transaction(db, timeout_seconds=5):
            return get_observation(JournalStore(db), observation_id, image=True)
    return Response(bytes(run(read)["png"]), media_type="image/png",
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/observations/{observation_id}/link-candidates")
def find_observation_targets(observation_id: UUID, kind: LinkKind, db: Database,
                             q: Annotated[str, Query(max_length=160)] = "", offset: Annotated[int, Query(ge=0)] = 0):
    def read():
        with readonly_transaction(db, timeout_seconds=5):
            return observation_candidates(JournalStore(db), observation_id, kind, q.strip(), offset)
    return run(read)


@router.get("/observations/{observation_id}/links")
def read_observation_links(observation_id: UUID, db: Database, offset: Annotated[int, Query(ge=0)] = 0):
    def read():
        with readonly_transaction(db, timeout_seconds=5):
            return observation_links(JournalStore(db), observation_id, offset)
    return run(read)


@router.put("/observations/{observation_id}/links", dependencies=writes)
def add_observation_link(observation_id: UUID, target: ObservationTarget, key: Key, db: Database):
    store = JournalStore(db)
    return run(lambda: store.mutate(key, f"observation-link:{observation_id}", target,
                                    lambda: link_observation(store, observation_id, target)))


@router.get("/observation-links")
def read_target_observations(kind: LinkKind, target_id: UUID, db: Database,
                             version: Annotated[int, Query(ge=1, le=2_147_483_647)] | None = None,
                             offset: Annotated[int, Query(ge=0)] = 0):
    def read():
        if (kind == "plan") != (version is not None):
            raise JournalError("JOURNAL_TARGET_VERSION_INVALID", 422)
        with readonly_transaction(db, timeout_seconds=5):
            target = ObservationTarget(kind=kind, target_id=target_id, version=version)
            return linked_observations(JournalStore(db), target, offset)
    return run(read)
