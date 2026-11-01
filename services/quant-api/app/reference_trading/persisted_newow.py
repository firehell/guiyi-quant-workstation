"""Persisted Newow reference section over the existing bounded MDS read."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import json
from threading import Lock
from typing import Any
from contextlib import closing, ExitStack
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import defer

from app.db.readonly import readonly_transaction
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.models import ReferenceBatch, ReferenceStream
from app.reference_trading.planning import HistoricalStreamRequest
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict, _decode, _encode
from app.reference_trading.repository import _identity_from_row
from app.reference_trading.fingerprint_proof import SEMANTIC_READERS, fingerprint_count
from app.reference_trading.source_identity import verify_saved_input_prefix, verify_saved_compact_source, ReferenceReadConflict, verified_saved_extension


def _completed_reference_window(read, cutoff):
    """Use owned completed facts, including the provider's night trading day."""
    latest_end = latest_day = None
    for item in getattr(read, "replay_bars", ()):
        bar = item.bar
        if bar.bar_end <= cutoff and bar.observation_eligible:
            latest_end = max(latest_end or bar.bar_end, bar.bar_end)
            latest_day = max(latest_day or bar.trading_day, bar.trading_day)
    if getattr(read, "data_interruptions", ()):
        from app.market_data.newow.product_service import _owned_display_interruptions
        for gap in _owned_display_interruptions(read):
            if gap.effective_at <= cutoff:
                latest_end = max(latest_end or gap.effective_at, gap.effective_at)
                latest_day = max(latest_day or gap.trading_day, gap.trading_day)
    if latest_end is None:
        # Intraday reference scope intentionally contains provenance only. Its
        # selected-frequency Session endpoint is authoritative for market lag;
        # resolving an old result's trading day still requires a completed read.
        source = getattr(read, "sources", {}).get(getattr(read, "frequency", None))
        endpoint = getattr(source, "bar_end", None)
        return (endpoint if endpoint is not None and endpoint <= cutoff else None), None
    return latest_end, latest_day


@dataclass(frozen=True, slots=True)
class _CompletePresentation:
    """One exact saved generation, retained inside the existing product budget."""

    payload: dict[str, Any]
    items_by_saved_id: dict[str, dict[str, Any]]
    status: Any
    generation: tuple[str, str, int]
    materials: dict[str, Any] | None = None


class _SavedManifest(dict):
    """Keep read watermark alongside, never inside the saved manifest proof."""
    def __init__(self, manifest, computed_through, *, page_material=None, input_integrity=None, generation=None):
        super().__init__(manifest)
        self.computed_through = computed_through
        self.page_material = page_material
        self.input_integrity = input_integrity
        self.generation = generation


