"""Materialize bounded Newow v35 sections from the exact archived Reference cutoff."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
import logging
from pathlib import Path
import re
from time import monotonic

from app.market_data.after_market_history import _bytes, _digest, publish_history
from app.market_data.after_market_limits import MAX_HISTORY_BYTES
from app.market_data.live_recovery_guard import _file_guard
from app.market_data.market_archive import MarketArchiveReceipt
from app.market_data.newow.market_reference_after_close import latest_reference
from app.market_data.newow.product_service import AuxiliaryComponent, ProductSection
from app.reference_trading.recording_scope import FREQUENCIES, STRATEGIES


_LOGGER = logging.getLogger(__name__)
_SCHEMA = "newow_market_archive_sections_v1"
_COMPARATOR_FREQUENCIES = {"1w", "1d", "60m"}
_MAX_ELAPSED = 1_800.0


def _section_keys(strategy: str, frequency: str) -> tuple[str, ...]:
    # Dual presentation reads the existing trend and oscillator sections.
    if strategy == "dual_fusion":
        return ()
    auxiliary = tuple(
        f"auxiliary:{component.value}" for component in AuxiliaryComponent
        if component is not AuxiliaryComponent.CUP_HANDLE or (strategy, frequency) == ("trend", "1d")
    )
    comparator = strategy == "oscillation" and frequency in _COMPARATOR_FREQUENCIES
    return (*auxiliary, "comparator") if comparator else auxiliary


def _path(sandbox: Path, reference: dict) -> Path:
    stream = reference["stream_id"].removeprefix("reference-stream:")
    revision = reference["revision_id"]
    sequence = reference["seq"]
    if (not re.fullmatch(r"[0-9a-f]{64}", stream)
            or not isinstance(revision, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", revision)
            or type(sequence) is not int or sequence < 1):
        raise ValueError("MARKET_REFERENCE_SECTION_IDENTITY_INVALID")
    directory = sandbox / "newow-archive-sections" / stream
    receipt = reference.get("receipt")
    if receipt is not None:
        if not isinstance(receipt, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt):
            raise ValueError("MARKET_REFERENCE_SECTION_IDENTITY_INVALID")
        directory /= receipt
    return directory / f"{revision}-{sequence}.json"


def _load(sandbox: Path, reference: dict) -> dict | None:
    try:
        data = json.loads(_bytes(_path(sandbox, reference), max_bytes=MAX_HISTORY_BYTES))
    except FileNotFoundError:
        # An immutable v1 section remains readable only under the receipt that created it.
        if reference.get("receipt") is None:
            return None
        legacy = _load(sandbox, {k: v for k, v in reference.items() if k != "receipt"})
        return legacy if legacy and legacy["receipt"] == reference["receipt"] else None
    if not isinstance(data, dict) or set(data) != {"schema", "receipt", "stream_id", "revision_id",
            "seq", "cutoff", "chart", "sections", "sha256"}:
        raise ValueError("MARKET_REFERENCE_SECTION_IDENTITY_INVALID")
    content_hash = data.pop("sha256")
    if (data["schema"] != _SCHEMA or data["stream_id"] != reference["stream_id"]
            or data["revision_id"] != reference["revision_id"] or data["seq"] != reference["seq"]
            or not isinstance(data["cutoff"], str) or datetime.fromisoformat(data["cutoff"]) != reference["cutoff"]
            or not isinstance(data["receipt"], str) or re.fullmatch(r"[0-9a-f]{64}", data["receipt"]) is None
            or not isinstance(data["chart"], dict) or not isinstance(data["sections"], dict)
            or reference.get("receipt", data["receipt"]) != data["receipt"]
            or _digest(data) != content_hash):
        raise ValueError("MARKET_REFERENCE_SECTION_IDENTITY_INVALID")
    return data


def saved_section(sandbox: Path, reference: dict, *, strategy: str, frequency: str,
                  section: str, component: str | None) -> dict:
    key = section if component is None else f"{section}:{component}"
    if key not in _section_keys(strategy, frequency):
        return {"status": "unavailable", "receipt": None, "result": None, "chart": None}
    data = _load(sandbox, reference)
    if data is None or key not in data["sections"]:
        return {"status": "pending", "receipt": None, "result": None, "chart": None}
    return {"status": "ready", "receipt": data["receipt"], "result": data["sections"][key], "chart": data["chart"]}


def _compute_sections(session, product: str, strategy: str, frequency: str, *,
                      reference: dict, receipt: MarketArchiveReceipt, cancelled) -> tuple[dict, dict]:
    from app.api.newow_presentation import _product_response
    from app.market_data.composition import build_database_coverage_source, build_market_data_service
    from app.market_data.newow.composition import NewowComposition
    from app.market_data.newow.product_release import (
        FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY, candidate_input_quality_policy,
    )
    from app.market_data.newow.product_service import ProductServiceQuery
    from app.market_data.operational_universe import load_active_products
    from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

    cutoff = reference["cutoff"]
    qualified_strategy = ProductStrategy(strategy)
    qualified_frequency = ProductFrequency(frequency)
    market = build_market_data_service(session, check_cancelled=cancelled)
    service = NewowComposition(
        market, build_database_coverage_source(session), load_active_products(),
        candidate_input_quality_policy(product, frequency, candidate_weekly=False),
        now=lambda: receipt.finished_at, reference_price_policy=FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY,
    ).service(reuse_read_inputs=True, cancelled=cancelled)
    base = {"product": product, "strategy": qualified_strategy, "frequency": qualified_frequency, "as_of": cutoff}
    chart = service.query(ProductServiceQuery(**base))
    proof = chart.meta.shared_input_proof
    if chart.meta.as_of != cutoff or proof is None:
        raise ValueError("MARKET_REFERENCE_SECTION_SNAPSHOT_CONFLICT")
    archive_token = _digest((
        _SCHEMA, receipt.identity, reference["stream_id"], reference["revision_id"],
        reference["seq"], cutoff.isoformat(), proof.market_input_sha256,
    ))
    chart_payload = _product_response(chart).model_dump(mode="json")
    chart_payload["meta"]["snapshot_token"] = archive_token
    if isinstance(chart_payload["chart"]["value"], dict):
        # Native pagination depends on a process-local live token.
        chart_payload["chart"]["value"]["next_before"] = None
        chart_payload["chart"]["value"]["next_older_window"] = None
    saved = {}
    for key in _section_keys(strategy, frequency):
        section, _, component = key.partition(":")
        result = service.query(ProductServiceQuery(
            **base, section=ProductSection(section), component=AuxiliaryComponent(component) if component else None,
            snapshot_token=chart.meta.snapshot_token,
        ))
        actual = result.meta.shared_input_proof
        if (result.meta.as_of != cutoff or actual is None
                or actual.market_input_sha256 != proof.market_input_sha256
                or result.meta.input_content_sha256 != chart.meta.input_content_sha256):
            raise ValueError("MARKET_REFERENCE_SECTION_SNAPSHOT_CONFLICT")
        payload = _product_response(result).model_dump(mode="json")
        payload["meta"]["snapshot_token"] = archive_token
        saved[key] = payload
    return chart_payload, saved


def materialize_sections(
    sandbox: Path, receipt: MarketArchiveReceipt, *, session_factory, verify_publication: Callable[[str], None],
    canonical_root: Path | None = None, formal: bool = False, stop_requested: Callable[[], bool] = lambda: False,
) -> dict:
    """One fixed default 500-bar chart window per active series and revision."""
    from app.db.readonly import readonly_transaction
    from app.market_data.catalog import MarketCatalog

    expected = len(receipt.revisions) * len(FREQUENCIES) * (len(STRATEGIES) - 1)
    finished = 0
    deadline = monotonic() + _MAX_ELAPSED

    def cancelled():
        return stop_requested() or monotonic() >= deadline

    guard_root = sandbox / "live-recovery-guards"
    try:
        with _file_guard("newow-sections.lock", root=guard_root, wait=False, legacy_root=True):
            data_root = canonical_root if canonical_root is not None else sandbox / "canonical"
            for product in receipt.revisions:
                for frequency in FREQUENCIES:
                    for strategy in STRATEGIES:
                        # Existing dual presentation uses the trend / oscillator sections.
                        if strategy == "dual_fusion" or cancelled():
                            continue
                        try:
                            reference = latest_reference(product, strategy, frequency, session_factory=session_factory)
                            if reference is None or reference["cutoff"] > receipt.finished_at:
                                continue
                            if formal:
                                reference = {**reference, "receipt": receipt.identity}
                            if _load(sandbox, reference) is None:
                                with session_factory() as session:
                                    lease = MarketCatalog(session, data_root).acquire_maintenance_lock(
                                        caller="market-newow-sections",
                                    )
                                    if lease is None:
                                        continue
                                    try:
                                        verify_publication(product)
                                        with readonly_transaction(session, timeout_seconds=120):
                                            chart, sections = _compute_sections(
                                                session, product, strategy, frequency, reference=reference,
                                                receipt=receipt, cancelled=cancelled,
                                            )
                                        payload = {
                                            "schema": _SCHEMA, "receipt": receipt.identity,
                                            "stream_id": reference["stream_id"], "revision_id": reference["revision_id"],
                                            "seq": reference["seq"], "cutoff": reference["cutoff"].isoformat(),
                                            "chart": chart, "sections": sections,
                                        }
                                        publish_history(_path(sandbox, reference), {**payload, "sha256": _digest(payload)})
                                        if _load(sandbox, reference) is None:
                                            raise ValueError("MARKET_REFERENCE_SECTION_UNREADABLE")
                                    finally:
                                        lease.release()
                            finished += 1
                        except (OSError, ValueError, RuntimeError) as exc:
                            # An already committed history result remains independently readable.
                            code = str(exc)
                            reason = code if re.fullmatch(r"(NEWOW|MARKET)_[A-Z0-9_]+", code) else type(exc).__name__
                            _LOGGER.warning(
                                "Newow archive section pending product=%s strategy=%s frequency=%s reason=%s",
                                product, strategy, frequency, reason,
                            )
    except RuntimeError as exc:
        if str(exc) != "LIVE_RECOVERY_BUSY":
            raise
    return {"status": "completed" if expected == finished else "pending",
            "expected": expected, "complete": finished}
