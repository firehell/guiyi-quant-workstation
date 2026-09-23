"""Read-only persisted historical reference views.

No historical driver, provider, advance operation, or notification code is
imported here.  A request owns one fresh repeatable-read transaction.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import replace
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import json
from time import monotonic

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.reference_trading.contracts import SnapshotIdentity, manifest_sha256
from app.reference_trading.models import (
    ReferenceActionRow, ReferenceBatch, ReferenceMarkRow, ReferenceRevision, ReferenceStream, ReferenceTradeRow,
)
from app.reference_trading.planning import _canonical_identity, _CAPABILITIES
from app.reference_trading.presentation import require_envelope, _wire
from app.reference_trading.repository import (
    ReferenceRepository, RepositoryConflict, _identity_from_row,
)
from guiyi_quant.reference_trading import RecordingMode
from guiyi_quant.reference_trading.htdy import MODEL_VERSION as HTDY_MODEL_VERSION


POLICY_VERSION = "entry_in_window_v1"
MAX_TOKEN_CHARS = 2048


class QueryConflict(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _encode(value: dict[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 1536:
        raise QueryConflict("TOKEN_INVALID")
    return urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str, *, kind: str) -> dict[str, object]:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_TOKEN_CHARS:
        raise QueryConflict("TOKEN_INVALID")
    try:
        raw = urlsafe_b64decode(value + "=" * (-len(value) % 4))
        parsed = json.loads(raw)
    except (ValueError, UnicodeError, Base64Error):
        raise QueryConflict("TOKEN_INVALID") from None
    if (
        not isinstance(parsed, dict)
        or parsed.get("kind") != kind
        or _encode(parsed) != value
    ):
        raise QueryConflict("TOKEN_INVALID")
    return parsed


def _day(value: object) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise QueryConflict("TOKEN_INVALID")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise QueryConflict("TOKEN_INVALID") from None


def _instant(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise QueryConflict("TOKEN_INVALID")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise QueryConflict("TOKEN_INVALID") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise QueryConflict("TOKEN_INVALID")
    return result


class HistoricalReferenceQuery:
    def __init__(self, session_factory) -> None:
        self._factory = session_factory
        self._repository = ReferenceRepository(session_factory)

    @staticmethod
    def capabilities() -> dict[str, object]:
        return {
            "code_support": {
                key: sorted(value) for key, value in _CAPABILITIES.items()
                if "-" in key
            },
            "readable_modes": ["historical_replay", "forward_observation"],
            "forward_observation": "requires_exact_activation",
            "page_opening": "separate_product_capability",
        }

    @staticmethod
    def _registered(row: ReferenceStream) -> bool:
        identity = _identity_from_row(row)
        if row.recording_mode == "historical_replay":
            return (
                row.frequency in _CAPABILITIES.get(row.strategy_code, ())
                and _canonical_identity(identity)
            )
        if row.recording_mode != "forward_observation" or not identity.observation_policy_version:
            return False
        if row.strategy_code == "htdy":
            return (
                identity.reference_model_version == HTDY_MODEL_VERSION
                and row.series_kind == "actual_dominant"
                and row.frequency in {"15m", "30m", "60m"}
            )
        return (
            row.frequency in _CAPABILITIES.get(row.strategy_code, ())
            and _canonical_identity(replace(
                identity, recording_mode=RecordingMode.HISTORICAL_REPLAY,
                observation_policy_version=None,
            ))
        )

    def streams(
        self, *, strategy: str, product: str, frequency: str,
        mode: str = "historical_replay",
    ) -> list[dict[str, object]]:
        if mode not in {"historical_replay", "forward_observation"}:
            raise QueryConflict("MODE_NOT_AVAILABLE")
        if (
            (strategy not in _CAPABILITIES and not (mode == "forward_observation" and strategy == "htdy"))
            or (strategy == "htdy" and frequency not in {"15m", "30m", "60m"})
            or (strategy in _CAPABILITIES and frequency not in _CAPABILITIES[strategy])
            or not product.isascii() or not product.isalpha()
            or not 1 <= len(product) <= 8
            or (strategy.replace("-", "_") == "subing_reference" and product != product.upper())
            or (strategy.replace("-", "_").startswith("newow_") and product != product.lower())
        ):
            raise QueryConflict("QUERY_INVALID")
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            def matching(code: str) -> list[ReferenceStream]:
                rows = session.execute(select(ReferenceStream).where(
                    ReferenceStream.strategy_code == code,
                    ReferenceStream.product == product,
                    ReferenceStream.frequency == frequency,
                    ReferenceStream.recording_mode == mode,
                ).order_by(ReferenceStream.stream_id).limit(20)).scalars().all()
                return [row for row in rows if self._registered(row)]

            exact = matching(strategy)
            fallback_code = strategy.replace("-", "_")
            fallback = matching(fallback_code) if fallback_code != strategy else []
            def readable(rows: list[ReferenceStream]) -> list[ReferenceStream]:
                return [
                    row for row in rows
                    if row.active_revision_id is not None
                    and (mode == "historical_replay" or row.enabled)
                ]
            selected = readable(exact) or readable(fallback) or exact or fallback
            return [self._stream_info(row) for row in selected]

    @staticmethod
    def _stream_info(row: ReferenceStream) -> dict[str, object]:
        return {
            "stream_id": row.stream_id, "strategy_code": row.strategy_code,
            "product": row.product, "frequency": row.frequency,
            "recording_mode": row.recording_mode,
            "formula_versions": row.formula_versions, "profile_id": row.profile_id,
            "reference_model_version": row.reference_model_version,
            "futures_adaptation_version": row.futures_adaptation_version,
            "active_revision_id": row.active_revision_id,
            "latest_seq": row.latest_seq, "health": row.health,
            "enabled": row.enabled,
            "activation_generation": row.activation_generation,
            "recording_start": row.recording_start.isoformat() if row.recording_start else None,
            "readable": row.active_revision_id is not None and (
                row.recording_mode == "historical_replay" or row.enabled
            ),
        }

    def _resolve(self, session: Session, stream_id: str) -> ReferenceStream:
        if (
            not isinstance(stream_id, str) or len(stream_id) != 81
            or not stream_id.startswith("reference-stream:")
            or any(char not in "0123456789abcdef" for char in stream_id[17:])
        ):
            raise QueryConflict("STREAM_NOT_FOUND")
        row = session.get(ReferenceStream, stream_id)
        if row is None or not self._registered(row):
            raise QueryConflict("STREAM_NOT_FOUND")
        return row

    def _snapshot(
        self, session: Session, row: ReferenceStream, *,
        since: date, through: date, cutoff: datetime | None, encoded: str | None,
    ) -> tuple[SnapshotIdentity, str, str]:
        if encoded is None:
            if row.active_revision_id is None or row.latest_seq < 1:
                raise QueryConflict("NOT_BUILT")
            if row.recording_mode == "forward_observation" and not row.enabled:
                raise QueryConflict("NOT_ENABLED")
            revision_id, seq = row.active_revision_id, row.latest_seq
            revision = session.get(ReferenceRevision, (row.stream_id, revision_id))
            if revision is None or revision.status != "active":
                raise QueryConflict("STALE_INVALID")
            digest = self._manifest_digest(session, row.stream_id, revision_id, seq)
            payload = {
                "kind": "snapshot", "stream": row.stream_id,
                "revision": revision_id, "seq": seq,
                "since": since.isoformat(), "through": through.isoformat(),
                "cutoff": cutoff.isoformat() if cutoff else None,
                "policy": POLICY_VERSION, "dependency": digest,
            }
            if row.recording_mode == "forward_observation":
                payload.update({
                    "mode": row.recording_mode, "generation": row.activation_generation,
                    "recording_start": row.recording_start.isoformat() if row.recording_start else None,
                })
            encoded = _encode(payload)
        else:
            token = _decode(encoded, kind="snapshot")
            expected_keys = {"kind", "stream", "revision", "seq", "since", "through", "cutoff", "policy", "dependency"}
            if row.recording_mode == "forward_observation":
                expected_keys |= {"mode", "generation", "recording_start"}
            if (
                set(token) != expected_keys
                or token["stream"] != row.stream_id
                or _day(token["since"]) != since or _day(token["through"]) != through
                or _instant(token["cutoff"]) != cutoff
                or token["policy"] != POLICY_VERSION
                or type(token["seq"]) is not int or token["seq"] < 1
                or not isinstance(token["revision"], str)
                or not isinstance(token["dependency"], str)
                or row.recording_mode == "forward_observation" and (
                    token.get("mode") != row.recording_mode
                    or token.get("generation") != row.activation_generation
                    or token.get("recording_start") != (
                        row.recording_start.isoformat() if row.recording_start else None
                    )
                )
            ):
                raise QueryConflict("SNAPSHOT_CONFLICT")
            revision_id, seq, digest = token["revision"], token["seq"], token["dependency"]
            revision = session.get(ReferenceRevision, (row.stream_id, revision_id))
            if revision is None or self._manifest_digest(
                session, row.stream_id, revision_id, seq,
            ) != digest:
                raise QueryConflict("SNAPSHOT_CONFLICT")
        snapshot = SnapshotIdentity(row.stream_id, revision_id, seq)
        try:
            self._repository._validate_snapshot(session, snapshot)
        except RepositoryConflict as exc:
            raise QueryConflict(str(exc)) from None
        return snapshot, encoded, digest

    @staticmethod
    def _manifest_digest(session: Session, stream_id: str, revision_id: str, seq: int) -> str:
        batch = session.scalar(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == stream_id,
            ReferenceBatch.revision_id == revision_id,
            ReferenceBatch.seq <= seq,
            ReferenceBatch.kind.in_(("seed_seal", "calculation")),
        ).order_by(ReferenceBatch.seq.desc()).limit(1))
        if batch is None:
            raise QueryConflict("SNAPSHOT_CONFLICT")
        return manifest_sha256(batch.dependency_manifest)

    @staticmethod
    def _window(since: date, through: date, cutoff: datetime | None) -> None:
        if type(since) is not date or type(through) is not date or since > through:
            raise QueryConflict("QUERY_INVALID")
        if cutoff is not None and (cutoff.tzinfo is None or cutoff.utcoffset() is None):
            raise QueryConflict("QUERY_INVALID")

    @staticmethod
    def _coverage(session: Session, snapshot: SnapshotIdentity) -> dict[str, object]:
        first, last = session.execute(select(
            func.min(ReferenceBatch.computed_through),
            func.max(ReferenceBatch.computed_through),
        ).where(
            ReferenceBatch.stream_id == snapshot.stream_id,
            ReferenceBatch.revision_id == snapshot.revision_id,
            ReferenceBatch.kind == "calculation",
            ~ReferenceBatch.batch_key.like("forward:observation-gap:%"),
            ReferenceBatch.seq <= snapshot.seq,
        )).one()
        gap_at = session.scalar(select(func.max(ReferenceBatch.observed_at)).where(
            ReferenceBatch.stream_id == snapshot.stream_id,
            ReferenceBatch.revision_id == snapshot.revision_id,
            ReferenceBatch.kind == "calculation",
            ReferenceBatch.batch_key.like("forward:observation-gap:%"),
            ReferenceBatch.seq <= snapshot.seq,
        ))
        return {
            "first_computed_through": first.isoformat() if first else None,
            "computed_through": last.isoformat() if last else None,
            "observation_boundary_at": gap_at.isoformat() if gap_at else None,
            "complete_window_proven": False,
        }

    @staticmethod
    def _assert_presentations(session: Session, snapshot: SnapshotIdentity) -> None:
        missing = session.scalar(select(ReferenceBatch.batch_id).where(
            ReferenceBatch.stream_id == snapshot.stream_id,
            ReferenceBatch.revision_id == snapshot.revision_id,
            ReferenceBatch.kind == "calculation",
            ReferenceBatch.seq <= snapshot.seq,
            ReferenceBatch.source_evidence["presentation_v1"]["version"].as_string().is_(None),
        ).limit(1))
        if missing is not None:
            raise QueryConflict("PRESENTATION_NOT_MATERIALIZED")

    def trades(
        self, stream_id: str, *, since: date, through: date,
        cutoff: datetime | None = None, limit: int = 50,
        snapshot_token: str | None = None, cursor: str | None = None,
    ) -> dict[str, object]:
        self._window(since, through, cutoff)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise QueryConflict("QUERY_INVALID")
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            row = self._resolve(session, stream_id)
            snapshot, token, digest = self._snapshot(
                session, row, since=since, through=through, cutoff=cutoff,
                encoded=snapshot_token,
            )
            self._assert_presentations(session, snapshot)
            after = None
            if cursor is not None:
                value = _decode(cursor, kind="trades")
                if set(value) != {"kind", "snapshot", "bar_end", "trade_id"} or value["snapshot"] != token:
                    raise QueryConflict("CURSOR_CONFLICT")
                instant = _instant(value["bar_end"])
                if instant is None or not isinstance(value["trade_id"], str):
                    raise QueryConflict("CURSOR_CONFLICT")
                after = (instant, value["trade_id"])
            if row.recording_mode == "forward_observation":
                page = self._repository.query_historical_trades(
                    session, snapshot, since=since, through=through,
                    cutoff=cutoff, limit=limit, after_key=after, forward=True,
                )
                next_cursor = None if page.next_key is None else _encode({
                    "kind": "trades", "snapshot": token,
                    "bar_end": page.next_key[0].isoformat(),
                    "trade_id": page.next_key[1],
                })
                return {
                    "items": [{
                        **_wire(item), "public_reference_trade_id": item.reference_trade_id,
                        "stream_id": snapshot.stream_id,
                    } for item in page.items],
                    "snapshot": token, "next_cursor": next_cursor,
                    "stream": self._stream_info(row), "revision_id": snapshot.revision_id,
                    "seq": snapshot.seq, "dependency_digest": digest,
                    "cutoff": cutoff.isoformat() if cutoff else None,
                    "window": {"since": since.isoformat(), "through": through.isoformat()},
                    "statistics_policy": POLICY_VERSION,
                    "coverage": self._coverage(session, snapshot), "status": row.health,
                    "expected_through": None, "freshness": "unknown",
                }
            interruption_keys = (
                self._boundary_keys(session, snapshot, since, through, cutoff)
                if row.strategy_code.replace("-", "_") == "subing_reference"
                else frozenset()
            )
            page = self._repository.query_historical_trades(
                session, snapshot, since=since, through=through,
                cutoff=cutoff, limit=limit, after_key=after,
                initial_interruptions=interruption_keys,
            )
            next_cursor = None if page.next_key is None else _encode({
                "kind": "trades", "snapshot": token,
                "bar_end": page.next_key[0].isoformat(),
                "trade_id": page.next_key[1],
            })
            public_ids = self._public_trade_ids(session, snapshot, page.items)
            interrupted = self._interruption_details(session, snapshot, page.items, cutoff)
            return {
                "items": [
                    {
                        **_wire(item),
                        "public_reference_trade_id": public_ids[item.entry_action_id][0],
                        "entry_sequence": public_ids[item.entry_action_id][1],
                        "exit_sequence": public_ids[item.entry_action_id][2],
                        "stream_id": snapshot.stream_id,
                        **interrupted.get(item.reference_trade_id, {}),
                    }
                    for item in page.items
                ],
                "snapshot": token, "next_cursor": next_cursor,
                "stream": self._stream_info(row),
                "revision_id": snapshot.revision_id, "seq": snapshot.seq,
                "dependency_digest": digest, "cutoff": cutoff.isoformat() if cutoff else None,
                "window": {"since": since.isoformat(), "through": through.isoformat()},
                "statistics_policy": POLICY_VERSION,
                "coverage": self._coverage(session, snapshot),
                "status": row.health,
                "expected_through": None, "freshness": "unknown",
            }

    @staticmethod
    def _boundary_keys(
        session: Session, snapshot: SnapshotIdentity,
        since: date, through: date, cutoff: datetime | None,
    ) -> frozenset[tuple[str, str, str]]:
        batches = session.execute(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == snapshot.stream_id,
            ReferenceBatch.revision_id == snapshot.revision_id,
            ReferenceBatch.kind == "calculation",
            ReferenceBatch.seq <= snapshot.seq,
            ReferenceBatch.source_evidence["presentation_v1"]["last_day"].as_string() >= since.isoformat(),
            ReferenceBatch.source_evidence["presentation_v1"]["first_day"].as_string() <= through.isoformat(),
        ).order_by(ReferenceBatch.seq).execution_options(yield_per=32)).scalars()
        keys: set[tuple[str, str, str]] = set()
        for batch in batches:
            for point in require_envelope(batch.source_evidence.get("presentation_v1")):
                if point.get("kind") != "boundary":
                    continue
                day = _day(point.get("trading_day"))
                value = point.get("value")
                if not isinstance(value, dict):
                    raise QueryConflict("PRESENTATION_CORRUPT")
                instant = _instant(value.get("bar_end"))
                if instant is None:
                    raise QueryConflict("PRESENTATION_CORRUPT")
                if not since <= day <= through or cutoff is not None and instant > cutoff:
                    continue
                key = (
                    value.get("physical_contract"), value.get("owner_segment_id"),
                    value.get("calculation_segment_id"),
                )
                if not all(isinstance(part, str) for part in key):
                    raise QueryConflict("PRESENTATION_CORRUPT")
                keys.add(key)
        return frozenset(keys)

    @staticmethod
    def _public_trade_ids(session: Session, snapshot: SnapshotIdentity, trades) -> dict[str, tuple[str, int, int | None]]:
        if not trades:
            return {}
        requested = {item.entry_action_id for item in trades}
        exits = {item.exit_action_id for item in trades if item.exit_action_id is not None}
        actions = session.execute(select(ReferenceActionRow).where(
            ReferenceActionRow.stream_id == snapshot.stream_id,
            ReferenceActionRow.origin_revision_id == snapshot.revision_id,
            ReferenceActionRow.source_action_id.in_(requested | exits),
        )).scalars().all()
        if {action.source_action_id for action in actions} != requested | exits:
            raise QueryConflict("TRADE_ACTION_CORRUPT")
        batches = session.execute(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == snapshot.stream_id,
            ReferenceBatch.revision_id == snapshot.revision_id,
            ReferenceBatch.batch_id.in_({
                action.batch_id for action in actions
                if action.source_action_id in requested
            }),
            ReferenceBatch.seq <= snapshot.seq,
        ).execution_options(yield_per=32)).scalars()
        sequences = {action.source_action_id: action.sequence for action in actions}
        exit_by_entry = {item.entry_action_id: item.exit_action_id for item in trades}
        public: dict[str, tuple[str, int, int | None]] = {}
        for batch in batches:
            for point in require_envelope(batch.source_evidence.get("presentation_v1")):
                value = point.get("value")
                if not isinstance(value, dict):
                    continue
                if point.get("kind") == "trade_identity":
                    action_id = value.get("source_action_id")
                    trade_id = value.get("public_trade_id")
                elif point.get("kind") == "signal":
                    action_id = f"{value.get('signal_id')}:open"
                    trade_id = value.get("entry_trade_id")
                else:
                    continue
                if action_id in requested and isinstance(trade_id, str) and trade_id:
                    exit_id = exit_by_entry[action_id]
                    public[action_id] = (
                        trade_id, sequences[action_id],
                        None if exit_id is None else sequences[exit_id],
                    )
        if set(public) != requested:
            raise QueryConflict("PRESENTATION_CORRUPT")
        return public

    @staticmethod
    def _interruption_details(
        session: Session, snapshot: SnapshotIdentity, trades, cutoff: datetime | None,
    ) -> dict[str, dict[str, object]]:
        ids = [item.reference_trade_id for item in trades if item.status.value not in ("OPEN", "CLOSED")]
        if not ids:
            return {}
        row = ReferenceTradeRow
        conditions = [
            row.stream_id == snapshot.stream_id,
            row.revision_id == snapshot.revision_id,
            row.trade_id.in_(ids),
            row.valid_from_seq <= snapshot.seq,
        ]
        if cutoff is not None:
            conditions.append(row.effective_bar_end <= cutoff)
        ranked = select(
            row.trade_id.label("trade_id"), row.valid_from_seq.label("valid_from_seq"),
            func.row_number().over(
                partition_by=row.trade_id, order_by=row.valid_from_seq.desc(),
            ).label("rank"),
        ).where(*conditions).subquery()
        versions = session.execute(select(row).join(ranked, and_(
            ranked.c.trade_id == row.trade_id,
            ranked.c.valid_from_seq == row.valid_from_seq,
            ranked.c.rank == 1,
        )).where(
            row.stream_id == snapshot.stream_id,
            row.revision_id == snapshot.revision_id,
        )).scalars().all()
        details = {
            item.trade_id: {"interrupted_at": item.effective_bar_end.isoformat()}
            for item in versions if item.status not in ("OPEN", "CLOSED")
        }
        if set(details) != set(ids):
            raise QueryConflict("TRADE_VERSION_CONFLICT")
        mark = ReferenceMarkRow
        eligible = [
            mark.stream_id == snapshot.stream_id,
            mark.revision_id == snapshot.revision_id,
            mark.trade_id.in_(ids),
            mark.batch_seq <= snapshot.seq,
        ]
        if cutoff is not None:
            eligible.append(mark.bar_end <= cutoff)
        latest = select(
            mark.trade_id.label("trade_id"), mark.batch_seq.label("batch_seq"),
            mark.bar_end.label("bar_end"),
            func.row_number().over(
                partition_by=mark.trade_id,
                order_by=(mark.bar_end.desc(), mark.batch_seq.desc()),
            ).label("rank"),
        ).where(*eligible).subquery()
        marks = session.execute(select(mark).join(latest, and_(
            latest.c.trade_id == mark.trade_id,
            latest.c.batch_seq == mark.batch_seq,
            latest.c.bar_end == mark.bar_end,
            latest.c.rank == 1,
        )).where(
            mark.stream_id == snapshot.stream_id,
            mark.revision_id == snapshot.revision_id,
        )).scalars().all()
        for item in marks:
            if item.trade_id in details:
                details[item.trade_id].update({
                    "prior_mark_bar_end": item.bar_end.isoformat(),
                    "prior_mark_reference_price": str(item.reference_price),
                    "prior_mark_change_pct": str(item.reference_return),
                })
        return details

    def signals(
        self, stream_id: str, *, since: date, through: date,
        cutoff: datetime | None = None, limit: int = 50,
        snapshot_token: str | None = None, cursor: str | None = None,
        point_kind: str = "signal",
    ) -> dict[str, object]:
        self._window(since, through, cutoff)
        if point_kind not in {"display_signal", "signal", "indicator", "hint", "diagnostic", "boundary", "trade_identity", "action", "availability"}:
            raise QueryConflict("QUERY_INVALID")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise QueryConflict("QUERY_INVALID")
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            row = self._resolve(session, stream_id)
            visible_kinds = (
                {"action", "hint", "diagnostic"}
                if point_kind == "display_signal" and row.strategy_code.replace("-", "_").startswith("newow_")
                else {"signal"} if point_kind == "display_signal" else {point_kind}
            )
            snapshot, token, _ = self._snapshot(
                session, row, since=since, through=through,
                cutoff=cutoff, encoded=snapshot_token,
            )
            after_seq, after_index = 0, -1
            if cursor is not None:
                value = _decode(cursor, kind=point_kind)
                if (
                    set(value) != {"kind", "snapshot", "seq", "index"}
                    or value["snapshot"] != token
                    or type(value["seq"]) is not int or type(value["index"]) is not int
                    or value["seq"] < 1 or value["index"] < 0
                ):
                    raise QueryConflict("CURSOR_CONFLICT")
                after_seq, after_index = value["seq"], value["index"]
            self._assert_presentations(session, snapshot)
            batches = session.execute(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == snapshot.revision_id,
                ReferenceBatch.kind == "calculation",
                ReferenceBatch.seq <= snapshot.seq,
                ReferenceBatch.seq >= max(1, after_seq),
                ReferenceBatch.source_evidence["presentation_v1"]["last_day"].as_string() >= since.isoformat(),
                ReferenceBatch.source_evidence["presentation_v1"]["first_day"].as_string() <= through.isoformat(),
                *(() if cutoff is None or row.recording_mode != "forward_observation" else (
                    ReferenceBatch.observed_at <= cutoff,
                )),
            ).order_by(ReferenceBatch.seq).execution_options(yield_per=32)).scalars()
            selected: list[tuple[int, int, dict[str, object]]] = []
            for batch in batches:
                for index, point in enumerate(require_envelope(
                    batch.source_evidence.get("presentation_v1"),
                )):
                    if (batch.seq, index) <= (after_seq, after_index):
                        continue
                    if point.get("kind") not in visible_kinds:
                        continue
                    day = _day(point.get("trading_day"))
                    value = point.get("value")
                    if not since <= day <= through or not isinstance(value, dict):
                        continue
                    instant = _instant(value.get("bar_end"))
                    if instant is None:
                        raise QueryConflict("PRESENTATION_CORRUPT")
                    if cutoff is not None and instant > cutoff:
                        continue
                    if point.get("kind") == "hint" and "known_at" not in value:
                        raise QueryConflict("PRESENTATION_CORRUPT")
                    if "known_at" in value:
                        known_at = _instant(value["known_at"])
                        if known_at is None:
                            raise QueryConflict("PRESENTATION_CORRUPT")
                        if cutoff is not None and known_at > cutoff:
                            continue
                    selected.append((batch.seq, index, point))
                    if len(selected) > limit:
                        break
                if len(selected) > limit:
                    break
            more = len(selected) > limit
            selected = selected[:limit]
            next_cursor = None
            if more and selected:
                seq, index, _ = selected[-1]
                next_cursor = _encode({
                    "kind": point_kind, "snapshot": token, "seq": seq, "index": index,
                })
            return {
                "items": [point for _seq, _index, point in selected],
                "snapshot": token, "next_cursor": next_cursor,
                "revision_id": snapshot.revision_id, "seq": snapshot.seq,
                "cutoff": cutoff.isoformat() if cutoff else None,
                "window": {"since": since.isoformat(), "through": through.isoformat()},
                "coverage": self._coverage(session, snapshot),
                "status": row.health,
            }

    def summary(
        self, stream_id: str, *, since: date, through: date,
        cutoff: datetime | None = None, snapshot_token: str | None = None,
    ) -> dict[str, object]:
        self._window(since, through, cutoff)
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            row = self._resolve(session, stream_id)
            snapshot, token, _ = self._snapshot(
                session, row, since=since, through=through,
                cutoff=cutoff, encoded=snapshot_token,
            )
            self._assert_presentations(session, snapshot)
            boundary_keys = (
                self._boundary_keys(session, snapshot, since, through, cutoff)
                if row.strategy_code.replace("-", "_") == "subing_reference"
                else frozenset()
            )
            counts = {"closed_count": 0, "win_count": 0, "loss_count": 0,
                      "flat_count": 0, "open_count": 0, "interrupted_count": 0,
                      "rollover_interrupted_count": 0, "data_interrupted_count": 0}
            trade = ReferenceTradeRow
            eligible = [
                trade.stream_id == stream_id,
                trade.revision_id == snapshot.revision_id,
                trade.valid_from_seq <= snapshot.seq,
                trade.entry_trading_day <= through,
            ]
            if cutoff is not None:
                eligible.extend((
                    trade.entry_bar_end <= cutoff,
                    trade.effective_bar_end <= cutoff,
                    or_(trade.exit_bar_end.is_(None), trade.exit_bar_end <= cutoff),
                ))
                if row.recording_mode == "forward_observation":
                    eligible.append(trade.observed_at <= cutoff)
            latest = select(
                trade.trade_id.label("trade_id"),
                trade.valid_from_seq.label("valid_from_seq"),
                func.row_number().over(
                    partition_by=trade.trade_id,
                    order_by=trade.valid_from_seq.desc(),
                ).label("rank"),
            ).where(*eligible).subquery()
            rows = session.execute(select(trade).join(latest, and_(
                latest.c.trade_id == trade.trade_id,
                latest.c.valid_from_seq == trade.valid_from_seq,
                latest.c.rank == 1,
            )).where(
                trade.stream_id == stream_id,
                trade.revision_id == snapshot.revision_id,
            ).order_by(
                trade.entry_bar_end, trade.trade_id,
            ).execution_options(yield_per=200)).scalars()
            deadline = monotonic() + 25
            initial_count = 0
            total = Decimal("0")
            with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
                for item in rows:
                    if monotonic() >= deadline:
                        raise QueryConflict("QUERY_BUDGET_EXCEEDED")
                    initial = item.entry_trading_day < since
                    if initial:
                        if row.recording_mode == "forward_observation":
                            # Match the forward trade-page window: a prior close or
                            # interruption is no longer an initial holding.
                            if item.status == "CLOSED" and item.exit_trading_day < since:
                                continue
                            if item.status not in ("OPEN", "CLOSED"):
                                continue
                        elif row.strategy_code.replace("-", "_") == "subing_reference":
                            if item.status == "CLOSED" and item.exit_trading_day < since:
                                continue
                            if item.status not in ("OPEN", "CLOSED"):
                                key = (
                                    item.physical_contract, item.owner_segment_id,
                                    item.calculation_segment_id,
                                )
                                if key not in boundary_keys:
                                    continue
                        initial_count += 1
                        continue
                    if item.status == "CLOSED":
                        if item.reference_return is None:
                            raise QueryConflict("SUMMARY_DATA_CONFLICT")
                        counts["closed_count"] += 1
                        total += item.reference_return
                        counts["win_count" if item.reference_return > 0 else
                               "loss_count" if item.reference_return < 0 else "flat_count"] += 1
                    elif item.status == "OPEN":
                        counts["open_count"] += 1
                    else:
                        counts["interrupted_count"] += 1
                        if item.status == "ROLLOVER_INTERRUPTED":
                            counts["rollover_interrupted_count"] += 1
                        elif item.status == "DATA_INTERRUPTED":
                            counts["data_interrupted_count"] += 1
                closed = counts["closed_count"]
                mean = total / Decimal(closed) if closed else None
                rate = Decimal(counts["win_count"]) / Decimal(closed) * 100 if closed else None
            return {
                **counts, "initial_count": initial_count,
                "win_rate_pct": str(rate) if rate is not None else None,
                "mean_return_pct": str(mean) if mean is not None else None,
                "sum_return_percentage_points": str(total) if closed or row.strategy_code.replace("-", "_") == "subing_reference" else None,
                "statistics_policy": POLICY_VERSION, "snapshot": token,
                "revision_id": snapshot.revision_id, "seq": snapshot.seq,
                "window": {"since": since.isoformat(), "through": through.isoformat()},
                "coverage": self._coverage(session, snapshot),
                "status": row.health,
            }