class PersistedNewowReference:
    def __init__(self, session_factory, *, cache=None) -> None:
        self._factory = session_factory
        self._query = HistoricalReferenceQuery(session_factory)
        self._cache = cache
        self._page_reads: OrderedDict[tuple, Any] = OrderedDict()
        self._page_read_lock = Lock()

    def _manifest(self, stream_id: str, revision_id: str, seq: int):
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            stream = session.get(ReferenceStream, stream_id)
            batch = session.scalar(select(ReferenceBatch).options(defer(ReferenceBatch.dependency_manifest)).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.seq <= seq,
                ReferenceBatch.kind.in_(("seed_seal", "calculation")),
            ).order_by(ReferenceBatch.seq.desc()).limit(1))
            if stream is None or batch is None:
                raise QueryConflict("SNAPSHOT_CONFLICT")
            from app.reference_trading.manifest_storage import resolve_manifest
            endpoint = batch.computed_through
            if endpoint is not None and endpoint.tzinfo is None:
                endpoint = endpoint.replace(tzinfo=UTC)
            evidence = batch.source_evidence
            if not isinstance(evidence, dict):
                raise QueryConflict("PRESENTATION_CORRUPT")
            from app.reference_trading.page_material_query import latest_input_integrity
            return _identity_from_row(stream), _SavedManifest(
                resolve_manifest(session, batch), endpoint,
                page_material=evidence.get("page_material_v1"),
                input_integrity=latest_input_integrity(session, batch),
                generation=(stream_id, revision_id, batch.seq),
            )

    @staticmethod
    def _material_owner_keys(envelope):
        try:
            owners = set()
            for segment in envelope["material"]["segments"]:
                physical, owner, _calculation = segment["owner"].split("|", 2)
                if not physical or not owner:
                    raise ValueError("invalid material owner")
                owners.add((physical, owner))
            return frozenset(owners)
        except (KeyError, TypeError, ValueError) as error:
            raise QueryConflict("PRESENTATION_CORRUPT") from error

    def _verify_material_source(self, identity, manifest, reader, *, owner_keys,
                                saved_through, saved_day, requested_through):
        """Prove old inputs using a freshly checked committed input generation.

        A later active batch may carry a verified source while its final page
        material is still being calculated. Only its source proof is reused;
        every visible number and record remains on the selected material seq.
        """
        from dataclasses import replace
        from app.reference_trading.page_material_storage import validate_input_integrity, verify_source_integrity
        from app.reference_trading.contracts import manifest_sha256
        from guiyi_quant.newow.product_adapters import build_product_identity
        from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
        from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION
        source_manifest = manifest
        source_identity = identity
        if identity.strategy_code.replace("-", "_") == "newow_dual_fusion":
            from app.reference_trading.newow_fusion import fusion_input_policy
            product = build_product_identity(identity.product, ProductStrategy.TREND,
                ProductFrequency(identity.frequency), input_quality_policy=fusion_input_policy(identity))
            source_identity = replace(identity, strategy_code="newow_trend",
                formula_versions=product.formula_versions, profile_id=product.profile_id,
                reference_model_version=REFERENCE_MODEL_VERSION)
            source_manifest = {**manifest, "reader": manifest.get("source_reader"),
                "input_fingerprints": manifest.get("source_input_fingerprints"),
                "formula_versions": list(product.formula_versions),
                "reference_model_version": REFERENCE_MODEL_VERSION}
        if source_manifest.get("reader") != "newow_product_reader_prefix_v5":
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        matches = self._query.streams(strategy=source_identity.strategy_code,
            product=source_identity.product, frequency=source_identity.frequency,
            mode="historical_replay")
        if len(matches) != 1:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        current = matches[0]
        current_identity, current_manifest = self._manifest(current["stream_id"],
            current["active_revision_id"], current["latest_seq"])
        record = getattr(current_manifest, "input_integrity", None)
        if not isinstance(record, dict):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        request = record.get("request")
        if (not isinstance(request, dict)
                or request.get("product") != current_identity.product.lower()
                or request.get("frequency") != current_identity.frequency
                or request.get("since") != current_manifest.get("query_since")):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        digest = manifest_sha256(current_manifest)
        expected = {
            "schema": "reference_input_integrity_v1",
            "stream_id": current["stream_id"], "revision_id": current["active_revision_id"],
            "seq": current["latest_seq"], "manifest_sha256": digest,
            "source_token": digest, "source_integrity": record.get("source_integrity"),
            "request": request,
        }
        try:
            validate_input_integrity(record, expected_binding=expected)
            fresh = verify_source_integrity(reader, expected["source_integrity"])
        except (TypeError, ValueError, KeyError) as error:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from error
        if not fresh:
            raise ReferenceReadConflict("REFERENCE_UPDATE_PENDING",
                saved_through=saved_through, requested_through=requested_through)
        verify_saved_input_prefix(current_manifest, source_manifest,
            saved_day, owner_keys)
        return True

    def _page_read(self, request, reader, manifest, resolved):
        """Decode the authoritative prefix only after saved source proof passes.

        Reuse binds the entire saved manifest and exact cutoff/window; a cache
        hit still verifies current Canonical evidence. This cache never weakens
        the independent saved stream revision/seq validation.
        """
        from dataclasses import replace
        from app.market_data.newow.product_query import NewowProductQuery
        if manifest.get("reader") in SEMANTIC_READERS:
            from app.reference_trading.planning import HistoricalStreamRequest
            stream = self._query.streams(strategy=f"newow_{request.strategy.value}",
                product=request.product, frequency=request.frequency.value, mode="historical_replay")
            if len(stream) != 1:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            # Semantic verification is repeated around the bounded display read.
            identity, _ = self._manifest(stream[0]["stream_id"], stream[0]["active_revision_id"], stream[0]["latest_seq"])
            def semantic_verify():
                input_reader = MarketDataHistoricalInputReader(newow_reader=reader, subing_service=None)
                with input_reader.planned_stream(HistoricalStreamRequest(
                    identity, date.fromisoformat(manifest["query_since"]),
                    resolved.actual_through, resolved.cutoff,
                )) as source:
                    verify_saved_input_prefix(manifest, source.dependency_manifest, resolved.actual_through,
                        frozenset((bar.physical_contract, bar.owner_segment_id) for bar in source.bars if bar.strategy_input))
                    return source.source_token
            before = semantic_verify()
            query = NewowProductQuery(request.product, request.strategy, request.frequency,
                date.fromisoformat(manifest["query_since"]), resolved.actual_through,
                date.fromisoformat(manifest["query_since"]), resolved.actual_through, resolved.cutoff)
            historical = getattr(reader, "load_historical", None)
            full = historical(query, resolved.cutoff) if callable(historical) else reader.load(query, resolved.cutoff)
            try:
                if semantic_verify() != before:
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
                return full
            except BaseException:
                close = getattr(full, "close", None)
                if callable(close):
                    close()
                raise
        if manifest.get("reader") != "newow_product_reader_intraday_v3":
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        try:
            start = date.fromisoformat(manifest["query_since"])
            source_through = date.fromisoformat(manifest["query_through"])
            source_as_of = datetime.fromisoformat(manifest["query_as_of"])
            if resolved.actual_through > source_through or resolved.cutoff > source_as_of:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            def verify():
                evidence = reader.historical_source_evidence(product=request.product,
                    frequency=request.frequency.value, since=start,
                    through=source_through, as_of=source_as_of)
                verify_saved_compact_source(manifest, evidence)
                return sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
            source_hash = verify()
            historical_loader = getattr(reader, "load_historical", None)
            if callable(historical_loader):
                # Legacy byte-bound proofs still use bounded decoding. Disposable
                # spools belong to this response and never enter the display cache.
                query = NewowProductQuery(request.product, request.strategy, request.frequency,
                    start, resolved.actual_through, start, resolved.actual_through,
                    resolved.cutoff)
                full = historical_loader(query, resolved.cutoff)
                try:
                    if not full.replay_bars or full.as_of != resolved.cutoff:
                        raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
                    if verify() != source_hash:
                        raise QueryConflict("SOURCE_GENERATION_CONFLICT")
                    return replace(full, reference_source_evidence_sha256=source_hash)
                except BaseException:
                    full.close()
                    raise
            key = (request.product, request.frequency.value,
                source_hash, start, source_through, source_as_of,
                resolved.actual_through, resolved.cutoff)
            with self._page_read_lock:
                cached = self._page_reads.get(key)
                if cached is not None:
                    self._page_reads.move_to_end(key)
                    return cached
            query = NewowProductQuery(request.product, request.strategy, request.frequency,
                start, resolved.actual_through, start, resolved.actual_through,
                resolved.cutoff)
            full = reader.load(query, resolved.cutoff)
            if not full.replay_bars or full.as_of != resolved.cutoff:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            if verify() != source_hash:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            full = replace(full, reference_source_evidence_sha256=source_hash)
            with self._page_read_lock:
                self._page_reads[key] = full
                while len(self._page_reads) > 4:
                    self._page_reads.popitem(last=False)
            return full
        except (KeyError, TypeError, ValueError) as exc:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from exc

    @staticmethod
    def _coverage(points, gaps, since: date, through: date):
        events = []
        for point in points:
            value = point["value"]
            events.append((
                point["trading_day"],
                "VALID" if value["status"] == "ready" else "WARMING",
                value["physical_contract"], value["segment_id"],
                value["calculation_segment_id"],
            ))
        for gap in gaps:
            if since <= gap.trading_day <= through:
                events.append((
                    gap.trading_day.isoformat(), "PRICE_UNAVAILABLE",
                    gap.physical_contract, gap.segment_id, None,
                ))
        grouped: dict[str, list[tuple]] = {}
        for event in events:
            grouped.setdefault(event[0], []).append(event)
        intervals: list[dict[str, object]] = []
        for day in sorted(grouped):
            same = grouped[day]
            if len({(item[2], item[3], item[4]) for item in same}) > 1:
                raise QueryConflict("COVERAGE_IDENTITY_CONFLICT")
            status = (
                "PRICE_UNAVAILABLE" if any(item[1] == "PRICE_UNAVAILABLE" for item in same)
                else "WARMING" if any(item[1] == "WARMING" for item in same)
                else "VALID"
            )
            event = same[0]
            current = {
                "since": day, "through": day, "status": status,
                "physical_contract": event[2], "segment_id": event[3],
                "calculation_segment_id": event[4],
            }
            if intervals and all(
                intervals[-1][key] == current[key]
                for key in ("status", "physical_contract", "segment_id", "calculation_segment_id")
            ):
                intervals[-1]["through"] = day
            else:
                intervals.append(current)
        return intervals

    @staticmethod
    def _hint_ids(trades, actions, hints, cutoff: datetime):
        positions = set()
        action_bars = set()
        for point in actions:
            value = point["value"]
            key = (value["physical_contract"], value["segment_id"], value["bar_end"])
            action_bars.add(key)
            positions.add((*key, value["sequence"]))
        attached: dict[str, list[Any]] = {item["reference_trade_id"]: [] for item in trades}
        from bisect import bisect_right
        indexed: dict[tuple, list[tuple[datetime, datetime, Any]]] = {}
        for trade in trades:
            key = (trade["physical_contract"], trade["owner_segment_id"], trade.get("calculation_segment_id", trade["owner_segment_id"]))
            entry = datetime.fromisoformat(trade["entry_bar_end"])
            end = datetime.fromisoformat(trade["exit_bar_end"]) if trade["status"] == "CLOSED" else datetime.fromisoformat(trade["interrupted_at"]) if trade["status"] in {"ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"} else cutoff
            indexed.setdefault(key, []).append((entry, end, trade))
        groups = {}
        for key, rows in indexed.items():
            rows.sort(key=lambda row: row[0])
            maximum: list[datetime] = []
            for _, end, _ in rows:
                maximum.append(max(end, maximum[-1]) if maximum else end)
            groups[key] = (rows, [row[0] for row in rows], maximum)
        for point in hints:
            hint = point["value"]
            if (
                hint.get("retrospective") is not False
                or str(hint.get("kind", "")).casefold() in {"control_mirror", "zhaoyaojing"}
            ):
                raise QueryConflict("PRESENTATION_CORRUPT")
            known_at = datetime.fromisoformat(hint["known_at"])
            if known_at > cutoff:
                continue
            key = (hint["physical_contract"], hint["segment_id"], hint["bar_end"])
            sequence = hint.get("sequence")
            if (sequence is None and key in action_bars) or (*key, sequence) in positions:
                continue
            matches = []
            at = datetime.fromisoformat(hint["bar_end"])
            rows, starts, maximum = groups.get((key[0], key[1], hint.get("calculation_segment_id", hint["segment_id"])), ([], [], []))
            index = bisect_right(starts, at) - 1
            while index >= 0 and maximum[index] >= at:
                entry, end, trade = rows[index]
                index -= 1
                if sequence is None:
                    if at <= entry:
                        continue
                elif (at, sequence) <= (entry, trade["entry_sequence"]):
                    continue
                if trade["status"] == "CLOSED":
                    exit_at = end
                    if sequence is None:
                        if at >= exit_at:
                            continue
                    elif (at, sequence) >= (exit_at, trade["exit_sequence"]):
                        continue
                elif trade["status"] in {"ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"}:
                    interrupted = end
                    if at > interrupted:
                        continue
                elif at > cutoff:
                    continue
                matches.append(trade["reference_trade_id"])
            if len(matches) == 1:
                attached[matches[0]].append(hint["hint_id"])
        return attached

    def _reference_facts(self, stream_id, snapshot, since, storage_start, through,
                         cutoff, manifest, minute, check_cancelled):
        facts = self._query.presentation_facts(
            stream_id, snapshot_token=snapshot,
            since=since if minute else storage_start, through=through, cutoff=cutoff,
            kinds=("availability", "boundary", "hint") if minute else
                  ("availability", "boundary", "hint", "action"),
            max_points=200_000 if minute else 100_000,
            check_cancelled=check_cancelled,
        )
        if not minute:
            return facts
        # Actions only suppress hints at the same physical owner/bar. Preserve all
        # sequences at that bar, including suppression of an unsequenced hint.
        facts["action"] = []
        if not facts["hint"]:
            return facts
        hint_bars = {
            (point["value"]["physical_contract"], point["value"]["segment_id"],
             point["value"]["bar_end"])
            for point in facts["hint"]
        }
        with closing(self._query.historical_actions(
            stream_id, snapshot_token=snapshot, since=since, through=through,
            cutoff=cutoff, input_count=manifest.get("input_count", fingerprint_count(manifest.get("input_fingerprints", []))),
            check_cancelled=check_cancelled,
        )) as actions:
            for point in actions:
                value = point["value"]
                if (value["physical_contract"], value["segment_id"], value["bar_end"]) in hint_bars:
                    facts["action"].append(point)
        return facts

    def _validate_material_generation(self, delivery, reader):
        """Validate the latest complete page snapshot without replaying inputs."""
        from app.reference_trading.page_material_query import select_page_material
        payload, saved = delivery.value.payload, delivery.value.saved_generation
        identity, manifest = self._manifest(*saved)
        if manifest.get("reader") != "newow_product_reader_prefix_v5":
            return False
        since = date.fromisoformat(payload["performance_since"])
        through = date.fromisoformat(payload["performance_through"])
        cutoff = datetime.fromisoformat(payload["reference_cutoff"])
        market = datetime.fromisoformat(payload["reference_status"]["market_through"])
        fusion = payload.get("fusion_comparison")
        fusion_material = None
        if fusion is not None:
            routes = self._query.streams(strategy="newow_dual_fusion",
                product=identity.product, frequency=identity.frequency, mode="historical_replay")
            if len(routes) != 1:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            fusion_material = select_page_material(self._factory, routes[0]["stream_id"], cutoff=market)
            if fusion_material is None or fusion_material.cutoff != cutoff:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            fusion_identity, fusion_manifest = self._manifest(fusion_material.stream_id,
                fusion_material.revision_id, fusion_material.seq)
            dependencies = fusion_manifest.get("source_dependencies")
            if not isinstance(dependencies, list) or len(dependencies) != 2:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            index = {"newow_trend": 0, "newow_oscillation": 1}.get(identity.strategy_code)
            dependency = dependencies[index] if index is not None else None
            material = select_page_material(self._factory, saved[0], cutoff=cutoff,
                generation=(dependency["revision_id"], dependency["seq"]) if dependency else None)
            if dependency is not None and dependency.get("stream_id") != saved[0]:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
        else:
            material = select_page_material(self._factory, saved[0], cutoff=market)
        if material is None or (material.revision_id, material.seq, material.cutoff) != (saved[1], saved[2], cutoff):
            raise QueryConflict("SOURCE_GENERATION_CONFLICT")
        envelope = material.envelope(manifest, identity)
        self._query.summary(saved[0], since=since, through=through, cutoff=cutoff,
            snapshot_token=material.token(manifest, since=since, through=through, cutoff=cutoff))
        if reader is not None:
            self._verify_material_source(identity, manifest, reader,
                owner_keys=self._material_owner_keys(envelope), saved_through=cutoff,
                saved_day=material.through, requested_through=market)
        if fusion_material is not None:
            from app.reference_trading.newow_fusion import PersistedFusionComparison
            from app.reference_trading.contracts import manifest_sha256
            token = fusion_material.token(fusion_manifest, since=since, through=through, cutoff=cutoff)
            self._query.summary(fusion_material.stream_id, since=since, through=through,
                cutoff=cutoff, snapshot_token=token)
            revision = manifest_sha256({"snapshot": token, "dependencies": dependencies,
                "record_since": fusion.get("record_since", (through - timedelta(days=364)).isoformat()),
                "record_through": through.isoformat()})
            if revision != fusion["reference_revision"]:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            for dependency in dependencies:
                _, base = self._manifest(dependency["stream_id"], dependency["revision_id"], dependency["seq"])
                if manifest_sha256(base) != dependency.get("dependency_digest"):
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
                dt = _decode(dependency["snapshot"], kind="snapshot")
                dt.update(since=since.isoformat(), through=through.isoformat(), cutoff=cutoff.isoformat())
                summary = self._query.summary(dependency["stream_id"], since=since, through=through,
                    cutoff=cutoff, snapshot_token=_encode(dt))
                if (summary["revision_id"], summary["seq"]) != (dependency["revision_id"], dependency["seq"]):
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            if reader is not None:
                PersistedFusionComparison.verify_saved_source(fusion_identity, fusion_manifest,
                    product=identity.product, frequency=identity.frequency, through=through,
                    cutoff=cutoff, reader=reader, persisted=self)
        return True

    def validate_cached_generation(self, delivery, *, reader=None):
        from app.reference_trading.contracts import manifest_sha256
        payload = delivery.value.payload
        saved = delivery.value.saved_generation
        if saved is None:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        if self._validate_material_generation(delivery, reader):
            return
        since, through = date.fromisoformat(payload["performance_since"]), date.fromisoformat(payload["performance_through"])
        cutoff = datetime.fromisoformat(payload["reference_cutoff"])
        current = self._query.summary(saved[0], since=since, through=through, cutoff=cutoff)
        if (current["revision_id"], current["seq"]) != (saved[1], saved[2]):
            raise QueryConflict("SOURCE_GENERATION_CONFLICT")
        if reader is not None:
            source_identity, source_manifest = self._manifest(*saved)
            if source_manifest.get("reader") in SEMANTIC_READERS:
                input_reader = MarketDataHistoricalInputReader(newow_reader=reader, subing_service=None)
                with input_reader.planned_stream(HistoricalStreamRequest(
                    source_identity, date.fromisoformat(source_manifest["query_since"]),
                    date.fromisoformat(payload["actual_available_through"]), cutoff,
                )) as source:
                    verify_saved_input_prefix(source_manifest, source.dependency_manifest,
                        date.fromisoformat(payload["actual_available_through"]),
                        frozenset((bar.physical_contract, bar.owner_segment_id) for bar in source.bars if bar.strategy_input))
        fusion = payload.get("fusion_comparison")
        if fusion is None:
            return
        streams = self._query.streams(strategy="newow_dual_fusion", product=fusion["product"], frequency=fusion["frequency"], mode="historical_replay")
        if len(streams) != 1:
            raise QueryConflict("SOURCE_GENERATION_CONFLICT")
        latest = self._query.summary(streams[0]["stream_id"], since=since, through=through, cutoff=cutoff)
        identity, manifest = self._manifest(streams[0]["stream_id"], latest["revision_id"], latest["seq"])
        dependencies = manifest.get("source_dependencies")
        if not isinstance(dependencies, list) or len(dependencies) != 2:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        revision = manifest_sha256({"snapshot": latest["snapshot"], "dependencies": dependencies,
            "record_since": fusion.get("record_since", (through - timedelta(days=364)).isoformat()),
            "record_through": through.isoformat()})
        if revision != fusion["reference_revision"]:
            raise QueryConflict("SOURCE_GENERATION_CONFLICT")
        for strategy, dependency in zip(("trend", "oscillation"), dependencies):
            base = self._query.streams(strategy="newow_" + strategy, product=fusion["product"], frequency=fusion["frequency"], mode="historical_replay")
            semantic_fusion = manifest.get("source_reader") in SEMANTIC_READERS
            if (len(base) != 1 or base[0]["stream_id"] != dependency["stream_id"]
                or not semantic_fusion and (base[0]["active_revision_id"], base[0]["latest_seq"]) != (dependency["revision_id"], dependency["seq"])):
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            _, dependency_manifest = self._manifest(dependency["stream_id"], dependency["revision_id"], dependency["seq"])
            if manifest_sha256(dependency_manifest) != dependency.get("dependency_digest"):
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            snapshot_options = {}
            if semantic_fusion:
                dependency_token = _decode(dependency["snapshot"], kind="snapshot")
                dependency_token.update(since=since.isoformat(), through=through.isoformat(), cutoff=cutoff.isoformat())
                snapshot_options["snapshot_token"] = _encode(dependency_token)
            dependency_summary = self._query.summary(dependency["stream_id"], since=since, through=through, cutoff=cutoff,
                **snapshot_options)
            if (dependency_summary["revision_id"], dependency_summary["seq"]) != (dependency["revision_id"], dependency["seq"]):
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
        if reader is not None:
            from app.reference_trading.newow_fusion import PersistedFusionComparison
            PersistedFusionComparison.verify_saved_source(
                identity, manifest, product=fusion["product"], frequency=fusion["frequency"],
                through=through, cutoff=cutoff, reader=reader, persisted=self,
            )

    def attach_cached_fusion(self, request, delivery, reader, fact_key, resolved):
        from dataclasses import replace
        from app.market_data.newow.product_service import PersistedReferenceSectionValue
        from app.reference_trading.newow_fusion import PersistedFusionComparison
        payload = delivery.value.payload
        saved = delivery.value.saved_generation
        if not isinstance(saved, tuple) or len(saved) != 3:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        _, saved_manifest = self._manifest(*saved)
        material = None
        material_token = None
        if saved_manifest.get("reader") == "newow_product_reader_prefix_v5":
            from app.reference_trading.page_material_query import select_page_material
            from app.market_data.newow.page_performance_adapter import project_page_material
            self.validate_cached_generation(delivery, reader=reader)
            cutoff = datetime.fromisoformat(payload["reference_cutoff"])
            routes = self._query.streams(strategy="newow_dual_fusion", product=request.product,
                frequency=request.frequency.value, mode="historical_replay")
            if len(routes) != 1:
                raise QueryConflict("NOT_BUILT")
            material = select_page_material(self._factory, routes[0]["stream_id"], cutoff=cutoff)
            if material is None or material.cutoff != cutoff:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            fusion_identity, fusion_manifest = self._manifest(material.stream_id, material.revision_id, material.seq)
            dependencies = fusion_manifest.get("source_dependencies")
            index = {"trend": 0, "oscillation": 1}.get(request.strategy.value)
            if not isinstance(dependencies, list) or len(dependencies) != 2:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            if index is not None:
                dependency = dependencies[index]
                if (dependency.get("stream_id"), dependency.get("revision_id"), dependency.get("seq")) != saved:
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            material_token = material.token(fusion_manifest, since=resolved.requested_since,
                through=resolved.requested_through, cutoff=cutoff)
        else:
            current = self._query.summary(saved[0], since=resolved.requested_since,
                through=resolved.actual_through, cutoff=resolved.cutoff)
            if (current["revision_id"], current["seq"]) != (saved[1], saved[2]):
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            cutoff = resolved.cutoff
        fusion = PersistedFusionComparison(self._factory).comparison(
            product=request.product, frequency=request.frequency.value,
            since=resolved.requested_since, through=resolved.requested_through,
            cutoff=cutoff, reader=reader, limit=request.history_limit,
            cursor=request.fusion_before,
            expected_source_generation=(request.strategy.value, *saved),
            snapshot_token=material_token,
        )
        fusion["fusion_input_sha256"] = fusion["reference_input_sha256"]
        fusion["reference_input_sha256"] = fact_key
        if material is not None:
            envelope = material.envelope(fusion_manifest, fusion_identity)
            fusion["page_performance"] = project_page_material(envelope,
                since=resolved.requested_since.isoformat(), through=resolved.requested_through.isoformat())
        else:
            from guiyi_quant.newow.product_adapters import build_product_identity
            from app.market_data.newow.page_performance_adapter import project_page_performance
            _, manifest = self._manifest(*saved)
            full = self._page_read(request, reader, manifest, resolved)
            try:
                source_identity = build_product_identity(request.product, request.strategy, request.frequency,
                    input_quality_policy=full.input_quality_policy)
                fusion["page_performance"] = project_page_performance(full, source_identity, resolved, fusion=True)
            finally:
                close = getattr(full, "close", None)
                if callable(close):
                    close()
        self.validate_cached_generation(delivery)
        return replace(delivery, value=PersistedReferenceSectionValue({**payload, "fusion_comparison": fusion}, saved))

    def _selected_projection(self, request, read, identity, reader, fact_key, resolved,
                             generation, snapshot, manifest, curve_items, availability, boundaries,
                             full_read=None, page_materials=None, fusion_material=None):
        """Derive only the requested display model from one complete saved base."""
        from app.market_data.newow.page_performance_adapter import project_page_performance, project_page_material
        stream_id = generation[0]
        reference_mode = getattr(request, "reference_mode", None)
        mode = reference_mode.value if reference_mode is not None else None
        local = mode.removeprefix("fusion_") if mode is not None else None
        fusion_selected = mode is not None and mode.startswith("fusion_")
        page_mode = local.removeprefix("page_") if local is not None and local.startswith("page_") else None
        legacy = mode is None
        extra = {}
        marks = None
        if legacy or (not fusion_selected and local in {"holding", "theoretical"}):
            marks = self._query.curve_marks(stream_id, since=resolved.requested_since,
                through=resolved.requested_through, cutoff=resolved.cutoff, snapshot_token=snapshot)
        if legacy or (not fusion_selected and local == "holding"):
            from app.reference_trading.saved_holding_curve import saved_holding_curve
            extra["holding_curve"] = saved_holding_curve(curve_items, marks, availability,
                resolved.requested_since.isoformat(), resolved.requested_through.isoformat(),
                resolved.cutoff, boundaries)
        if (legacy or (not fusion_selected and local == "theoretical")) and callable(
                getattr(reader, "reference_theoretical_bars", None)):
            from app.reference_trading.saved_theoretical import saved_theoretical
            member_trades = [trade for trade in curve_items
                             if resolved.requested_since.isoformat() <= trade["entry_trading_day"] <= resolved.requested_through.isoformat()]
            theory_bars = reader.reference_theoretical_bars(
                request.product, request.frequency.value, member_trades, resolved.cutoff)
            if manifest.get("reader") == "newow_product_reader_intraday_v3":
                verify_saved_compact_source(manifest, reader.historical_source_evidence(
                    product=request.product, frequency=request.frequency.value,
                    since=date.fromisoformat(manifest["query_since"]),
                    through=date.fromisoformat(manifest["query_through"]),
                    as_of=datetime.fromisoformat(manifest["query_as_of"])))
            extra["theoretical"] = saved_theoretical(member_trades, marks, theory_bars,
                request.strategy.value, resolved.requested_since.isoformat(),
                resolved.requested_through.isoformat())
        if request.include_fusion and (legacy or fusion_selected):
            from app.reference_trading.newow_fusion import PersistedFusionComparison
            fusion = PersistedFusionComparison(self._factory).comparison(
                product=request.product, frequency=request.frequency.value,
                since=resolved.requested_since, through=resolved.requested_through,
                cutoff=resolved.cutoff, reader=reader, limit=request.history_limit,
                cursor=request.fusion_before,
                expected_source_generation=(request.strategy.value, *generation),
                snapshot_token=(fusion_material.token(
                    self._manifest(fusion_material.stream_id, fusion_material.revision_id, fusion_material.seq)[1],
                    since=resolved.requested_since, through=resolved.requested_through,
                    cutoff=resolved.cutoff) if fusion_material is not None else None),
            )
            fusion["fusion_input_sha256"] = fusion["reference_input_sha256"]
            fusion["reference_input_sha256"] = fact_key
            extra["fusion_comparison"] = fusion
        if (legacy or page_mode is not None) and page_materials:
            if legacy or not fusion_selected:
                extra["page_performance"] = project_page_material(page_materials["base"],
                    since=resolved.requested_since.isoformat(), through=resolved.requested_through.isoformat(),
                    selected_mode=page_mode)
            if "fusion_comparison" in extra:
                if "fusion" not in page_materials:
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
                extra["fusion_comparison"]["page_performance"] = project_page_material(page_materials["fusion"],
                    since=resolved.requested_since.isoformat(), through=resolved.requested_through.isoformat(),
                    selected_mode=page_mode)
            return extra
        if legacy or page_mode is not None:
            owns_full = full_read is None and request.frequency.value in {"1m", "5m", "15m", "30m", "60m"}
            full = full_read if full_read is not None else (
                self._page_read(request, reader, manifest, resolved) if
                request.frequency.value in {"1m", "5m", "15m", "30m", "60m"} else read)
            try:
                if legacy or not fusion_selected:
                    extra["page_performance"] = project_page_performance(
                        full, identity, resolved, selected_mode=page_mode)
                if "fusion_comparison" in extra:
                    extra["fusion_comparison"]["page_performance"] = project_page_performance(
                        full, identity, resolved, fusion=True, selected_mode=page_mode)
            finally:
                if owns_full:
                    close = getattr(full, "close", None)
                    if callable(close):
                        close()
        return extra

    def section(self, request, read, identity, reader, fact_key, _page_identity, resolved):
        with ExitStack() as resources:
            return self._section(request, read, identity, reader, fact_key, _page_identity, resolved, resources)

    def _section(self, request, read, identity, reader, fact_key, _page_identity, resolved, resources):
        from guiyi_quant.newow.product_contracts import (
            EvidenceStatus, FeatureRuntimeStatus, FeatureStatus, INTRADAY_PRODUCT_FREQUENCIES, ProductFrequency,
        )
        from app.market_data.newow.product_service import (
            PersistedReferenceSectionValue, SectionDelivery, _has_unresolved_tail_gap,
        )

        matches = self._query.streams(
            strategy=f"newow_{request.strategy.value}", product=request.product,
            frequency=request.frequency.value, mode="historical_replay",
        )
        if not matches:
            raise QueryConflict("NOT_BUILT")
        if len(matches) != 1:
            raise QueryConflict("STREAM_IDENTITY_AMBIGUOUS")
        stream_id = matches[0]["stream_id"]
        since, through, cutoff = (
            resolved.requested_since, resolved.requested_through, resolved.cutoff,
        )
        market_cutoff = cutoff
        from app.reference_trading.page_material_query import select_page_material
        selected_mode = getattr(getattr(request, "reference_mode", None), "value", "") or ""
        base_material = select_page_material(self._factory, stream_id, cutoff=cutoff)
        fusion_material = None
        needs_fusion = (getattr(request, "include_fusion", False)
                        and (not selected_mode or selected_mode.startswith("fusion_")))
        if needs_fusion:
            fusion_routes = self._query.streams(strategy="newow_dual_fusion", product=request.product,
                frequency=request.frequency.value, mode="historical_replay")
            if len(fusion_routes) == 1:
                fusion_material = select_page_material(self._factory, fusion_routes[0]["stream_id"], cutoff=cutoff)
            if fusion_material is not None:
                dependencies = fusion_material.field["binding"].get("fusion_source_dependencies")
                if not isinstance(dependencies, list) or len(dependencies) != 2:
                    raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
                index = {"trend": 0, "oscillation": 1}.get(request.strategy.value)
                if index is not None:
                    dependency = dependencies[index]
                    if dependency.get("stream_id") != stream_id:
                        raise QueryConflict("SOURCE_GENERATION_CONFLICT")
                    base_material = select_page_material(self._factory, stream_id,
                        cutoff=fusion_material.cutoff,
                        generation=(dependency.get("revision_id"), dependency.get("seq")))
                else:
                    base_material = select_page_material(self._factory, stream_id, cutoff=fusion_material.cutoff)
                if base_material is None or base_material.cutoff != fusion_material.cutoff:
                    raise ReferenceReadConflict("REFERENCE_UPDATE_PENDING",
                        saved_through=None, requested_through=market_cutoff)
        head_options = {}
        if base_material is not None:
            _, selected_manifest = self._manifest(stream_id, base_material.revision_id, base_material.seq)
            head_options["snapshot_token"] = base_material.token(selected_manifest,
                since=since, through=through, cutoff=cutoff)
        head = self._query.summary(stream_id, since=since, through=through, cutoff=cutoff, **head_options)
        _, head_manifest = self._manifest(stream_id, head["revision_id"], head["seq"])
        saved_endpoint = base_material.cutoff if base_material is not None else getattr(head_manifest, "computed_through", None)
        if base_material is None and head_manifest.get("reader") == "newow_product_reader_prefix_v5":
            raise QueryConflict("NOT_BUILT")
        if getattr(request, "include_fusion", False) and (not selected_mode or selected_mode.startswith("fusion_")):
            fusion_streams = self._query.streams(strategy="newow_dual_fusion", product=request.product,
                frequency=request.frequency.value, mode="historical_replay")
            if len(fusion_streams) != 1:
                raise QueryConflict("NOT_BUILT")
            fusion_options = {}
            if fusion_material is not None:
                _, selected_fusion_manifest = self._manifest(fusion_material.stream_id,
                    fusion_material.revision_id, fusion_material.seq)
                fusion_options["snapshot_token"] = fusion_material.token(selected_fusion_manifest,
                    since=since, through=through, cutoff=cutoff)
            fusion_head = self._query.summary(fusion_streams[0]["stream_id"], since=since, through=through,
                cutoff=cutoff, **fusion_options)
            _, fusion_manifest = self._manifest(fusion_streams[0]["stream_id"], fusion_head["revision_id"], fusion_head["seq"])
            fusion_endpoint = getattr(fusion_manifest, "computed_through", None)
            if fusion_endpoint is not None and saved_endpoint is not None:
                saved_endpoint = min(saved_endpoint, fusion_endpoint)
        market_endpoint, _ = _completed_reference_window(read, cutoff)
        if market_endpoint is not None:
            market_cutoff = market_endpoint
        updating = (saved_endpoint is not None and market_endpoint is not None
                    and saved_endpoint < market_endpoint)
        if updating:
            from dataclasses import replace
            cutoff = saved_endpoint
            # Resolve the actual trading day from completed MDS inputs. Neither
            # UTC date nor a manifest's planned rank1 tail proves a night-session
            # or partially committed batch's actual end day.
            from app.market_data.newow.product_query import NewowProductQuery
            if base_material is not None:
                saved_day = base_material.through
            else:
                loader = getattr(reader, "load_historical", None) or reader.load
                read = loader(NewowProductQuery(request.product, request.strategy, request.frequency,
                    date.fromisoformat(head_manifest["query_since"]), through,
                    since, through, cutoff), cutoff)
                close = getattr(read, "close", None)
                if callable(close):
                    resources.callback(close)
                _, saved_day = _completed_reference_window(read, cutoff)
            if saved_day is None:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            through = min(through, saved_day)
            resolved = replace(resolved, requested_through=through,
                actual_through=min(resolved.actual_through, through), cutoff=cutoff)
        if base_material is not None and not updating:
            from dataclasses import replace
            cutoff = base_material.cutoff
            resolved = replace(resolved, cutoff=cutoff,
                actual_through=min(resolved.actual_through, base_material.through))
        reference_status = {"status": "updating" if updating else "current",
            "result_through": cutoff.isoformat(), "market_through": market_cutoff.isoformat()}
        minute = request.frequency in (*INTRADAY_PRODUCT_FREQUENCIES, ProductFrequency.MINUTE)
        saved_snapshot = None
        if request.history_before is not None:
            cursor = _decode(request.history_before, kind="record_trades" if minute else "trades")
            saved_snapshot = cursor.get("snapshot")
            if not isinstance(saved_snapshot, str):
                raise QueryConflict("CURSOR_CONFLICT")
        record_since = max(since, through - timedelta(days=364)) if minute else since
        if base_material is not None:
            if saved_snapshot is not None:
                requested_snapshot = _decode(saved_snapshot, kind="snapshot")
                if (requested_snapshot.get("revision"), requested_snapshot.get("seq")) != (base_material.revision_id, base_material.seq):
                    raise QueryConflict("CURSOR_CONFLICT")
            saved_snapshot = base_material.token(head_manifest,
                since=record_since, through=through, cutoff=cutoff)
        page = self._query.trades(
            stream_id, since=record_since, through=through, cutoff=cutoff,
            limit=request.history_limit, snapshot_token=saved_snapshot,
            cursor=request.history_before, entry_since_only=minute,
        )
        snapshot = page["snapshot"]
        if minute:
            # Rewindow only the exact saved generation; record pagination never
            # changes the complete statistics/curve input window.
            saved = _decode(snapshot, kind="snapshot")
            snapshot = _encode({**saved, "since": since.isoformat()})
        stream_identity, manifest = self._manifest(
            stream_id, page["revision_id"], page["seq"],
        )
        saved_endpoint = getattr(manifest, "computed_through", None)
        storage_start = manifest.get("query_since")
        if not isinstance(storage_start, str):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        page_materials = {}
        if base_material is not None:
            base_envelope = base_material.envelope(manifest, stream_identity)
            if type(base_envelope.get("has_unresolved_tail_gap")) is not bool:
                raise QueryConflict("PRESENTATION_CORRUPT")
            self._verify_material_source(stream_identity, manifest, reader,
                owner_keys=self._material_owner_keys(base_envelope),
                saved_through=base_material.cutoff, saved_day=base_material.through,
                requested_through=market_cutoff)
            page_materials["base"] = base_envelope
            if fusion_material is not None:
                fusion_identity, fusion_saved_manifest = self._manifest(fusion_material.stream_id,
                    fusion_material.revision_id, fusion_material.seq)
                fusion_envelope = fusion_material.envelope(fusion_saved_manifest, fusion_identity)
                self._verify_material_source(fusion_identity, fusion_saved_manifest, reader,
                    owner_keys=self._material_owner_keys(fusion_envelope),
                    saved_through=fusion_material.cutoff, saved_day=fusion_material.through,
                    requested_through=market_cutoff)
                page_materials["fusion"] = fusion_envelope
        elif manifest.get("reader") == "newow_product_reader_intraday_v3":
            try:
                source_through = date.fromisoformat(manifest["query_through"])
                source_as_of = datetime.fromisoformat(manifest["query_as_of"])
                evidence = reader.historical_source_evidence(
                    product=request.product, frequency=request.frequency.value,
                    since=date.fromisoformat(storage_start), through=source_through,
                    as_of=source_as_of,
                )
                verify_saved_compact_source(manifest, evidence)
                if resolved.actual_through > source_through or cutoff > source_as_of:
                    raise ReferenceReadConflict("REFERENCE_UPDATE_PENDING",
                        saved_through=source_as_of, requested_through=cutoff)
            except ReferenceReadConflict:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from exc
        else:
            try:
                source_request = HistoricalStreamRequest(
                    stream_identity, date.fromisoformat(storage_start),
                    resolved.actual_through, cutoff,
                )
                input_reader = MarketDataHistoricalInputReader(
                    newow_reader=reader, subing_service=None,
                )
                source = input_reader.plan_stream(source_request)
            except (TypeError, ValueError) as exc:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from exc
            try:
                verify_saved_input_prefix(
                    manifest, source.dependency_manifest, resolved.actual_through,
                    frozenset((bar.physical_contract, bar.owner_segment_id)
                              for bar in source.bars if bar.strategy_input),
                )
            except QueryConflict:
                if saved_endpoint is not None and verified_saved_extension(
                    manifest, source.dependency_manifest, saved_endpoint.date(),
                ):
                    raise ReferenceReadConflict("REFERENCE_UPDATE_PENDING",
                        saved_through=saved_endpoint, requested_through=cutoff) from None
                raise ReferenceReadConflict("SOURCE_IDENTITY_UNVERIFIED",
                    saved_through=saved_endpoint, requested_through=cutoff) from None
            finally:
                input_reader.release_snapshot(source)
        # A cache hit is useful only after a fresh saved-generation and source
        # validation above. The process cache is never an authority for either.
        generation = (stream_id, page["revision_id"], page["seq"])
        selected_mode = request.reference_mode.value if getattr(request, "reference_mode", None) is not None else None
        selected_key = ("selected", selected_mode, request.fusion_before) if selected_mode is not None else None
        from app.reference_trading.contracts import manifest_sha256
        cache_identity = sha256(json.dumps({
            "stream": stream_id, "revision": page["revision_id"], "seq": page["seq"],
            "snapshot": snapshot, "since": since.isoformat(), "through": through.isoformat(),
            "cutoff": cutoff.isoformat(), "fact": fact_key,
            "include_fusion": getattr(request, "include_fusion", False) if selected_mode is None else None,
            "fusion_before": getattr(request, "fusion_before", None) if selected_mode is None else None,
            "manifest": manifest_sha256(manifest),
        }, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        cache_key = f"persisted-reference-complete:{cache_identity}"
        cached = self._cache.get(cache_key, ("complete",), touch=False) if self._cache is not None else None
        if (isinstance(cached, _CompletePresentation) and cached.generation == generation
                and (selected_mode is None or cached.materials is not None)):
            items = []
            for saved_item in page["items"]:
                item = cached.items_by_saved_id.get(saved_item["reference_trade_id"])
                if item is None:
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
                items.append(item)
            from app.market_data.newow.product_service import PersistedReferenceSectionValue, SectionDelivery
            extra = {}
            selected_missing = False
            if selected_key is not None:
                extra = self._cache.get(cache_key, selected_key, touch=False) if self._cache is not None else None
                if extra is None:
                    selected_missing = True
                    materials = cached.materials
                    extra = self._selected_projection(
                        request, read, identity, reader, fact_key, resolved, generation,
                        materials["snapshot"], manifest, materials["curve_items"],
                        materials["availability"], materials["boundaries"],
                        page_materials=page_materials, fusion_material=fusion_material,
                    )
            delivery = SectionDelivery("delivered", cached.status, PersistedReferenceSectionValue(
                {**cached.payload, **extra, "reference_status": reference_status, "items": items, "next_before": page["next_cursor"]}, generation,
            ))
            self.validate_cached_generation(delivery, reader=reader)
            if selected_missing and self._cache is not None:
                self._cache.put(cache_key, selected_key, extra)
            elif self._cache is not None:
                self._cache.get(cache_key, ("complete",))
            return delivery
        stats = self._query.summary(
            stream_id, since=since, through=through, cutoff=cutoff,
            snapshot_token=snapshot,
        )
        # Curve facts use the same saved snapshot, independently of record pagination.
        if minute:
            curve_items = self._query.complete_trades(stream_id, since=since, through=through,
                cutoff=cutoff, snapshot_token=snapshot)
        else:
            curve_items = []
            curve_cursor = None
            while True:
                curve_page = self._query.trades(
                    stream_id, since=since, through=through, cutoff=cutoff,
                    snapshot_token=snapshot, cursor=curve_cursor, limit=200,
                )
                curve_items.extend(curve_page["items"])
                if len(curve_items) > 100_000:
                    raise QueryConflict("PRESENTATION_BUDGET_EXCEEDED")
                curve_cursor = curve_page["next_cursor"]
                if curve_cursor is None:
                    break
        page_ids = {item["reference_trade_id"] for item in page["items"]}
        facts = self._reference_facts(
            stream_id, snapshot, since, date.fromisoformat(storage_start),
            resolved.actual_through, cutoff, manifest, minute,
            getattr(reader, "_check_cancelled", None),
        )
        if base_material is not None:
            from app.reference_trading.page_material_query import material_interruptions
            from types import SimpleNamespace
            saved_gaps = material_interruptions(page_materials["base"], identity, cutoff)
            read = SimpleNamespace(owners=read.owners, data_interruptions=saved_gaps,
                replay_bars=(), as_of=cutoff, frequency=request.frequency, sources=read.sources)
        availability = [point for point in facts["availability"] if point["trading_day"] >= since.isoformat()]
        # All frequencies retain physical warmup facts. Only the authoritative
        # rank1 owner may contribute availability for a trading day.
        availability = reader.reference_owned_points(request.product, availability, read.owners)
        boundaries = facts["boundary"]
        hints = facts["hint"]
        actions = facts["action"]
        boundary_by_owner = {
            (item["value"]["physical_contract"], item["value"]["owner_segment_id"]): item
            for item in boundaries
        }
        for item in curve_items:
            if item["status"] not in ("OPEN", "CLOSED") and item.get("interrupted_at") is None:
                boundary = boundary_by_owner.get((item["physical_contract"], item["owner_segment_id"]))
                if boundary is None:
                    raise QueryConflict("PRESENTATION_CORRUPT")
                item["interrupted_at"] = boundary["value"]["bar_end"]
        hint_ids = self._hint_ids(curve_items, actions, hints, cutoff)
        output_items = []
        for item in curve_items:
            status = item["status"]
            has_prior_mark = item.get("prior_mark_bar_end") is not None
            reason = None
            if status not in ("OPEN", "CLOSED"):
                reason = (
                    "SOURCE_PRICE_UNAVAILABLE" if status == "DATA_INTERRUPTED"
                    else "OWNER_BOUNDARY"
                ) if has_prior_mark else "OWNER_BOUNDARY_MARK_UNAVAILABLE"
            output_items.append({
                "reference_trade_id": item["public_reference_trade_id"],
                "product": request.product, "strategy_code": request.strategy.value,
                "frequency": request.frequency.value,
                "physical_contract": item["physical_contract"],
                "segment_id": item["owner_segment_id"],
                "calculation_segment_id": item["calculation_segment_id"],
                "formula_versions": list(identity.formula_versions),
                "reference_model_version": matches[0]["reference_model_version"],
                "futures_adaptation_version": matches[0]["futures_adaptation_version"],
                **({"input_quality_policy": identity.input_quality_policy.value}
                   if identity.input_quality_policy.value != "newow_input_quality_v1" else {}),
                "entry_signal_id": item["entry_action_id"],
                "entry_sequence": item["entry_sequence"],
                "entry_bar_end": item["entry_bar_end"],
                "entry_trading_day": item["entry_trading_day"],
                "entry_reference_price": item["entry_reference_price"],
                "exit_signal_id": item["exit_action_id"],
                "exit_bar_end": item["exit_bar_end"],
                "exit_trading_day": item["exit_trading_day"],
                "exit_reference_price": item["exit_reference_price"],
                "status": status, "holding_bars": item["holding_bars"],
                "reference_return_pct": item["reference_return"],
                "mark_bar_end": item["mark_bar_end"] if status == "OPEN" else item.get("prior_mark_bar_end"),
                "mark_reference_price": item["mark_reference_price"] if status == "OPEN" else item.get("prior_mark_reference_price"),
                "mark_change_pct": item["mark_return"] if status == "OPEN" else item.get("prior_mark_change_pct"),
                "interrupted_at": item.get("interrupted_at"),
                "interruption_reason": reason,
                "statistics_membership": "initial_before_window" if item["entry_trading_day"] < since.isoformat() else "entry_in_window_v1",
                "hint_ids": hint_ids.get(item["reference_trade_id"], []),
            })
        intervals = self._coverage(availability, read.data_interruptions, since, resolved.actual_through)
        unavailable = sorted({
            gap.trading_day.isoformat() for gap in read.data_interruptions
            if since <= gap.trading_day <= resolved.actual_through
        })
        payload = {
            "reference_status": reference_status,
            "performance_since": since.isoformat(),
            "performance_through": through.isoformat(),
            "actual_available_through": resolved.actual_through.isoformat(),
            "reference_cutoff": cutoff.isoformat(),
            "reference_input_sha256": fact_key,
            "history_coverage": "PARTIAL" if any(i["status"] != "VALID" for i in intervals) else "FULL",
            "record_since": record_since.isoformat(),
            "records_window_limited": record_since > since,
            "unavailable_days": unavailable, "coverage_intervals": intervals,
            "summary": {**{key: stats[key] for key in (
                "closed_count", "win_count", "loss_count", "flat_count",
                "win_rate_pct", "mean_return_pct", "sum_return_percentage_points",
                "open_count", "interrupted_count", "rollover_interrupted_count",
                "data_interrupted_count", "initial_count",
            )}, "membership_policy": "entry_in_window_v1"},
            "items": [item for item, raw in zip(output_items, curve_items)
                      if raw["reference_trade_id"] in page_ids],
            "curve_trades": [item for item in output_items
                             if item["status"] == "CLOSED"
                             and item["statistics_membership"] == "entry_in_window_v1"],
            "next_before": page["next_cursor"],
            "executable": False, "auto_order": False,
            "storage_mode": "persisted",
            "allowed_uses": ["page_parity_reference", "research_display"],
        }
        payload["result_identity_sha256"] = sha256(json.dumps({
            "generation": generation, "summary": payload["summary"],
            "records": output_items, "coverage": intervals,
        }, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        base_payload = dict(payload)
        # Read the complete persisted window for readiness even when no page
        # estimate is requested: the bounded display read can miss a tail gap.
        full = read if base_material is not None else (
            self._page_read(request, reader, manifest, resolved) if minute else read)
        try:
            selected_extra = self._selected_projection(
                request, read, identity, reader, fact_key, resolved, generation,
                snapshot, manifest, curve_items, availability, boundaries, full_read=full,
                page_materials=page_materials, fusion_material=fusion_material,
            )
            payload.update(selected_extra)
            warming = (
                not resolved.complete or (page_materials["base"]["has_unresolved_tail_gap"]
                    if base_material is not None else _has_unresolved_tail_gap(full))
                or bool(availability and availability[-1]["value"].get("last_status", availability[-1]["value"]["status"]) != "ready")
            )
        finally:
            if minute:
                close = getattr(full, "close", None)
                if callable(close):
                    close()
        status = FeatureStatus(
            FeatureRuntimeStatus.WARMING if warming else FeatureRuntimeStatus.READY,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
            (resolved.reason_code or "NEWOW_REFERENCE_WINDOW_PARTIAL") if warming else None,
        )
        delivery = SectionDelivery(
            "delivered", status, PersistedReferenceSectionValue(payload, generation),
        )
        # The selected fusion or its dependencies can advance while the base
        # projection is being derived. Recheck the complete result before any
        # cache admission, including a fresh fusion source proof.
        self.validate_cached_generation(delivery, reader=reader)
        if self._cache is not None:
            self._cache.put(cache_key, ("complete",), _CompletePresentation(
                {key: item for key, item in (payload if selected_mode is None else base_payload).items()
                 if key not in {"items", "next_before"}},
                {raw["reference_trade_id"]: item for raw, item in zip(curve_items, output_items, strict=True)},
                status, generation,
                ({"snapshot": snapshot, "curve_items": curve_items,
                  "availability": availability, "boundaries": boundaries}
                 if selected_mode is not None else None),
            ), related_values={selected_key: selected_extra} if selected_key is not None else None)
        return delivery
