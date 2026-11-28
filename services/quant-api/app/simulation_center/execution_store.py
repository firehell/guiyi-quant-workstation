"""Transactional, replayable storage for offline HTDY execution rehearsal."""

from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from threading import RLock

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from guiyi_quant import htdy_account_execution as account
from guiyi_quant import htdy_execution as strategy
from guiyi_quant.htdy_account_execution import codec

COMMAND_TYPES = {
    strategy.Owner, strategy.Signal, strategy.Fill, account.NativeFill,
    account.Tick, account.ManagedTickV1, account.ContinuousTradeTickV1,
    account.OrderUpdate, account.Readback, account.Disconnect, account.Recover,
    account.ProductRecoveryV1,
}
REHEARSAL_SOURCE = "OFFLINE_CTP_REHEARSAL"


class ExecutionStoreError(ValueError):
    """Fixed offline journal diagnostic."""


class ExecutionStore:
    """Use one dedicated connection per caller and commit before returning effects."""

    def __init__(self, connection, run_id: str):
        if type(run_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
            raise ExecutionStoreError("OFFLINE_RUN_ID_INVALID")
        self.connection = connection
        self.run_id = run_id
        self.account_id = f"offline:{run_id}"
        self._mutex = RLock()

    def _verify_scope(self, state: account.State) -> None:
        if type(state) is not account.State or state.account_id != self.account_id:
            raise ExecutionStoreError("OFFLINE_ACCOUNT_IDENTITY_MISMATCH")

    @contextmanager
    def _write(self):
        with self._mutex:
            if self.connection.info.transaction_status != TransactionStatus.IDLE:
                raise ExecutionStoreError("OFFLINE_TRANSACTION_ALREADY_ACTIVE")
            with self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
                yield cur

    def _run(self, cur, *, lock: bool = False) -> dict:
        query = "SELECT genesis, binding_hash, projection, sequence FROM guiyi_simulation.execution_runs WHERE run_id = %s"
        row = cur.execute(query + (" FOR UPDATE" if lock else ""), (self.run_id,)).fetchone()
        if row is None:
            raise ExecutionStoreError("OFFLINE_RUN_NOT_FOUND")
        return row

    def _state(self, checkpoint: str) -> account.State:
        state = codec.load(checkpoint)
        self._verify_scope(state)
        return state

    def _tip(self, cur, row: dict) -> account.State:
        state = self._state(row["projection"])
        if row["sequence"] == 0:
            matches = row["genesis"] == row["projection"]
        else:
            step = cur.execute("""SELECT state_hash FROM guiyi_simulation.execution_steps
                                  WHERE run_id = %s AND sequence = %s""",
                               (self.run_id, row["sequence"])).fetchone()
            matches = step is not None and step["state_hash"] == codec.digest(state)
        if not matches:
            raise ExecutionStoreError("OFFLINE_PROJECTION_REPLAY_MISMATCH")
        return state

    def create(self, initial: account.State, *, binding_hash: str | None = None) -> None:
        self._verify_scope(initial)
        genesis = codec.checkpoint(initial)
        with self._write() as cur:
            cur.execute(
                """INSERT INTO guiyi_simulation.execution_runs (run_id, genesis, projection, binding_hash)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""", (self.run_id, genesis, genesis, binding_hash))
            prior = self._run(cur)
            if prior["genesis"] != genesis or prior["binding_hash"] != binding_hash:
                raise ExecutionStoreError("OFFLINE_GENESIS_CONFLICT")

    def verify_binding(self, binding_hash: str) -> None:
        with self._mutex, self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
            if self._run(cur)["binding_hash"] != binding_hash:
                raise ExecutionStoreError("OFFLINE_BINDING_HASH_MISMATCH")

    def current(self) -> account.State:
        with self._mutex, self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
            return self._tip(cur, self._run(cur))

    def _apply(self, state: account.State, command_id: str, command: object) -> account.Transition:
        if type(command) not in COMMAND_TYPES:
            raise ExecutionStoreError("OFFLINE_COMMAND_TYPE_INVALID")
        transition = account.apply(state, command_id, command)
        self._verify_scope(transition.state)
        return transition

    def transact(
        self, build: Callable[[account.State], Iterable[tuple[str, object]]],
        *, evidence: tuple[str, dict] | None = None,
    ) -> tuple[account.Effect, ...]:
        effects = []
        with self._write() as cur:
            row = self._run(cur, lock=True)
            state = self._tip(cur, row)
            sequence = row["sequence"]
            for command_id, command in build(state):
                transition = self._apply(state, command_id, command)
                if transition.state is state:
                    continue
                state = transition.state
                sequence += 1
                proof = evidence[1] if evidence and command_id == evidence[0] else None
                cur.execute(
                    """INSERT INTO guiyi_simulation.execution_steps
                       (run_id, sequence, command_id, command, command_hash, state_hash, effects, evidence, evidence_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.run_id, sequence, command_id, Jsonb(codec.encode(command)), codec.digest(command),
                     codec.digest(state), Jsonb(codec.encode(transition.effects)),
                     Jsonb(proof) if proof is not None else None, codec.digest(proof) if proof is not None else None))
                effects.extend(transition.effects)
            if sequence != row["sequence"]:
                cur.execute("""UPDATE guiyi_simulation.execution_runs SET projection = %s, sequence = %s
                               WHERE run_id = %s""", (codec.checkpoint(state), sequence, self.run_id))
        return tuple(effects)

    @staticmethod
    def _qualify_claim(state: account.State, order_id: str, kind: str, payload: dict) -> None:
        order = next((one for one in state.orders if one.order_id == order_id), None)
        if order is None or order.reconciled or not state.readback_valid:
            raise ExecutionStoreError("OFFLINE_CLAIM_NOT_QUALIFIED")
        if kind == "SUBMIT" and (state.phase != "READY" or order.status != "PROPOSED"):
            raise ExecutionStoreError("OFFLINE_CLAIM_NOT_QUALIFIED")
        if kind == "CANCEL" and (order.status != "CANCEL_PENDING" or not order.cancel_sent):
            raise ExecutionStoreError("OFFLINE_CLAIM_NOT_QUALIFIED")
        try:
            claimed_at = datetime.fromisoformat(payload["claimed_at"])
            amount = Decimal(payload["price"])
            if (payload["state_hash"] != codec.digest(state) or payload["proof"] != state.readback.source_id
                    or not state.readback.at <= claimed_at < state.readback.valid_until
                    or claimed_at < state.clock):
                raise ExecutionStoreError("OFFLINE_CLAIM_PROOF_STALE")
            if (payload["quantity"] != order.quantity or amount != order.price
                    or payload["direction"] != ("LONG" if order.side == "BUY" else "SHORT")
                    or payload["offset"] not in ({"OPEN"} if order.offset == "OPEN" else
                                                  {"CLOSE", "CLOSETODAY", "CLOSEYESTERDAY"})):
                raise ExecutionStoreError("OFFLINE_CLAIM_ORDER_FACTS_CONFLICT")
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise ExecutionStoreError("OFFLINE_CLAIM_PAYLOAD_INVALID") from exc

    @staticmethod
    def _payload_hash(order_id: str, payload: dict) -> str:
        if (type(order_id) is not str or not order_id or type(payload) is not dict or payload.get("order_id") != order_id
                or payload.get("source") != REHEARSAL_SOURCE or type(payload.get("native_id")) is not str
                or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}:[A-Z]+:[0-9]+:-?[0-9]+:[0-9]{1,12}", payload["native_id"])
                or payload["native_id"].split(":")[1] != payload.get("exchange")
                or not re.fullmatch(r"[A-Z]{1,3}[0-9]{3,4}", str(payload.get("contract", "")))):
            raise ExecutionStoreError("OFFLINE_CLAIM_PAYLOAD_INVALID")
        try:
            return codec.digest(payload)
        except (TypeError, ValueError):
            raise ExecutionStoreError("OFFLINE_CLAIM_PAYLOAD_INVALID") from None

    def _origin(self, cur, order_id: str, kind: str):
        rows = cur.execute(
            """SELECT step.sequence, step.command, step.command_hash FROM guiyi_simulation.execution_steps step
               WHERE step.run_id = %s AND EXISTS (
                   SELECT FROM jsonb_array_elements(step.effects) effect
                   WHERE effect #>> '{fields,kind}' = %s
                     AND effect #>> '{fields,order,fields,order_id}' = %s
               ) LIMIT 2""", (self.run_id, kind, order_id)).fetchall()
        if len(rows) != 1:
            raise ExecutionStoreError("OFFLINE_CLAIM_EFFECT_MISSING")
        return rows[0]

    def origin_command(self, order_id: str, kind: str):
        with self._mutex, self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
            row = self._origin(cur, order_id, kind)
            command = codec.decode(row["command"])
            if codec.digest(command) != row["command_hash"]:
                raise ExecutionStoreError("OFFLINE_ORIGIN_HASH_MISMATCH")
            return command

    def claim(self, order_id: str, kind: str, payload: dict) -> bool:
        if kind not in {"SUBMIT", "CANCEL"}:
            raise ExecutionStoreError("OFFLINE_CLAIM_KIND_INVALID")
        payload_hash = self._payload_hash(order_id, payload)
        with self._write() as cur:
            run = self._run(cur, lock=True)
            known = cur.execute(
                """SELECT payload, payload_hash FROM guiyi_simulation.execution_claims
                   WHERE run_id = %s AND order_id = %s AND kind = %s""", (self.run_id, order_id, kind)).fetchone()
            if known:
                if known["payload_hash"] != payload_hash or self._payload_hash(order_id, known["payload"]) != payload_hash:
                    raise ExecutionStoreError("OFFLINE_CLAIM_IDENTITY_CONFLICT")
                return False
            origin = self._origin(cur, order_id, kind)
            self._qualify_claim(self._tip(cur, run), order_id, kind, payload)
            cur.execute(
                """INSERT INTO guiyi_simulation.execution_claims
                   (run_id, order_id, kind, effect_sequence, claimed_sequence, payload, payload_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (self.run_id, order_id, kind, origin["sequence"], run["sequence"], Jsonb(payload), payload_hash))
        return True

    def evidence(self, command_id: str) -> dict | None:
        with self._mutex, self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
            row = cur.execute("""SELECT evidence, evidence_hash FROM guiyi_simulation.execution_steps
                                 WHERE run_id = %s AND command_id = %s""", (self.run_id, command_id)).fetchone()
            if row and row["evidence"] is not None:
                if codec.digest(row["evidence"]) != row["evidence_hash"]:
                    raise ExecutionStoreError("OFFLINE_EVIDENCE_HASH_MISMATCH")
                return row["evidence"]
            return None

    def _claims(self, cur, through: int) -> list[dict]:
        return cur.execute(
            """SELECT order_id, kind, effect_sequence, claimed_sequence, payload, payload_hash
               FROM guiyi_simulation.execution_claims WHERE run_id = %s AND claimed_sequence <= %s
               ORDER BY claimed_sequence, order_id, kind""", (self.run_id, through)).fetchall()

    def claims(self) -> dict[tuple[str, str], dict]:
        with self._mutex, self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
            rows = self._claims(cur, self._run(cur)["sequence"])
            claims = {}
            for row in rows:
                if self._payload_hash(row["order_id"], row["payload"]) != row["payload_hash"]:
                    raise ExecutionStoreError("OFFLINE_CLAIM_HASH_MISMATCH")
                claims[row["order_id"], row["kind"]] = row["payload"]
            return claims

    def replay(self) -> account.State:
        """Prove the immutable command prefix and the claims visible at its revision."""
        with self._mutex, self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cur:
            run = self._run(cur)
            steps = cur.execute(
                """SELECT sequence, command_id, command, command_hash, state_hash, effects, evidence, evidence_hash
                   FROM guiyi_simulation.execution_steps WHERE run_id = %s AND sequence <= %s
                   ORDER BY sequence""", (self.run_id, run["sequence"])).fetchall()
            claimed_at = {}
            for row in self._claims(cur, run["sequence"]):
                claimed_at.setdefault(row["claimed_sequence"], []).append(row)
            state = self._state(run["genesis"])
            emitted = {}
            for sequence, row in enumerate(steps, 1):
                if row["sequence"] != sequence:
                    raise ExecutionStoreError("OFFLINE_JOURNAL_SEQUENCE_GAP")
                command = codec.decode(row["command"])
                transition = self._apply(state, row["command_id"], command)
                if (transition.state is state or codec.digest(command) != row["command_hash"]
                        or codec.digest(transition.state) != row["state_hash"]
                        or row["evidence"] is not None and codec.digest(row["evidence"]) != row["evidence_hash"]
                        or codec.encode(transition.effects) != row["effects"]):
                    raise ExecutionStoreError("OFFLINE_JOURNAL_REPLAY_MISMATCH")
                state = transition.state
                for effect in transition.effects:
                    emitted[effect.order.order_id, effect.kind] = sequence
                for claim in claimed_at.get(sequence, ()):
                    order_id, kind = claim["order_id"], claim["kind"]
                    if (emitted.get((order_id, kind)) != claim["effect_sequence"]
                            or self._payload_hash(order_id, claim["payload"]) != claim["payload_hash"]):
                        raise ExecutionStoreError("OFFLINE_CLAIM_REPLAY_MISMATCH")
                    self._qualify_claim(state, order_id, kind, claim["payload"])
            if len(steps) != run["sequence"] or codec.checkpoint(state) != run["projection"]:
                raise ExecutionStoreError("OFFLINE_PROJECTION_REPLAY_MISMATCH")
            return state
