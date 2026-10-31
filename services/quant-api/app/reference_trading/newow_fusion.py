"""Historical fusion of verified saved source actions over shared market facts."""

from __future__ import annotations

from app.reference_trading.fingerprint_proof import (
    SEMANTIC_READERS, fingerprint_count,
)

from app.reference_trading.checkpoint import checkpoint_watermark

from dataclasses import dataclass

from guiyi_quant.newow.fusion_reference import (
    FusionReferenceReplayState,
    build_fusion_stream_identity,
    fusion_trade_id,
)
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION
from guiyi_quant.newow.product_contracts import (
    ProductBar,
    ProductFrequency,
    ProductStrategy,
    StrategyAction,
    TradeEligibility,
)
from guiyi_quant.reference_trading import (
    ActionKind,
    CompletedReferenceBar,
    ReferenceAction,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from app.reference_trading.contracts import SourceAction, manifest_sha256
from app.reference_trading.presentation import presentation_point


@dataclass(frozen=True, slots=True)
class FusionHistoricalPayload:
    bar: ProductBar
    source_actions: tuple[StrategyAction, ...]


def fusion_input_policy(stream):
    from guiyi_quant.newow.product_identity import InputQualityPolicy, futures_adaptation_version

    for policy in InputQualityPolicy:
        try:
            if futures_adaptation_version(stream.frequency, policy) == stream.futures_adaptation_version:
                return policy
        except ValueError:
            continue
    raise ValueError("REFERENCE_FUSION_STREAM_IDENTITY_CONFLICT")


def advance_fusion_step(stream, checkpoint, item, presentation, *, observed_at=None):
    if (
        not isinstance(checkpoint.strategy_state, FusionReferenceReplayState)
        or checkpoint.reference_state is None
    ):
        raise ValueError("REFERENCE_FUSION_CHECKPOINT_INVALID")
    if stream != build_fusion_stream_identity(
        stream.product, stream.frequency, recording_mode=stream.recording_mode,
        observation_policy_version=stream.observation_policy_version,
        input_quality_policy=fusion_input_policy(stream),
    ):
        raise ValueError("REFERENCE_FUSION_STREAM_IDENTITY_CONFLICT")
    prior = checkpoint.reference_state
    if not item.strategy_input:
        transition = reduce_reference(prior, boundaries=item.boundaries)
        return (
            AdapterCheckpoint(
                checkpoint.strategy_state,
                checkpoint_watermark(checkpoint, item, transition.state),
                item.fingerprint,
                item.physical_contract,
                item.owner_segment_id,
                item.calculation_segment_id,
                stream,
                transition.state,
            ),
            (),
            transition,
        )
    payload = item.payload
    if not isinstance(payload, FusionHistoricalPayload):
        raise ValueError("REFERENCE_FUSION_PAYLOAD_INVALID")
    bar = payload.bar
    if (
        bar.frequency.value != stream.frequency
        or bar.bar.product != stream.product
        or bar.bar.bar_end != item.bar_end
        or bar.bar.trading_day != item.trading_day
        or bar.bar.close != item.reference_price
        or (bar.bar.physical_contract, bar.bar.segment_id, bar.calculation_segment_id)
        != (item.physical_contract, item.owner_segment_id, item.calculation_segment_id)
    ):
        raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
    expected = (
        item.physical_contract,
        item.owner_segment_id,
        item.calculation_segment_id,
    )
    source_identities = {
        strategy: build_product_identity(stream.product, strategy, bar.frequency, input_quality_policy=fusion_input_policy(stream))
        for strategy in (ProductStrategy.TREND, ProductStrategy.OSCILLATION)
    }
    candidates = []
    for action in payload.source_actions:
        if (
            action.identity != source_identities.get(action.identity.strategy)
            or action.bar_end != item.bar_end
        ):
            raise ValueError("REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT")
        if (
            action.physical_contract,
            action.segment_id,
            action.calculation_segment_id,
        ) != expected:
            raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
        if action.trade_eligibility in (
            TradeEligibility.ELIGIBLE,
            TradeEligibility.NO_ELIGIBLE_ENTRY,
            TradeEligibility.INITIAL_CLEAR_NO_ENTRY,
        ):
            candidates.append(action)
    candidates.sort(
        key=lambda action: (
            0 if action.identity.strategy is ProductStrategy.OSCILLATION else 1,
            action.sequence,
            action.signal_id,
        )
    )
    holding = prior.open_trade
    if (
        holding is not None
        and (
            holding.physical_contract,
            holding.owner_segment_id,
            holding.calculation_segment_id,
        )
        != expected
    ):
        holding = None
    selected = []
    sells = [action for action in candidates if action.kind.value == "CLEAR"]
    buys = [action for action in candidates if action.kind.value == "BUILD"]
    if bar.bar.observation_eligible:
        if holding is not None and sells:
            selected.append((sells[0], ActionKind.CLOSE, holding.entry_action_id))
            holding = None
        if holding is None and buys:
            selected.append((buys[0], ActionKind.OPEN_LONG, None))
    actions = []
    for sequence, (source, kind, entry_id) in enumerate(selected):
        action = ReferenceAction(
            stream,
            source.signal_id,
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            item.bar_end,
            item.trading_day,
            sequence,
            kind,
            source.reference_price,
            entry_id,
            "newow_fusion_source_reference",
        )
        actions.append(action)
        if presentation is not None:
            presentation.append(
                presentation_point(
                    kind="action",
                    value={
                        "bar_end": item.bar_end,
                        "source": source.identity.strategy.value,
                        "source_signal_id": source.signal_id,
                        "kind": kind.value,
                    },
                    trading_day=item.trading_day,
                    formula_versions=stream.formula_versions,
                )
            )
            if kind is ActionKind.OPEN_LONG:
                public = fusion_trade_id(
                    source_identities[ProductStrategy.TREND],
                    source_identities[ProductStrategy.OSCILLATION],
                    source.signal_id,
                )
                presentation.append(
                    presentation_point(
                        kind="trade_identity",
                        value={
                            "bar_end": item.bar_end,
                            "source_action_id": source.signal_id,
                            "public_trade_id": public,
                        },
                        trading_day=item.trading_day,
                        formula_versions=stream.formula_versions,
                    )
                )
    completed = (
        CompletedReferenceBar(
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            item.bar_end,
            item.trading_day,
            item.reference_price,
        )
        if bar.bar.observation_eligible
        else None
    )
    transition = reduce_reference(
        prior,
        actions=tuple(actions),
        boundaries=item.boundaries,
        completed_bar=completed,
    )
    if presentation is not None:
        state = ("BUILD" if actions[-1].kind is ActionKind.OPEN_LONG else "CLEAR") if actions else (
            "HOLD" if transition.state.open_trade else "FLAT")
        presentation.append(presentation_point(kind="indicator", trading_day=item.trading_day,
            formula_versions=stream.formula_versions, value={
                "version":"newow_bar_state_v1", "product":stream.product, "strategy":"dual_fusion",
                "frequency":stream.frequency, "bar_end":item.bar_end,
                "physical_contract":item.physical_contract, "segment_id":item.owner_segment_id,
                "calculation_segment_id":item.calculation_segment_id,
                "source_identity":bar.bar.source_identity, "source_bar_sha256":bar.source_bar_sha256,
                "input_quality_policy":fusion_input_policy(stream), "main_state":state,
                "availability":{"status":"evidence_required", "reason_code":"SOURCE_STATE_NOT_CAPTURED"},
                "main_values":{}, "action_ids":[action.source_action_id for action in actions], "hint_ids":[],
            }))
    return (
        AdapterCheckpoint(
            checkpoint.strategy_state,
            checkpoint_watermark(checkpoint, item, transition.state),
            item.fingerprint,
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            stream,
            transition.state,
        ),
        tuple(SourceAction(action, observed_at) for action in actions),
        transition,
    )


def decode_source_action(value, identity):
    from datetime import date, datetime
    from decimal import Decimal
    from app.reference_trading.presentation import _wire

    if not isinstance(value, dict) or value.get("identity") != _wire(identity):
        raise ValueError("REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT")
    try:
        action = StrategyAction(
            identity=identity,
            physical_contract=value["physical_contract"],
            segment_id=value["segment_id"],
            bar_end=datetime.fromisoformat(value["bar_end"]),
            trading_day=date.fromisoformat(value["trading_day"]),
            kind=value["kind"],
            reference_price=Decimal(value["reference_price"]),
            anchor_price=Decimal(value["anchor_price"])
            if value["anchor_price"] is not None
            else None,
            sequence=value["sequence"],
            related_build_id=value["related_build_id"],
            source_marker_id=value["source_marker_id"],
            source_related_marker_ids=tuple(value["source_related_marker_ids"]),
            trade_eligibility=value["trade_eligibility"],
            calculation_segment_id=value["calculation_segment_id"],
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise ValueError("REFERENCE_FUSION_SOURCE_ACTION_CORRUPT") from error
    if _wire(action) != value:
        raise ValueError("REFERENCE_FUSION_SOURCE_ACTION_CORRUPT")
    return action


class SavedFusionSources:
    """Load both published base projections at one exact frozen input scope."""

    def __init__(self, session_factory, *, check_cancelled=None):
        self._check_cancelled = check_cancelled
        from app.reference_trading.persisted_newow import PersistedNewowReference

        self._persisted = PersistedNewowReference(session_factory)
        self._query = self._persisted._query

    def __call__(self, request, market_manifest, *, source_manifests=None,
                 source_integrity=None, target_completed_through=None,
                 target_trading_day=None):
        from contextlib import nullcontext
        from datetime import date, datetime
        from guiyi_quant.newow.product_contracts import ProductFrequency
        from app.reference_trading.fusion_action_spool import FusionActionSpool
        from app.reference_trading.manifest_storage import verified_manifest_scope

        target_cutoff = target_completed_through or request.as_of
        actions = FusionActionSpool()
        dependencies = []

        # The per-source frame releases its manifest and page material before
        # the next strategy starts; only actions and small dependency proofs remain.
        def read_one(strategy, expected_manifest):
            streams = self._query.streams(
                strategy=f"newow_{strategy.value}",
                product=request.identity.product,
                frequency=request.identity.frequency,
            )
            if len(streams) != 1:
                raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
            stream_id = streams[0]["stream_id"]
            summary = self._query.summary(
                stream_id,
                since=request.since,
                through=request.through,
                cutoff=target_cutoff,
            )
            source_identity, manifest = self._persisted._manifest(
                stream_id, summary["revision_id"], summary["seq"]
            )
            if expected_manifest.get("reader") == "newow_product_reader_prefix_v5":
                from app.reference_trading.page_material_query import select_page_material
                from app.reference_trading.page_material_storage import validate_input_integrity

                if (not isinstance(target_completed_through, datetime)
                        or target_completed_through.tzinfo is None
                        or target_completed_through.utcoffset() is None
                        or type(target_trading_day) is not date
                        or target_completed_through > request.as_of):
                    raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
                count = fingerprint_count(manifest.get("input_fingerprints"))
                material = select_page_material(
                    self._persisted._factory, stream_id, cutoff=target_cutoff,
                    generation=(summary["revision_id"], summary["seq"]),
                )
                record = getattr(manifest, "input_integrity", None)
                digest = manifest_sha256(manifest)
                if (material is None or material.cutoff != target_cutoff
                        or material.through != target_trading_day
                        or material.seq != summary["seq"]
                        or material.revision_id != summary["revision_id"]
                        or type(manifest.get("input_count", count)) is not int
                        or manifest.get("input_count", count) != count
                        or count <= 0 or not isinstance(record, dict)
                        or source_integrity is None
                        or record.get("source_integrity") != source_integrity):
                    raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
                expected_binding = {
                    "schema": "reference_input_integrity_v1",
                    "stream_id": stream_id, "revision_id": summary["revision_id"],
                    "seq": summary["seq"], "manifest_sha256": digest,
                    "source_token": digest,
                    "source_integrity": source_integrity,
                    "request": {
                        "product": request.identity.product.lower(),
                        "frequency": request.identity.frequency,
                        "since": request.since.isoformat(),
                        "through": request.through.isoformat(),
                        "as_of": request.as_of.isoformat(),
                    },
                }
                try:
                    validate_input_integrity(record, expected_binding=expected_binding)
                    envelope = material.envelope(manifest, source_identity)
                    if material.field["binding"]["end_input_index"] != count:
                        raise ValueError("incomplete final material")
                    del envelope
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY") from error
            required = ("reader", "query_since", "quality_policy")
            if request.identity.frequency == "1d":
                from app.reference_trading.inputs import NEWOW_D1_REFERENCE_BOUNDARY_POLICY
                if expected_manifest.get("reference_boundary_policy_version") != NEWOW_D1_REFERENCE_BOUNDARY_POLICY:
                    raise ValueError("REFERENCE_FUSION_SOURCE_SNAPSHOT_CONFLICT")
                required = (*required, "reference_boundary_policy_version")
            shared = (
                "query_through", "query_as_of", "source_evidence_sha256", "input_count",
                "input_fingerprints", "calendar_session_effective_fingerprints",
                "calendar_session_source_evidence", "rank1", "boundaries", "data_interruptions",
                "lifecycle_owners", "market_source_identity", "input_policy_version",
            )
            for key in (*required, *(key for key in shared if key in expected_manifest)):
                if manifest.get(key) is None or manifest.get(key) != expected_manifest.get(key):
                    raise ValueError("REFERENCE_FUSION_SOURCE_SNAPSHOT_CONFLICT")
            dependencies.append(
                {
                    "stream_id": stream_id,
                    "revision_id": summary["revision_id"],
                    "seq": summary["seq"],
                    "dependency_digest": manifest_sha256(manifest),
                    "snapshot": summary["snapshot"],
                }
            )
            identity = build_product_identity(
                request.identity.product,
                strategy,
                ProductFrequency(request.identity.frequency),
                input_quality_policy=fusion_input_policy(request.identity),
            )
            if (
                source_identity.formula_versions != identity.formula_versions
                or source_identity.profile_id != identity.profile_id
            ):
                raise ValueError("REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT")
            from contextlib import closing
            with closing(self._query.historical_actions(
                stream_id,
                snapshot_token=summary["snapshot"],
                since=date.min,
                through=request.through,
                cutoff=target_cutoff,
                input_count=manifest.get("input_count", fingerprint_count(manifest.get("input_fingerprints", []))),
                check_cancelled=self._check_cancelled,
            )) as facts:
                for point in facts:
                    action = decode_source_action(point["value"], identity)
                    actions.append(action)

        try:
            for strategy in (ProductStrategy.TREND, ProductStrategy.OSCILLATION):
                expected_manifest = (source_manifests or {}).get(strategy.value, market_manifest)
                scope = (verified_manifest_scope(expected_manifest, manifest_sha256(expected_manifest))
                         if expected_manifest.get("reader") == "newow_product_reader_prefix_v5"
                         else nullcontext())
                with scope:
                    read_one(strategy, expected_manifest)
            return actions, dependencies
        except BaseException:
            actions.close()
            raise


class PersistedFusionComparison:
    """Independent fusion revision, complete curve and bounded one-year records."""

    def __init__(self, session_factory):
        from app.reference_trading.persisted_newow import PersistedNewowReference

        self._persisted = PersistedNewowReference(session_factory)
        self._query = self._persisted._query

    @staticmethod
    def verify_saved_source(identity, manifest, *, product, frequency, through, cutoff, reader, persisted=None):
        """Freshly verify the saved fusion source for calculations and cache hits."""
        from datetime import date, datetime
        from app.reference_trading.query import QueryConflict
        from app.reference_trading.source_identity import verify_saved_compact_source

        if manifest.get("source_reader") == "newow_product_reader_prefix_v5":
            from app.reference_trading.page_material_query import PageMaterialSnapshot
            generation = getattr(manifest, "generation", None)
            field = getattr(manifest, "page_material", None)
            if persisted is None or generation is None or not isinstance(field, dict):
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            try:
                binding = field["binding"]
                material = PageMaterialSnapshot(*generation,
                    datetime.fromisoformat(binding["cutoff"]),
                    date.fromisoformat(binding["result_trading_day"]), field)
                if material.cutoff != cutoff:
                    raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
                envelope = material.envelope(manifest, identity)
                persisted._verify_material_source(identity, manifest, reader,
                    owner_keys=persisted._material_owner_keys(envelope),
                    saved_through=material.cutoff, saved_day=material.through,
                    requested_through=cutoff)
                return
            except (KeyError, TypeError, ValueError) as error:
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from error
        try:
            source_through = date.fromisoformat(manifest["query_through"])
            source_cutoff = datetime.fromisoformat(manifest["query_as_of"])
            if (
                manifest.get("reader") not in {
                    "newow_fusion_saved_sources_v1", "newow_fusion_saved_sources_v2", "newow_fusion_saved_sources_v3"
                }
                or through > source_through
                or cutoff > source_cutoff
            ):
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
            source_reader = manifest.get("source_reader", "newow_product_reader_intraday_v3")
            if source_reader == "newow_product_reader_intraday_v3":
                if manifest["reader"] != "newow_fusion_saved_sources_v1":
                    raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
                proof = reader.historical_source_evidence(
                    product=product, frequency=frequency,
                    since=date.fromisoformat(manifest["query_since"]),
                    through=source_through, as_of=source_cutoff,
                )
                verify_saved_compact_source({**manifest, "reader": source_reader}, proof)
            else:
                from dataclasses import replace
                from app.reference_trading.inputs import MarketDataHistoricalInputReader
                from app.reference_trading.planning import HistoricalStreamRequest
                from app.reference_trading.source_identity import verify_saved_input_prefix
                base_identity = build_product_identity(product, ProductStrategy.TREND,
                    ProductFrequency(frequency), input_quality_policy=fusion_input_policy(identity))
                source_stream = replace(identity, strategy_code="newow_trend",
                    formula_versions=base_identity.formula_versions, profile_id=base_identity.profile_id,
                    reference_model_version=REFERENCE_MODEL_VERSION)
                input_reader = MarketDataHistoricalInputReader(newow_reader=reader, subing_service=None)
                with input_reader.planned_stream(HistoricalStreamRequest(
                    source_stream, date.fromisoformat(manifest["query_since"]),
                    through, cutoff,
                )) as source:
                    source_manifest = {**manifest, "reader": source_reader,
                        "formula_versions": list(base_identity.formula_versions),
                        "reference_model_version": source_stream.reference_model_version}
                    if manifest["reader"] in {"newow_fusion_saved_sources_v2", "newow_fusion_saved_sources_v3"}:
                        from app.reference_trading.inputs import _stream_manifest_sha256
                        execution = manifest.get("input_fingerprints")
                        shadow = manifest.get("source_input_fingerprints")
                        if (
                            fingerprint_count(execution) == 0
                            or fingerprint_count(shadow) != fingerprint_count(execution)
                            or type(manifest.get("input_count")) is not int
                            or manifest["input_count"] != fingerprint_count(execution)
                            or manifest.get("input_sha256") != _stream_manifest_sha256(execution)[0]
                        ):
                            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
                        source_manifest["input_fingerprints"] = shadow
                    verify_saved_input_prefix(source_manifest,
                        source.dependency_manifest, through,
                        frozenset((bar.physical_contract, bar.owner_segment_id) for bar in source.bars if bar.strategy_input))
        except (KeyError, TypeError, ValueError) as error:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from error

    def comparison(
        self,
        *,
        product,
        frequency,
        since,
        through,
        cutoff,
        reader,
        limit=200,
        cursor=None,
        expected_source_generation=None,
        snapshot_token=None,
    ):
        from datetime import date, timedelta
        from app.reference_trading.query import QueryConflict, _decode, _encode

        matches = self._query.streams(
            strategy="newow_dual_fusion", product=product, frequency=frequency
        )
        if len(matches) != 1:
            raise QueryConflict(
                "NOT_BUILT" if not matches else "STREAM_IDENTITY_AMBIGUOUS"
            )
        stream = matches[0]
        stats = self._query.summary(
            stream["stream_id"], since=since, through=through, cutoff=cutoff,
            **({"snapshot_token": snapshot_token} if snapshot_token is not None else {}),
        )
        identity, manifest = self._persisted._manifest(
            stream["stream_id"], stats["revision_id"], stats["seq"]
        )
        self.verify_saved_source(identity, manifest, product=product, frequency=frequency,
                                 through=through, cutoff=cutoff, reader=reader, persisted=self._persisted)
        dependencies = manifest.get("source_dependencies")
        if not isinstance(dependencies, list) or len(dependencies) != 2:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        groups = []
        for strategy, dependency in zip(
            (ProductStrategy.TREND, ProductStrategy.OSCILLATION), dependencies
        ):
            if (manifest.get("source_reader") not in SEMANTIC_READERS
                    and expected_source_generation is not None and strategy.value == expected_source_generation[0]):
                if (dependency.get("stream_id"), dependency.get("revision_id"), dependency.get("seq")) != tuple(expected_source_generation[1:]):
                    raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            bases = self._query.streams(
                strategy=f"newow_{strategy.value}", product=product, frequency=frequency
            )
            if len(bases) != 1 or any(
                bases[0].get(key) != dependency.get(other)
                for key, other in (
                    ("stream_id", "stream_id"),
                    *(((("active_revision_id", "revision_id"), ("latest_seq", "seq")))
                      if manifest.get("source_reader") not in SEMANTIC_READERS else ()),
                )
            ):
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            _, saved = self._persisted._manifest(
                dependency["stream_id"], dependency["revision_id"], dependency["seq"]
            )
            if manifest_sha256(saved) != dependency.get("dependency_digest"):
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            snapshot_options = {}
            if manifest.get("source_reader") in SEMANTIC_READERS:
                token = _decode(dependency["snapshot"], kind="snapshot")
                token.update(since=since.isoformat(), through=through.isoformat(), cutoff=cutoff.isoformat())
                snapshot_options["snapshot_token"] = _encode(token)
            base = self._query.summary(
                dependency["stream_id"], since=since, through=through, cutoff=cutoff,
                **snapshot_options,
            )
            if base["revision_id"] != dependency["revision_id"] or base["seq"] != dependency["seq"]:
                raise QueryConflict("SOURCE_GENERATION_CONFLICT")
            groups.append(
                self._group(strategy.value, bases[0]["reference_model_version"], base)
            )
        groups.append(self._group("fusion", identity.reference_model_version, stats))
        record_since = through - timedelta(days=364)
        revision = manifest_sha256(
            {
                "snapshot": stats["snapshot"],
                "dependencies": dependencies,
                "record_since": record_since.isoformat(),
                "record_through": through.isoformat(),
            }
        )
        inner_cursor = None
        if cursor is not None:
            token = _decode(cursor, kind="fusion_records")
            if token.get("reference_revision") != revision or not isinstance(
                token.get("cursor"), str
            ):
                raise QueryConflict("CURSOR_CONFLICT")
            inner_cursor = token["cursor"]
        record_snapshot = _decode(stats["snapshot"], kind="snapshot")
        record_snapshot["since"] = record_since.isoformat()
        record_snapshot = _encode(record_snapshot)
        page = self._query.trades(
            stream["stream_id"],
            since=record_since,
            through=through,
            cutoff=cutoff,
            snapshot_token=record_snapshot,
            limit=limit,
            cursor=inner_cursor,
            entry_since_only=True,
        )
        facts = self._query.presentation_facts(
            stream["stream_id"],
            snapshot_token=stats["snapshot"],
            since=date.min,
            through=through,
            cutoff=cutoff,
            kinds=("action",),
            max_points=200_000,
            check_cancelled=getattr(reader, "_check_cancelled", None),
        )
        sources = {
            point["value"]["source_signal_id"]: point["value"]["source"]
            for point in facts["action"]
        }
        curve = [
            self._trade(item, sources, since, identity.reference_model_version)
            for item in self._query.complete_trades(
                stream["stream_id"],
                since=since,
                through=through,
                cutoff=cutoff,
                snapshot_token=stats["snapshot"],
            )
            if item["status"] == "CLOSED"
        ]
        return {
            "snapshot_schema": "newow_fusion_reference_snapshot_v2",
            "reference_revision": revision,
            "summary": groups[-1],
            "curve": curve,
            "source_profiles": [
                build_product_identity(
                    product, strategy, ProductFrequency(frequency),
                    input_quality_policy=fusion_input_policy(identity),
                ).profile_id
                for strategy in (ProductStrategy.TREND, ProductStrategy.OSCILLATION)
            ],
            "product": product,
            "frequency": frequency,
            "reference_model_version": identity.reference_model_version,
            "reference_input_sha256": manifest["input_sha256"],
            "performance_since": since.isoformat(),
            "performance_through": through.isoformat(),
            "reference_cutoff": cutoff.isoformat(),
            "source_formula_versions": list(identity.formula_versions),
            "page_parity": True,
            "executable": False,
            "groups": groups,
            "items": [
                self._trade(item, sources, since, identity.reference_model_version)
                for item in page["items"]
            ],
            "records_truncated": False,
            "record_since": record_since.isoformat(),
            "record_through": through.isoformat(),
            "next_cursor": _encode(
                {
                    "kind": "fusion_records",
                    "reference_revision": revision,
                    "cursor": page["next_cursor"],
                }
            )
            if page["next_cursor"] is not None
            else None,
        }

    @staticmethod
    def _group(model, version, summary):
        return {
            "model": model,
            "reference_model_version": version,
            **{
                key: summary[key]
                for key in (
                    "closed_count",
                    "sum_return_percentage_points",
                    "open_count",
                    "interrupted_count",
                )
            },
        }

    @staticmethod
    def _trade(item, sources, since, version):
        from app.reference_trading.query import QueryConflict

        entry, exit_id = item["entry_action_id"], item["exit_action_id"]
        if entry not in sources or (exit_id is not None and exit_id not in sources):
            raise QueryConflict("PRESENTATION_CORRUPT")
        return {
            "reference_trade_id": item["public_reference_trade_id"],
            "reference_model_version": version,
            "physical_contract": item["physical_contract"],
            "segment_id": item["owner_segment_id"],
            "calculation_segment_id": item["calculation_segment_id"],
            "entry_source": sources[entry],
            "entry_signal_id": entry,
            "exit_source": sources.get(exit_id),
            "exit_signal_id": exit_id,
            **{
                key: item[key]
                for key in (
                    "entry_bar_end",
                    "entry_trading_day",
                    "entry_reference_price",
                    "exit_bar_end",
                    "exit_trading_day",
                    "exit_reference_price",
                    "status",
                    "holding_bars",
                    "mark_bar_end",
                    "mark_reference_price",
                )
            },
            "reference_return_pct": item["reference_return"],
            "mark_change_pct": item["mark_return"],
            "interrupted_at": item.get("interrupted_at"),
            "statistics_membership": "initial_before_window"
            if item["entry_trading_day"] < since.isoformat()
            else "entry_in_window_v1",
        }
