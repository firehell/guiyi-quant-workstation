"""Native MDS proof for a bounded HTDY context conflict, never a replay permit."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from types import SimpleNamespace

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
    SeriesKind,
    SeriesPageQuery,
)
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.htdy_activation import SCHEMA, htdy_identity
from guiyi_quant.reference_trading.htdy import CONTEXT_BARS
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json,
    adapter_checkpoint_to_json,
)

POLICY = "htdy_context_conflict_source_v1"
FIELDS = ("open", "high", "low", "close", "volume")


def require(value, code="HTDY_CONFLICT_SOURCE_UNPROVEN"):
    if not value:
        raise ValueError(code)


def _instant(raw):
    result = datetime.fromisoformat(raw)
    require(result.tzinfo is not None and result.utcoffset() is not None)
    return result


def _valid(bar):
    values = [getattr(bar, name) for name in FIELDS]
    require(all(Decimal(str(v)).is_finite() for v in values))
    require(
        bar.low > 0
        and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
    )
    require(
        bar.volume >= 0
        and Decimal(str(bar.volume)) == Decimal(str(bar.volume)).to_integral_value()
    )


def _bar(raw):
    result = CanonicalBar(
        _instant(raw["bar_end"]),
        date.fromisoformat(raw["trading_day"]),
        *(Decimal(raw[k]) for k in FIELDS),
        None if raw["turnover"] is None else Decimal(raw["turnover"]),
        None if raw["open_interest"] is None else Decimal(raw["open_interest"]),
    )
    _valid(result)
    for value in (result.turnover, result.open_interest):
        require(value is None or value.is_finite() and value >= 0)
    return result


def _fact(bar, contract):
    return {
        "bar_end": bar.bar_end.isoformat(),
        "trading_day": bar.trading_day.isoformat(),
        "contract": contract,
        **{f: str(getattr(bar, f)) for f in FIELDS},
    }


class HtdyConflictSource:
    def __init__(self, market, authority):
        self.market, self.authority = market, authority

    def __call__(self, identity, binding, manifest):
        require(identity == htdy_identity(identity.product))
        require(binding["stream_id"] == identity.stream_id)
        cp = adapter_checkpoint_from_json(
            json.dumps(binding["checkpoint"]),
            expected_stream=identity,
            expected_strategy_schema=SCHEMA,
        )
        require(
            sha256(
                adapter_checkpoint_to_json(cp, strategy_schema=SCHEMA).encode()
            ).hexdigest()
            == binding["checkpoint_sha256"]
        )
        old = cp.strategy_state.window
        require(len(old) == CONTEXT_BARS and old[-1].bar_end == cp.computed_through)
        for value in old:
            _valid(value)
        captures = binding["captures"]
        require(len(captures) == 1)
        row = captures[0]
        wire = row["source_evidence"]["forward_capture_v1"]
        cap = ForwardCapture(
            identity.stream_id,
            binding["revision_id"],
            wire["generation"],
            wire["source_key"],
            _instant(wire["bar_end"]),
            _instant(wire["observed_at"]),
            wire["source_kind"],
            wire["input_payload"],
            wire["source_proof"],
            wire["eligibility"],
        )
        require(
            cap.capture_hash == row["payload_hash"] == wire["hash"]
            and cap.source_kind == "completed_live"
            and cap.eligibility == "first_seen"
        )
        from app.market_data.observation_stream import ObservationEnvelope
        from app.reference_trading.inbox import _exact_legacy_capture

        delivery_id = cap.source_proof.get("inbox_delivery_id")
        originals = [
            d["original"]
            for d in binding["deliveries"]
            if d["delivery_id"] == delivery_id
        ]
        require(len(originals) == 1, "HTDY_CONFLICT_ORIGINAL_UNPROVEN")
        original = originals[0]
        event = ObservationEnvelope.from_json(
            original["input"]["canonical_envelope"],
            stream_id=original["input"]["journal_id"],
        )
        require(
            _exact_legacy_capture(
                SimpleNamespace(**row), SimpleNamespace(**original["delivery"]), event
            ),
            "HTDY_CONFLICT_ORIGINAL_UNPROVEN",
        )
        raw, contracts = cap.input_payload["bars"], cap.input_payload["bar_contracts"]
        require(len(raw) == len(contracts) == CONTEXT_BARS)
        require(
            sha256(
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            == cap.source_proof["window_sha256"]
        )
        bars = tuple(_bar(b) for b in raw)
        require(
            cap.input_payload["bar"] == raw[-1]
            and bars[-1].bar_end == cap.bar_end
            and cap.bar_end < cap.observed_at
            and cap.input_payload["contract"] == contracts[-1]
        )
        require(
            tuple((b.bar_end, b.trading_day, b.physical_contract) for b in old[1:])
            == tuple(
                (b.bar_end, b.trading_day, c) for b, c in zip(bars[:-1], contracts[:-1])
            )
        )
        for context, owners in (
            (old, tuple(b.physical_contract for b in old)),
            (bars, tuple(contracts)),
        ):
            self.market.validate_actual_dominant_alert_window(
                symbol=identity.product.lower(),
                frequency="60m",
                trading_day=context[-1].trading_day,
                current_contract=owners[-1],
                cutoff=context[-1].bar_end,
                bars=context,
                bar_contracts=owners,
            )
        require(
            self.authority.owner_segments(
                identity, contracts[-1], bars[-1].trading_day, cap.bar_end
            )
            == (
                cap.source_proof["owner_segment_id"],
                cap.source_proof["calculation_segment_id"],
            )
            == (cp.owner_segment_id, cp.calculation_segment_id),
            "HTDY_CONFLICT_OWNER_UNPROVEN",
        )
        require(
            self.authority.expected_endpoints(
                identity,
                contracts[-1],
                bars[-1].trading_day,
                cp.computed_through,
                cap.bar_end,
            )
            == (cap.bar_end,),
            "HTDY_CONFLICT_ENDPOINT_UNPROVEN",
        )
        groups = defaultdict(list)
        for a, b, c in zip(old[1:], bars[:-1], contracts[:-1]):
            differences = {
                f: {"old": str(getattr(a, f)), "new": str(getattr(b, f))}
                for f in FIELDS
                if getattr(a, f) != getattr(b, f)
            }
            if differences:
                groups[c].append((a, b, differences))
        require(groups)
        conflicts, sources = [], []
        for contract, changes in sorted(groups.items()):
            product = identity.product.lower()
            require(
                self.market.catalog.contract_fact(product, contract).provider
                == "rqdata",
                "HTDY_CONFLICT_PROVIDER_UNPROVEN",
            )
            upper = max(b.bar_end for _, b, _ in changes)
            lower = min(b.bar_end for _, b, _ in changes)
            page = self.market.query_page_inclusive(
                SeriesPageQuery(
                    SeriesKind.CONTRACT,
                    product,
                    BarFrequency.H1,
                    before=upper,
                    limit=CONTEXT_BARS,
                    contract=contract,
                )
            )
            current = {b.bar_end: b for b in page.bars}
            for a, b, differences in changes:
                require(current.get(b.bar_end) == b, "HTDY_CONFLICT_CANONICAL_MISMATCH")
                conflicts.append(
                    {
                        "bar_end": b.bar_end.isoformat(),
                        "contract": contract,
                        "old_sha256": manifest_sha256(_fact(a, contract)),
                        "new_sha256": manifest_sha256(_fact(b, contract)),
                        "fields": differences,
                    }
                )
            for frequency, expected in (
                (BarFrequency.M1, "rqdata"),
                (BarFrequency.H1, "canonical_1m"),
            ):
                evidence = self.market.contract_source_evidence(
                    symbol=product,
                    contract=contract,
                    frequency=frequency,
                    before=upper + timedelta(microseconds=1),
                )
                require(
                    evidence["contract"] == contract
                    and evidence["frequency"] == frequency.value
                    and evidence["partitions"]
                )
                require(
                    all(
                        re.fullmatch("[0-9a-f]{64}", p["content_sha256"])
                        and (
                            p["quality_sha256"] is None
                            or re.fullmatch("[0-9a-f]{64}", p["quality_sha256"])
                        )
                        for p in evidence["partitions"]
                    )
                )
                partitions = self.market.catalog.partitions(
                    DatasetKey(DatasetKind.CONTRACT, product, contract, frequency),
                    lower - timedelta(microseconds=1),
                    upper,
                )
                require(partitions)
                provenance = [
                    self.market.store.read_publication_provenance(p) for p in partitions
                ]
                require(
                    all(
                        p
                        and p.get("version") == 1
                        and p.get("input_source") == expected
                        and re.fullmatch("[0-9a-f]{64}", p.get("input_sha256", ""))
                        for p in provenance
                    ),
                    "HTDY_CONFLICT_PROVENANCE_UNPROVEN",
                )
                sources.append(
                    {"evidence": evidence, "publication_provenance": provenance}
                )
        return {
            "policy": POLICY,
            "capture_sha256": cap.capture_hash,
            "checkpoint_sha256": binding["checkpoint_sha256"],
            "conflicts": conflicts,
            "sources": sources,
            "boundary_end": cap.bar_end.isoformat(),
            "boundary_trading_day": bars[-1].trading_day.isoformat(),
        }
