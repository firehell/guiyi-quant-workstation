"""Transactional persistence for user-authored records and source identities."""

from datetime import date, timedelta
from hashlib import sha256
import json
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from .contracts import EXECUTION_SOURCES, OPENING_ACTIONS, CaseCreate, CaseUpdate, EventRemoval, Link, ManualEvent, Plan, Summary


_CASES_IN_PERIOD = '''
    (c.trading_day BETWEEN :anchor AND :end OR EXISTS (
        SELECT 1 FROM trade_journal_events activity
        WHERE activity.case_id=c.id AND activity.removed_at IS NULL
            AND activity.kind <> 'COMPARISON' AND activity.trading_day BETWEEN :anchor AND :end
    ))
'''


class JournalError(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.status = status


def encode(value) -> str:
    return json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":"))


class JournalStore:
    def __init__(self, db: Session):
        self.db = db

    def execute(self, sql, **values):
        return self.db.execute(text(sql), values)

    def one(self, sql, **values):
        row = self.execute(sql, **values).mappings().one_or_none()
        return dict(row) if row is not None else None

    def many(self, sql, **values):
        return [dict(row) for row in self.execute(sql, **values).mappings()]

    def mutate(self, key: UUID, action: str, payload, write):
        fingerprint = sha256(encode([action, payload]).encode()).hexdigest()
        claimed = self.one("""
            INSERT INTO trade_journal_mutations (id, fingerprint) VALUES (:key, :fingerprint)
            ON CONFLICT DO NOTHING RETURNING id
        """, key=key, fingerprint=fingerprint)
        if not claimed:
            previous = self.one("SELECT fingerprint, result FROM trade_journal_mutations WHERE id=:key", key=key)
            if previous is None or previous["fingerprint"] != fingerprint:
                raise JournalError("JOURNAL_REQUEST_CONFLICT")
            return previous["result"]
        result = jsonable_encoder(write())
        self.execute("""
            UPDATE trade_journal_mutations SET result=CAST(:result AS jsonb) WHERE id=:key
        """, key=key, result=encode(result))
        self.db.commit()
        return result

    def save_plan(self, plan_id: UUID, plan: Plan):
        version = plan.expected_version + 1
        where = dict(id=plan_id, trading_day=plan.trading_day, product=plan.product)
        if plan.expected_version == 0:
            row = self.one("""
                INSERT INTO trade_journal_plans (id, trading_day, product, version)
                VALUES (:id, :trading_day, :product, 1) ON CONFLICT DO NOTHING RETURNING id
            """, **where)
        else:
            row = self.one("""
                UPDATE trade_journal_plans SET version=:version
                WHERE id=:id AND trading_day=:trading_day AND product IS NOT DISTINCT FROM CAST(:product AS text)
                    AND version=:previous
                RETURNING id
            """, **where, version=version, previous=plan.expected_version)
        if not row:
            raise JournalError("JOURNAL_PLAN_VERSION_CONFLICT")

        self.execute("""
            INSERT INTO trade_journal_plan_revisions (plan_id, version, content)
            VALUES (:id, :version, CAST(:content AS jsonb))
        """, id=plan_id, version=version, content=encode(plan.model_dump(exclude={"expected_version"}, mode="json")))
        return {"id": plan_id, "version": version}

    def plan_revision(self, plan_id: UUID, version: int):
        return self.one("""
            SELECT p.id, p.trading_day, p.product, r.version, r.content, r.recorded_at
            FROM trade_journal_plans p JOIN trade_journal_plan_revisions r ON r.plan_id=p.id
            WHERE p.id=:id AND r.version=:version
        """, id=plan_id, version=version)

    def create_case(self, case_id: UUID, case: CaseCreate):
        if case.plan_id is not None:
            plan = self.plan_revision(case.plan_id, case.plan_version)
            if plan is None or plan["trading_day"] != case.trading_day or plan["product"] not in (None, case.product):
                raise JournalError("JOURNAL_PLAN_SCOPE_CONFLICT")

        row = self.one("""
            INSERT INTO trade_journal_cases (id, trading_day, product, contract, direction, title, plan_id, plan_version)
            VALUES (:id, :trading_day, :product, :contract, :direction, :title, :plan_id, :plan_version)
            ON CONFLICT DO NOTHING RETURNING id, version
        """, id=case_id, **case.model_dump())
        if not row:
            raise JournalError("JOURNAL_CASE_EXISTS")
        return row

    def case(self, case_id: UUID):
        row = self.one("SELECT * FROM trade_journal_cases WHERE id=:id", id=case_id)
        if row is None:
            raise JournalError("JOURNAL_CASE_NOT_FOUND", 404)
        return row

    def update_case(self, case_id: UUID, case: CaseUpdate):
        tags = sorted({tag for item in case.review.dimensions.values() for tag in item.tags}) if case.review else []
        row = self.one("""
            UPDATE trade_journal_cases
            SET version=version+1, title=:title, closed=:closed, review=CAST(:review AS jsonb), tags=:tags
            WHERE id=:id AND version=:previous RETURNING id, version
        """, id=case_id, title=case.title, closed=case.closed, previous=case.expected_version, tags=tags,
            review=encode(case.review) if case.review else None)
        if not row:
            self.case(case_id)
            raise JournalError("JOURNAL_CASE_VERSION_CONFLICT")
        return row

    def timeline(self, case_id: UUID):
        return self.many("""
            SELECT * FROM trade_journal_events
            WHERE case_id=:case_id ORDER BY occurred_at, recorded_at, id
        """, case_id=case_id)

    def add_manual(self, case_id: UUID, event_id: UUID, event: ManualEvent):
        case = self.case(case_id)
        if event.trading_day < case["trading_day"]:
            raise JournalError("JOURNAL_EVENT_BEFORE_CASE")
        row = self.one("""
            INSERT INTO trade_journal_events (id, case_id, kind, trading_day, occurred_at, manual)
            VALUES (:id, :case_id, :kind, :day, :at, CAST(:manual AS jsonb))
            ON CONFLICT DO NOTHING RETURNING id
        """, id=event_id, case_id=case_id, kind=event.kind, day=event.trading_day, at=event.occurred_at,
            manual=encode(event.model_dump(exclude={"kind", "trading_day", "occurred_at"}, mode="json")))
        if not row:
            raise JournalError("JOURNAL_EVENT_EXISTS")
        return row

    def add_link(self, case_id: UUID, event_id: UUID, link: Link, evidence: dict):
        # Serializes ownership changes within a case. The partial unique index arbitrates across cases.
        self.execute("SELECT id FROM trade_journal_cases WHERE id=:id FOR UPDATE", id=case_id)
        case = self.case(case_id)
        execution = link.source in EXECUTION_SOURCES
        if execution and (
            evidence["contract"] != case["contract"] or evidence["direction"] != case["direction"]
            or link.trading_day < case["trading_day"]
        ):
            raise JournalError("JOURNAL_FILL_SCOPE_CONFLICT")
        if execution:
            owner = self.one("""
                SELECT source, scope FROM trade_journal_events
                WHERE case_id=:id AND kind='FILL' AND removed_at IS NULL LIMIT 1
            """, id=case_id)
            if owner and (owner["source"], owner["scope"]) != (link.source, link.scope):
                raise JournalError("JOURNAL_FILL_ACCOUNT_CONFLICT")
        if link.replaces_manual:
            manual = self.one("""
                SELECT kind, trading_day FROM trade_journal_events
                WHERE id=:id AND case_id=:case_id AND manual IS NOT NULL AND removed_at IS NULL
            """, id=link.replaces_manual, case_id=case_id)
            if (
                not execution or not manual or manual["kind"] == "NOTE" or manual["trading_day"] != link.trading_day
                or (manual["kind"] in OPENING_ACTIONS) != (evidence["action"] in OPENING_ACTIONS)
            ):
                raise JournalError("JOURNAL_MANUAL_LINK_CONFLICT")
        row = self.one("""
            INSERT INTO trade_journal_events
                (id, case_id, kind, occurred_at, trading_day, source, scope, native_id, replaces_manual)
            VALUES (:id, :case_id, :kind, :at, :day, :source, :scope, :native_id, :replaces_manual)
            ON CONFLICT DO NOTHING RETURNING id
        """, id=event_id, case_id=case_id, kind="FILL" if execution else "COMPARISON", at=evidence["occurred_at"],
            day=link.trading_day, source=link.source, scope=link.scope, native_id=link.native_id,
            replaces_manual=link.replaces_manual)
        if not row:
            raise JournalError("JOURNAL_EVIDENCE_ALREADY_LINKED")
        return row

    def remove_event(self, case_id: UUID, event_id: UUID, removal: EventRemoval):
        self.execute("SELECT id FROM trade_journal_cases WHERE id=:id FOR UPDATE", id=case_id)
        linked = self.one("""
            SELECT id FROM trade_journal_events WHERE replaces_manual=:id AND removed_at IS NULL
        """, id=event_id)
        if linked:
            raise JournalError("JOURNAL_MANUAL_HAS_EVIDENCE")
        row = self.one("""
            UPDATE trade_journal_events SET removed_at=clock_timestamp(), removal_reason=:reason
            WHERE id=:id AND case_id=:case_id AND removed_at IS NULL RETURNING id
        """, id=event_id, case_id=case_id, reason=removal.reason)
        if not row:
            raise JournalError("JOURNAL_EVENT_NOT_ACTIVE", 404)
        return row

    def overview(self, period, anchor, product, source, tag, offset):
        end = anchor + timedelta(days=6) if period == "week" else anchor
        plans = self.many("""
            SELECT p.id, p.trading_day, p.product, p.version, r.content
            FROM trade_journal_plans p JOIN trade_journal_plan_revisions r
                ON r.plan_id=p.id AND r.version=p.version
            WHERE p.trading_day BETWEEN :anchor AND :end
                AND (CAST(:product AS text) IS NULL OR p.product IS NULL OR p.product=:product)
            ORDER BY p.trading_day, p.product NULLS FIRST, p.id
        """, anchor=anchor, end=end, product=product)
        cases = self.many(f"""
            SELECT c.id, c.title, c.trading_day, c.product, c.contract, c.direction,
                c.closed, c.review IS NOT NULL AS reviewed, c.tags
            FROM trade_journal_cases c
            WHERE {_CASES_IN_PERIOD}
                AND (CAST(:product AS text) IS NULL OR c.product=:product)
                AND (CAST(:tag AS text) IS NULL OR :tag=ANY(c.tags))
                AND (
                    CAST(:source AS text) IS NULL
                    OR (:source='MANUAL' AND NOT EXISTS (
                        SELECT 1 FROM trade_journal_events e
                        WHERE e.case_id=c.id AND e.kind='FILL' AND e.removed_at IS NULL
                    ))
                    OR EXISTS (
                        SELECT 1 FROM trade_journal_events e
                        WHERE e.case_id=c.id AND e.source=:source AND e.removed_at IS NULL
                    )
                )
            ORDER BY c.trading_day DESC, c.recorded_at DESC, c.id LIMIT 51 OFFSET :offset
        """, anchor=anchor, end=end, product=product, source=source, tag=tag, offset=offset)
        return {"plans": plans, "cases": cases[:50], "next_offset": offset + 50 if len(cases) > 50 else None,
                "summary": self.one("SELECT * FROM trade_journal_summaries WHERE period=:period AND anchor=:anchor",
                                    period=period, anchor=anchor)}

    def save_summary(self, period: str, anchor: date, summary: Summary):
        end = anchor + timedelta(days=6) if period == "week" else anchor
        case_ids = set(summary.case_ids)
        if case_ids:
            admitted = self.many(f"""
                SELECT c.id FROM trade_journal_cases c WHERE c.id=ANY(:ids) AND {_CASES_IN_PERIOD}
            """, ids=list(case_ids), anchor=anchor, end=end)
            if len(admitted) != len(case_ids):
                raise JournalError("JOURNAL_SUMMARY_CASE_OUTSIDE_PERIOD")

        content = summary.model_dump(exclude={"expected_version"}, mode="json")
        content["case_ids"] = list(dict.fromkeys(content["case_ids"]))
        params = dict(period=period, anchor=anchor, content=encode(content))
        if summary.expected_version == 0:
            row = self.one("""
                INSERT INTO trade_journal_summaries (period, anchor, version, content)
                VALUES (:period, :anchor, 1, CAST(:content AS jsonb))
                ON CONFLICT DO NOTHING RETURNING version
            """, **params)
        else:
            row = self.one("""
                UPDATE trade_journal_summaries SET version=version+1, content=CAST(:content AS jsonb),
                    updated_at=clock_timestamp()
                WHERE period=:period AND anchor=:anchor AND version=:expected_version RETURNING version
            """, **params, expected_version=summary.expected_version)
        if not row:
            raise JournalError("JOURNAL_SUMMARY_VERSION_CONFLICT")
        return row
