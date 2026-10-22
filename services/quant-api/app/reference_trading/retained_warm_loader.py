"""Fresh, read-only H1 kernel warming from immutable normal completed journals."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.reference_trading.forward_authority import ForwardMarketAuthority
from app.reference_trading.forward_inputs import capture_newow_envelope
from app.reference_trading.models import ReferenceStream
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
from app.reference_trading.newow_forward import _whole_number
from app.reference_trading.original_conflict_warm_seed import (
    RETAINED_VERSION,
    WarmBaseline,
    WarmInput,
    WarmInterval,
    _hash,
    _input_facts,
    materialize_retained_warm_seed,
    materialize_fusion_warm_seed,
    require,
)
from app.reference_trading.inputs import HistoricalInputSnapshot
from app.reference_trading.planning import HistoricalStreamRequest, _canonical_identity
from app.reference_trading.repository import _identity_from_row
from app.reference_trading.retained_observation_authority import read_retained_interval
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import ProductBar

BASES = frozenset(("newow_trend", "newow_oscillation", "newow_main_rise"))


class RetainedWarmSourceLoader:
    """Caller retains writer fence and Canonical lease on every invocation.

    Only one authoritative trading-day suffix is admitted. Owner rollover is
    rejected here; it requires a separately proved boundary, never a guessed
    current-contract substitution.
    """

    def __init__(
        self,
        factory,
        journal,
        reader,
        market,
        *,
        trading_day: date,
        recording_start: datetime,
        knowledge_at: datetime,
        assert_fenced,
        capability_ready,
    ):
        require(knowledge_at < recording_start, "WARM_SEED_FUTURE_BOUNDARY_INVALID")
        self.factory, self.journal, self.reader, self.market = (
            factory,
            journal,
            reader,
            market,
        )
        self.day, self.start, self.known = trading_day, recording_start, knowledge_at
        self.assert_fenced, self.capability_ready = assert_fenced, capability_ready
        self.authority = ForwardMarketAuthority(market)

    def __call__(self, session, source_id, *, lock=False):
        self.assert_fenced()
        identity, cp, schema, saved, binding = NewowForwardBootstrap(
            self.factory
        )._source(session, source_id, lock=lock)
        require(
            identity.frequency == "60m" and _canonical_identity(identity),
            "NEEDS_HISTORICAL_REBUILD",
        )
        if identity.strategy_code == "newow_dual_fusion":
            rows = tuple(
                row
                for row in session.scalars(
                    select(ReferenceStream).where(
                        ReferenceStream.product == identity.product,
                        ReferenceStream.frequency == "60m",
                        ReferenceStream.recording_mode == "historical_replay",
                        ReferenceStream.strategy_code.in_(BASES),
                    )
                )
                if _canonical_identity(_identity_from_row(row))
            )
            require(
                len(rows) == 3 and {row.strategy_code for row in rows} == BASES,
                "WARM_SEED_FUSION_BASES_INVALID",
            )
            seeds = tuple(
                self(session, row.stream_id, lock=lock)
                for row in sorted(rows, key=lambda row: row.strategy_code)
            )
            return materialize_fusion_warm_seed(
                identity,
                seeds,
                original_binding=binding,
                recording_start=self.start,
                version=RETAINED_VERSION,
            )
        require(identity.strategy_code in BASES, "NEEDS_HISTORICAL_REBUILD")
        request = HistoricalStreamRequest(
            identity,
            date.fromisoformat(saved["query_since"]),
            date.fromisoformat(saved["query_through"]),
            datetime.fromisoformat(saved["query_as_of"]),
        )
        snapshot = self.reader.plan_stream(request)
        # Prove full suffix through the future boundary using the baseline's actual
        # physical contract. A different current owner cannot make this pass.
        ends = self.authority.expected_endpoints(
            identity,
            cp.physical_contract,
            self.day,
            cp.computed_through,
            self.start - timedelta(microseconds=1),
        )
        originals = read_retained_interval(
            self.journal,
            product=identity.product,
            day=self.day,
            after=cp.computed_through,
            before=self.start,
            expected_endpoints=ends,
            knowledge_at=self.known,
        )
        metadata = self.market.historical_metadata_evidence(
            symbol=identity.product, since=cp.computed_through.date(), through=self.day
        )
        baseline_proof = {
            "kind": "canonical_baseline",
            "stream_id": identity.stream_id,
            "input_sha256": snapshot.dependency_manifest["input_sha256"],
            "input_count": len(snapshot.bars),
            "source_evidence_sha256": snapshot.dependency_manifest[
                "source_evidence_sha256"
            ],
            "computed_through": snapshot.completed_through.isoformat(),
            "range_sha256": _hash(snapshot.bars),
            "physical_sha256": _hash(
                [
                    (
                        b.physical_contract,
                        b.owner_segment_id,
                        b.calculation_segment_id,
                        b.bar_end.isoformat(),
                    )
                    for b in snapshot.bars
                ]
            ),
            "session_sha256": _hash(
                snapshot.dependency_manifest.get(
                    "calendar_session_effective_fingerprints"
                )
            ),
            "quality_sha256": _hash(snapshot.dependency_manifest),
        }
        inputs, proofs = [], {}
        previous = cp.computed_through
        for original, original_proof in originals:
            capture = capture_newow_envelope(
                original,
                identity,
                revision_id=binding["revision_id"],
                generation=1,
                after=previous,
                now=original.confirmed_at,
                owner_segments=self.authority.owner_segments,
                expected_endpoints=self.authority.expected_endpoints,
                capability_ready=self.capability_ready,
            )
            require(capture is not None, "WARM_SEED_INPUT_INVALID")
            payload, source = capture.input_payload, capture.source_proof
            owner = (
                payload["contract"],
                source["owner_segment_id"],
                source["calculation_segment_id"],
            )
            require(
                owner
                == (
                    cp.physical_contract,
                    cp.owner_segment_id,
                    cp.calculation_segment_id,
                ),
                "WARM_SEED_OWNER_BOUNDARY_REQUIRED",
            )
            raw = payload["bar"]
            bar = ProductBar(
                NewowDailyBar(
                    identity.product,
                    owner[0],
                    owner[1],
                    original.trading_day,
                    capture.bar_end,
                    Decimal(raw["open"]),
                    Decimal(raw["high"]),
                    Decimal(raw["low"]),
                    Decimal(raw["close"]),
                    _whole_number(raw["volume"]),
                    None
                    if raw["open_interest"] is None
                    else _whole_number(raw["open_interest"]),
                    payload["source_identity"],
                    True,
                    True,
                ),
                identity.frequency,
                calculation_segment_id=owner[2],
                source_bar_sha256=payload["source_bar_sha256"],
            )
            item = WarmInput(bar, "completed_live", original.confirmed_at, {})
            proof = {
                **_input_facts(item),
                **original_proof,
                "expected_endpoint": capture.bar_end.isoformat(),
                "previous_watermark": previous.isoformat(),
                "expected_endpoints": [capture.bar_end.isoformat()],
                "source_manifest_sha256": _hash(source),
                "owner_sha256": _hash(owner),
                "session_sha256": _hash(metadata),
                "quality_sha256": _hash({"validated_capture": capture.input_payload}),
                "rollover": False,
            }
            inputs.append(replace(item, source_proof=proof))
            proofs[capture.bar_end] = proof
            previous = capture.bar_end
        cutoff = previous
        require(
            not self.authority.expected_endpoints(
                identity,
                cp.physical_contract,
                self.day,
                cutoff,
                self.start - timedelta(microseconds=1),
            ),
            "WARM_SEED_FINAL_FRONTIER_INCOMPLETE",
        )
        interval = {
            "kind": "completed_warm_interval" if inputs else "completed_empty_interval",
            "stream_id": identity.stream_id,
            "previous_watermark": cp.computed_through.isoformat(),
            "cutoff": cutoff.isoformat(),
            "recording_start": self.start.isoformat(),
            "knowledge_at": self.known.isoformat(),
            "stage": "final_observation",
            "physical_contract": cp.physical_contract,
            "owner_segment_id": cp.owner_segment_id,
            "calculation_segment_id": cp.calculation_segment_id,
            "expected_endpoints": [end.isoformat() for end in ends],
            "computed_through": cutoff.isoformat(),
            "remaining_endpoints_before_start": [],
            "session_sha256": _hash(metadata),
            "owner_sha256": _hash(
                (cp.physical_contract, cp.owner_segment_id, cp.calculation_segment_id)
            ),
            "quality_sha256": _hash(
                [proof["quality_sha256"] for proof in proofs.values()]
            ),
        }

        def verify(value):
            self.assert_fenced()
            if isinstance(value, HistoricalInputSnapshot):
                return baseline_proof
            if isinstance(value, WarmInterval):
                return interval
            require(isinstance(value, WarmInput), "WARM_SEED_INPUT_AUTHORITY_INVALID")
            return proofs[value.product_bar.bar.bar_end]

        result = materialize_retained_warm_seed(
            WarmBaseline(identity, cp, schema, saved, binding),
            fresh_snapshot=snapshot,
            inputs=tuple(inputs),
            expected_endpoints=ends,
            recording_start=self.start,
            cutoff=cutoff,
            knowledge_at=self.known,
            verify_authority=verify,
        )
        require(
            read_retained_interval(
                self.journal,
                product=identity.product,
                day=self.day,
                after=cp.computed_through,
                before=self.start,
                expected_endpoints=ends,
                knowledge_at=self.known,
            )
            == originals,
            "WARM_SEED_SOURCE_DRIFT",
        )
        require(
            self.reader.revalidate(
                request, expected_source_token=snapshot.source_token
            ),
            "WARM_SEED_BASELINE_DRIFT",
        )
        self.assert_fenced()
        return result
