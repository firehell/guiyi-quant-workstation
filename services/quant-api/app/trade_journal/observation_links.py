"""Explicit links never rewrite the frozen observation, plan revision or case."""
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .contracts import Input
from .store import JournalError, JournalStore

LinkKind = Literal["plan", "case"]


class ObservationTarget(Input):
    kind: LinkKind
    target_id: UUID
    version: int | None = Field(default=None, ge=1, le=2_147_483_647)

    @model_validator(mode="after")
    def exact_version(self):
        if (self.kind == "plan") != (self.version is not None):
            raise ValueError("计划需要确切版本，案例使用案例 ID")
        return self


def scope(store, observation_id):
    identity = store.one("""
        SELECT snapshot->>'product' AS product, snapshot->>'physical_contract' AS contract
        FROM trade_journal_observations WHERE id=:id
    """, id=observation_id)
    if identity is None:
        raise JournalError("JOURNAL_OBSERVATION_NOT_FOUND", 404)
    return identity


def link_observation(store: JournalStore, observation_id: UUID, target: ObservationTarget):
    identity = scope(store, observation_id)
    plan = target.kind == "plan"
    if plan:
        ref = store.plan_revision(target.target_id, target.version)
        match = ref and ref["product"] in (None, identity["product"])
    else:
        ref = store.one("SELECT contract, product FROM trade_journal_cases WHERE id=:id", id=target.target_id)
        match = ref and ref["contract"] == identity["contract"] and ref["product"] == identity["product"]
    if ref is None:
        raise JournalError("JOURNAL_TARGET_NOT_FOUND", 404)
    if not match:
        raise JournalError("JOURNAL_TARGET_SCOPE_CONFLICT", 409)
    store.execute("""
        INSERT INTO trade_journal_observation_links (observation_id,plan_id,plan_version,case_id)
        VALUES (:id,:plan,:version,:case) ON CONFLICT DO NOTHING
    """, id=observation_id, plan=target.target_id if plan else None, case=None if plan else target.target_id, version=target.version)
    return {"id": observation_id, **target.model_dump(mode="json")}


def observation_candidates(store, observation_id, kind, query, offset):
    identity = scope(store, observation_id)
    if kind == "case":
        rows = store.many("""
            SELECT id AS target_id, NULL::integer AS version, title, trading_day, contract AS scope
            FROM trade_journal_cases WHERE contract=:contract AND product=:product
                AND (strpos(lower(title),lower(:q))>0 OR CAST(id AS text)=:q)
            ORDER BY trading_day DESC, id LIMIT 31 OFFSET :offset
        """, **identity, q=query, offset=offset)
    else:
        rows = store.many("""
            SELECT p.id AS target_id, r.version, r.content->>'title' AS title, p.trading_day, p.product AS scope
            FROM trade_journal_plans p JOIN trade_journal_plan_revisions r ON r.plan_id=p.id
            WHERE (p.product IS NULL OR p.product=:product)
                AND (strpos(lower(r.content->>'title'),lower(:q))>0 OR CAST(p.id AS text)=:q)
            ORDER BY p.trading_day DESC, p.id, r.version DESC LIMIT 31 OFFSET :offset
        """, product=identity["product"], q=query, offset=offset)
    return {"items": rows[:30], "next_offset": offset+30 if len(rows)>30 else None}


def observation_links(store, observation_id, offset):
    scope(store, observation_id)
    rows = store.many("""
        SELECT coalesce(l.plan_id,l.case_id) AS target_id, l.plan_version AS version,
            CASE WHEN l.plan_id IS NULL THEN 'case' ELSE 'plan' END AS kind,
            coalesce(c.title,r.content->>'title') AS title, coalesce(c.trading_day,p.trading_day) AS trading_day,
            coalesce(c.contract,p.product) AS scope, r.content AS plan, l.linked_at
        FROM trade_journal_observation_links l
        LEFT JOIN trade_journal_cases c ON c.id=l.case_id
        LEFT JOIN trade_journal_plans p ON p.id=l.plan_id
        LEFT JOIN trade_journal_plan_revisions r ON r.plan_id=l.plan_id AND r.version=l.plan_version
        WHERE observation_id=:id ORDER BY linked_at DESC, target_id, version LIMIT 31 OFFSET :offset
    """, id=observation_id, offset=offset)
    return {"items": rows[:30], "next_offset": offset+30 if len(rows)>30 else None}


def linked_observations(store, target, offset):
    rows = store.many("""
        SELECT o.id, o.trading_day, o.snapshot->>'physical_contract' AS contract, left(o.note,180) AS note
        FROM trade_journal_observation_links l JOIN trade_journal_observations o ON o.id=l.observation_id
        WHERE (:kind='case' AND l.case_id=:target)
           OR (:kind='plan' AND l.plan_id=:target AND l.plan_version=:version)
        ORDER BY o.trading_day DESC, o.recorded_at DESC, o.id LIMIT 31 OFFSET :offset
    """, kind=target.kind, target=target.target_id, version=target.version, offset=offset)
    return {"items": rows[:30], "next_offset": offset+30 if len(rows)>30 else None}
