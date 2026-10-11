"""Append-only, account-serialized PostgreSQL storage for explicit local Paper."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any

from sqlalchemy import (
    BigInteger, Column, ForeignKey, JSON, MetaData, String, Table,
    UniqueConstraint, create_engine, inspect, select, text, update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError

from guiyi_quant.paper import (
    apply_command, apply_events, command_to_dict, event_from_dict, event_to_dict,
)


class PaperLedgerError(ValueError):
    """Only fixed public codes; never database statements or credentials."""


_METADATA = MetaData()
_ACCOUNTS = Table("paper_accounts", _METADATA,
    Column("account_id", String(80), primary_key=True),
    Column("sequence", BigInteger, nullable=False),
    Column("event_hash", String(64), nullable=False),
)
_COMMANDS = Table("paper_commands", _METADATA,
    Column("account_id", String(80), ForeignKey("paper_accounts.account_id"), primary_key=True),
    Column("command_id", String(256), primary_key=True),
    Column("command_hash", String(64), nullable=False),
    Column("first_sequence", BigInteger, nullable=False),
    Column("last_sequence", BigInteger, nullable=False),
    Column("event_count", BigInteger, nullable=False),
)
_EVENTS = Table("paper_events", _METADATA,
    Column("account_id", String(80), ForeignKey("paper_accounts.account_id"), primary_key=True),
    Column("sequence", BigInteger, primary_key=True),
    Column("event_id", String(256), nullable=False),
    Column("command_id", String(256), nullable=False),
    Column("previous_hash", String(64), nullable=False),
    Column("event_hash", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("account_id", "event_id"),
)
_ZERO = "0" * 64


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return sha256(_json(value).encode()).hexdigest()


def _account(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", value) is None:
        raise PaperLedgerError("PAPER_ACCOUNT_ID_INVALID")


@dataclass(frozen=True)
class CommandReceipt:
    command_id: str
    first_sequence: int
    last_sequence: int
    event_count: int
    duplicate: bool


class PaperLedger:
    def __init__(self, url: str):
        try:
            parsed = make_url(url)
            valid = (
                parsed.drivername == "postgresql+psycopg"
                and parsed.host in {"127.0.0.1", "localhost", "::1"}
                and parsed.port is not None and parsed.port != 5432
                and re.fullmatch(r"guiyi_paper_[a-z0-9_]{1,45}", parsed.database or "")
                and not parsed.query
            )
        except (ValueError, TypeError, ArgumentError):
            valid = False
        if not valid:
            raise PaperLedgerError("PAPER_DATABASE_SCOPE_INVALID")
        self.engine = create_engine(parsed, pool_pre_ping=True,
                                    connect_args={"options": "-c statement_timeout=60000 -c lock_timeout=10000"})

    def close(self) -> None:
        self.engine.dispose()

    def initialize_schema(self) -> None:
        """Only this dedicated database, explicit CLI init; no normal app startup."""
        with self.engine.begin() as conn:
            if set(inspect(conn).get_table_names()) - set(_METADATA.tables):
                raise PaperLedgerError("PAPER_DATABASE_NOT_DEDICATED")
            _METADATA.create_all(conn)
            # Durable facts cannot be rewritten through ordinary SQL either.
            conn.execute(text("""CREATE OR REPLACE FUNCTION paper_deny_rewrite()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                  RAISE EXCEPTION 'PAPER_LEDGER_IMMUTABLE'; END; $$"""))
            for table in ("paper_events", "paper_commands"):
                exists = conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname=:name AND tgrelid=CAST(:table AS regclass))"),
                                     {"name": table + "_immutable", "table": table})
                if not exists:
                    conn.execute(text(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION paper_deny_rewrite()"))

    @staticmethod
    def _receipt(row, duplicate=True) -> CommandReceipt:
        return CommandReceipt(row["command_id"], row["first_sequence"],
                              row["last_sequence"], row["event_count"], duplicate)

    @staticmethod
    def _load(conn: Connection, account: str, owner):
        state, sequence, previous = None, 0, _ZERO
        commands = {row["command_id"]: row for row in conn.execute(
            select(_COMMANDS).where(_COMMANDS.c.account_id == account)).mappings()}
        seen: dict[str, tuple[int, int, int]] = {}
        rows = conn.execute(select(_EVENTS).where(_EVENTS.c.account_id == account)
                            .order_by(_EVENTS.c.sequence)).mappings()
        for row in rows:
            sequence += 1
            expected = _digest({"account_id": account, "sequence": sequence,
                                "previous_hash": previous, "payload": row["payload"]})
            if (row["sequence"] != sequence or row["previous_hash"] != previous
                    or row["event_hash"] != expected):
                raise PaperLedgerError("PAPER_LEDGER_CORRUPT")
            event = event_from_dict(row["payload"])
            if event.event_id != row["event_id"] or event.command_id != row["command_id"]:
                raise PaperLedgerError("PAPER_LEDGER_CORRUPT")
            receipt = commands.get(event.command_id)
            if receipt is None or receipt["command_hash"] != event.command_hash:
                raise PaperLedgerError("PAPER_LEDGER_CORRUPT")
            first, _, count = seen.get(event.command_id, (sequence, sequence, 0))
            seen[event.command_id] = (first, sequence, count + 1)
            state = apply_events(state, (event,))
            previous = expected
        if set(seen) != set(commands) or any(
            seen[key] != (row["first_sequence"], row["last_sequence"], row["event_count"])
            for key, row in commands.items()
        ):
            raise PaperLedgerError("PAPER_LEDGER_CORRUPT")
        if owner is not None and (owner["sequence"] != sequence or owner["event_hash"] != previous):
            raise PaperLedgerError("PAPER_LEDGER_CORRUPT")
        return state, sequence, previous

    def load(self, account: str):
        _account(account)
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                owner = conn.execute(select(_ACCOUNTS).where(_ACCOUNTS.c.account_id == account)).mappings().one_or_none()
                if owner is None:
                    raise PaperLedgerError("PAPER_ACCOUNT_NOT_FOUND")
                state, sequence, _ = self._load(conn, account, owner)
                return state, sequence

    def verify(self, account: str) -> dict:
        state, sequence = self.load(account)
        return {"verified": True, "sequence": sequence, "cash": str(state.cash),
                "equity": str(state.equity), "halted": state.daily_halt or state.rollover_halt,
                "position_qty": state.position_qty, "position_contract": state.position_contract}

    def lookup(self, account: str, command) -> CommandReceipt | None:
        """Read-only recovery after an unknown commit; never resend a command."""
        _account(account)
        fingerprint = _digest(command_to_dict(command))
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                owner = conn.execute(select(_ACCOUNTS).where(
                    _ACCOUNTS.c.account_id == account)).mappings().one_or_none()
                if owner is not None:
                    self._load(conn, account, owner)
                row = conn.execute(select(_COMMANDS).where(
                    _COMMANDS.c.account_id == account,
                    _COMMANDS.c.command_id == command.command_id)).mappings().one_or_none()
                if row is None:
                    return None
                if row["command_hash"] != fingerprint:
                    raise PaperLedgerError("PAPER_COMMAND_CONFLICT")
                return self._receipt(row)

    def execute(self, account: str, command, *, expected_sequence: int | None = None) -> CommandReceipt:
        return self.execute_many(account, (command,), expected_sequence=expected_sequence)[0]

    def execute_many(self, account: str, commands, *, expected_sequence: int | None = None) -> tuple[CommandReceipt, ...]:
        _account(account)
        commands = tuple(commands)
        if not 1 <= len(commands) <= 2000 or (
            expected_sequence is not None and (type(expected_sequence) is not int or expected_sequence < 0)
        ):
            raise PaperLedgerError("PAPER_BATCH_INVALID")
        receipts = []
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(_ACCOUNTS).values(account_id=account, sequence=0, event_hash=_ZERO)
                             .on_conflict_do_nothing())
                owner = conn.execute(select(_ACCOUNTS).where(_ACCOUNTS.c.account_id == account)
                                     .with_for_update()).mappings().one()
                state, sequence, previous = self._load(conn, account, owner)
                checked_expected = False
                for command in commands:
                    body = command_to_dict(command)
                    fingerprint = _digest(body)
                    old = conn.execute(select(_COMMANDS).where(_COMMANDS.c.account_id == account,
                        _COMMANDS.c.command_id == command.command_id)).mappings().one_or_none()
                    if old is not None:
                        if old["command_hash"] != fingerprint:
                            raise PaperLedgerError("PAPER_COMMAND_CONFLICT")
                        receipts.append(self._receipt(old))
                        continue
                    if not checked_expected:
                        if expected_sequence is not None and sequence != expected_sequence:
                            raise PaperLedgerError("PAPER_SEQUENCE_CONFLICT")
                        checked_expected = True
                    generated = apply_command(state, command)
                    if not generated:
                        raise PaperLedgerError("PAPER_LEDGER_CORRUPT")
                    first = sequence + 1
                    for event in generated:
                        if event.command_id != command.command_id or event.command_hash != fingerprint:
                            raise PaperLedgerError("PAPER_EVENT_COMMAND_MISMATCH")
                        payload = event_to_dict(event)
                        sequence += 1
                        event_hash = _digest({"account_id": account, "sequence": sequence,
                                              "previous_hash": previous, "payload": payload})
                        conn.execute(_EVENTS.insert().values(account_id=account, sequence=sequence,
                            event_id=event.event_id, command_id=event.command_id, previous_hash=previous,
                            event_hash=event_hash, payload=payload))
                        previous = event_hash
                    state = apply_events(state, generated)
                    values = dict(account_id=account, command_id=command.command_id, command_hash=fingerprint,
                                  first_sequence=first, last_sequence=sequence, event_count=len(generated))
                    conn.execute(_COMMANDS.insert().values(**values))
                    receipts.append(self._receipt(values, False))
                conn.execute(update(_ACCOUNTS).where(_ACCOUNTS.c.account_id == account)
                             .values(sequence=sequence, event_hash=previous))
        except DBAPIError as exc:
            # Connectivity can fail during COMMIT. Classify conservatively and
            # let explicit lookup distinguish committed/absent; no automatic retry.
            code = "PAPER_COMMIT_OUTCOME_UNKNOWN" if exc.connection_invalidated else "PAPER_STORAGE_FAILED"
            raise PaperLedgerError(code) from None
        return tuple(receipts)
