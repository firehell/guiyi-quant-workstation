"""Versioned receiving handover: only the exclusive new owner freezes the boundary."""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

from app.runtime_handover import _read, _write, runtime_directory


class ReceivingProtocol:
    def __init__(self, path: Path, *, binding: str):
        self.path, self.binding = Path(path), binding

    def read(self):
        value = _read(self.path)
        if value is None:
            return None
        if value.get("schema_version") != 1 or value.get("protocol_version") != 2 or value.get("status") not in {"requested", "active"}:
            raise ValueError("REFERENCE_INBOX_PROTOCOL_INVALID")
        if value.get("binding") != self.binding:
            raise ValueError("REFERENCE_INBOX_BINDING_DRIFT")
        if value['status'] == 'active' and not isinstance(value.get('boundaries'), dict):
            raise ValueError("REFERENCE_INBOX_PROTOCOL_INVALID")
        return value

    def enabled(self):
        state = self.read()
        return bool(state and state["status"] == "active")

    def request(self, *, schema_ready):
        schema_ready()
        if self.read() is not None:
            return
        _write(self.path, {"schema_version": 1, "protocol_version": 2,
                          "status": "requested", "binding": self.binding,
                          "requested_at": datetime.now(UTC).isoformat()})

    def activate(self, journal, *, assert_owned, warmup=False):
        state = self.read()
        if state is None:
            return False
        if state["status"] == "active":
            return True
        if warmup:
            return False
        assert_owned()
        boundaries = {day.isoformat(): {"cursor": journal.cursor("reference", day),
                                       "tail": journal.tail(day)} for day in journal.days()}
        assert_owned()
        _write(self.path, {**state, "status": "active", "boundaries": boundaries,
                          "activated_at": datetime.now(UTC).isoformat()})
        return True

    def block_intake(self, code):
        import re
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", code) is None:
            raise ValueError("REFERENCE_INBOX_PROTOCOL_INVALID")
        state = self.read()
        if not state or state["status"] != "active":
            raise ValueError("REFERENCE_INBOX_PROTOCOL_INVALID")
        if state.get("intake_error") is None:
            _write(self.path, {**state, "intake_error": code,
                "intake_blocked_at": datetime.now(UTC).isoformat()})


def build_receiving_protocol():
    from app.db.session import SessionLocal
    from app.market_data.composition import canonical_root
    from app.market_data.operational_universe import load_operational_products
    # Source-code contract hashes change on an approved release; accepted raw
    # receipts belong to the stable data authority, never to a checkout version.
    with SessionLocal() as session:
        database = session.get_bind().url.render_as_string(hide_password=True)
    identity = {"database_identity": database, "canonical_root": str(canonical_root().resolve()),
                "operational_products": sorted(load_operational_products())}
    binding = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return ReceivingProtocol(runtime_directory()/"reference-receiving-protocol.json", binding=binding)


def require_inbox_schema(session_factory):
    from sqlalchemy import inspect
    with session_factory() as session:
        tables = set(inspect(session.connection()).get_table_names())
        if not {"reference_inbox_inputs", "reference_inbox_deliveries", "reference_inbox_recovery_results"} <= tables:
            raise ValueError("REFERENCE_INBOX_SCHEMA_REQUIRED")


def read_receiving_health(session_factory):
    path = runtime_directory()/"reference-receiving-protocol.json"
    if not path.exists():
        return {"protocol_version": 1, "cursor_semantics": "calculation"}
    protocol = build_receiving_protocol()
    if not protocol.enabled():
        return {"protocol_version": 1, "requested_protocol_version": 2,
                "cursor_semantics": "calculation"}
    from app.reference_trading.inbox import ReferenceInboxRepository
    return {"protocol_version": 2, "cursor_semantics": "durable_acceptance",
            "intake_error": protocol.read().get("intake_error"),
            **ReferenceInboxRepository(session_factory).health()}
