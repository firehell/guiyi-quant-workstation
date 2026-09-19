"""Isolated, non-applying candidates for the SuBing D1 quality plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, cast
import uuid

from app.market_data.catalog import CatalogPartition
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.source_quality import (
    NonpositiveCloseFact,
    PriceUnavailableFact,
    SourceQualityFact,
    source_quality_fact_from_record,
)
from app.market_data.storage import (
    CanonicalMonthlyStore,
    PublishRequest,
    PublishedPartition,
)


class CandidatePreparationError(RuntimeError):
    """Candidate construction failed before any production mutation."""


@dataclass(frozen=True, slots=True)
class SourceProof:
    request_sha256: str
    response_sha256: str
    observed_at: datetime
    classification: str
    source_values: Mapping[str, Decimal | None] | None = None


@dataclass(frozen=True, slots=True)
class PreparedCandidate:
    manifest: Mapping[str, Any]
    partition: PublishedPartition


def verify_plan_input_files(
    plan: Mapping[str, Any], inputs: Mapping[str, Path]
) -> None:
    """Bind every approved evidence input to the exact bytes supplied to the CLI."""
    required = {
        "d1-17-source-diagnosis.json",
        "d1-17-source-evidence-refresh.json",
        "d1-17-source-verification-complete.json",
    }
    approved = plan.get("input_evidence", {}).get("impact_input_sha256")
    if (
        not isinstance(approved, Mapping)
        or set(approved) != required
        or set(inputs) != required
    ):
        raise CandidatePreparationError("PLAN_EVIDENCE_BINDING_INVALID")
    for name in sorted(required):
        expected = approved[name]
        if not isinstance(expected, str):
            raise CandidatePreparationError("PLAN_EVIDENCE_BINDING_INVALID")
        _validate_digest(expected)
        try:
            actual = sha256(inputs[name].read_bytes()).hexdigest()
        except OSError as exc:
            raise CandidatePreparationError("PLAN_EVIDENCE_UNREADABLE") from exc
        if actual != expected:
            raise CandidatePreparationError("PLAN_EVIDENCE_HASH_MISMATCH")


def build_candidate_manifest(
    *,
    plan: Mapping[str, Any],
    candidate_root: str,
    candidates: list[Mapping[str, Any]],
    recovery_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize frozen replacements and fail closed on unstaged create targets."""
    targets = plan.get("targets")
    if not isinstance(targets, list) or len(targets) != plan.get("target_partition_count"):
        raise CandidatePreparationError("PLAN_SCOPE_INVALID")
    target_by_id = {
        (str(item.get("symbol")), str(item.get("contract")), str(item.get("month"))): item
        for item in targets if isinstance(item, Mapping)
    }
    target_ids = set(target_by_id)
    candidate_ids = [
        (str(item.get("symbol")), str(item.get("contract")), str(item.get("month")))
        for item in candidates
    ]
    if (
        len(candidate_ids) != len(set(candidate_ids))
        or not set(candidate_ids) <= target_ids
    ):
        raise CandidatePreparationError("CANDIDATE_SCOPE_INVALID")
    required_hashes = (
        "candidate_file_sha256",
        "candidate_content_sha256",
        "candidate_source_quality_sha256",
        "candidate_quality_sidecar_sha256",
    )
    for item in candidates:
        identity = (str(item.get("symbol")), str(item.get("contract")), str(item.get("month")))
        if (
            item.get("state") != "CANDIDATE_FROZEN"
            or item.get("operation") != target_by_id[identity].get("operation")
            or any(not isinstance(item.get(name), str) for name in required_hashes)
            or any(len(str(item[name])) != 64 for name in required_hashes)
            or (
                item.get("operation") == "REPLACE_EXISTING_PARTITION"
                and not isinstance(item.get("old_file_sha256"), str)
            )
            or any(
                Path(str(item.get(name, ""))).is_absolute()
                or ".." in Path(str(item.get(name, ""))).parts
                for name in ("candidate_file_uri", "candidate_quality_sidecar_uri")
            )
            or not isinstance(item.get("row_count"), int)
            or not isinstance(item.get("source_quality_count"), int)
        ):
            raise CandidatePreparationError("CANDIDATE_RECORD_INVALID")
    missing_ids = {
        (str(item.get("symbol")), str(item.get("contract")), str(item.get("month"))): item
        for item in targets
        if isinstance(item, Mapping)
        and (str(item.get("symbol")), str(item.get("contract")), str(item.get("month")))
        not in set(candidate_ids)
    }
    blocked = [
        {
            "symbol": item.get("symbol"),
            "contract": item.get("contract"),
            "month": item.get("month"),
            "operation": item.get("operation"),
            "expected_endpoints_sha256": item.get("expected_endpoints_sha256"),
            "reason": "SOURCE_RESPONSE_BYTES_UNAVAILABLE",
        }
        for item in missing_ids.values()
    ]
    total = len(targets)
    frozen = len(candidates)
    body: dict[str, Any] = {
        "schema": "subing-d1-quality-candidate-manifest-v1",
        "mode": "ISOLATED_CANDIDATE_PREPARE",
        "state": f"PARTIAL_CANDIDATES_{frozen}_OF_{total}" if blocked else "ALL_CANDIDATES_FROZEN",
        "fixed_cutoff": plan.get("fixed_cutoff"),
        "parent_plan_sha256": plan.get("plan_sha256"),
        "candidate_root": candidate_root,
        "target_partition_count": total,
        "frozen_candidate_count": frozen,
        "blocked_target_count": len(blocked),
        "provider_requests": 0,
        "production_writes": 0,
        "candidates": sorted(
            (dict(item) for item in candidates),
            key=lambda item: (item["symbol"], item["contract"], item["month"]),
        ),
        "blocked_targets": sorted(
            blocked, key=lambda item: (item["symbol"], item["contract"], item["month"])
        ),
    }
    if recovery_evidence is not None:
        body["recovery_evidence"] = dict(recovery_evidence)
    body["manifest_sha256"] = sha256(_canonical_json(body)).hexdigest()
    return body


def build_source_proof_index(
    evidence_refresh: Mapping[str, Any],
    *,
    raw_evidence_root: Path,
) -> dict[tuple[str, str, date], SourceProof]:
    """Verify saved response bytes and bind exact source rows to their hashes."""
    root = raw_evidence_root.resolve(strict=True)
    result: dict[tuple[str, str, date], SourceProof] = {}

    def put(key: tuple[str, str, date], proof: SourceProof) -> None:
        _validate_digest(proof.request_sha256)
        _validate_digest(proof.response_sha256)
        previous = result.get(key)
        if previous is not None and previous != proof:
            raise CandidatePreparationError("SOURCE_PROOF_CONFLICT")
        result[key] = proof

    items = evidence_refresh.get("items")
    if not isinstance(items, list):
        raise CandidatePreparationError("SOURCE_EVIDENCE_INVALID")
    for item in items:
        if not isinstance(item, Mapping):
            raise CandidatePreparationError("SOURCE_EVIDENCE_INVALID")
        symbol = str(item.get("symbol", "")).lower()
        artifacts = item.get("saved_raw_artifacts", ())
        if not isinstance(artifacts, list):
            raise CandidatePreparationError("SOURCE_EVIDENCE_INVALID")
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or not isinstance(artifact.get("request"), Mapping):
                raise CandidatePreparationError("SOURCE_EVIDENCE_INVALID")
            request = dict(artifact["request"])
            contract = str(request.get("contract", "")).upper()
            if (
                artifact.get("journal_matches_file") is not True
                or artifact.get("journal_payload_sha256") != artifact.get("artifact_sha256")
            ):
                raise CandidatePreparationError("SOURCE_RAW_JOURNAL_MISMATCH")
            relative = Path(str(artifact.get("artifact", "")))
            if relative.is_absolute() or ".." in relative.parts:
                raise CandidatePreparationError("SOURCE_RAW_PATH_INVALID")
            raw, observed_at = _read_raw_file(root, relative)
            response_sha256 = sha256(raw).hexdigest()
            if response_sha256 != artifact.get("artifact_sha256"):
                raise CandidatePreparationError("SOURCE_RAW_HASH_MISMATCH")
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CandidatePreparationError("SOURCE_RAW_INVALID") from exc
            if (
                not isinstance(payload, Mapping)
                or payload.get("request") != request
                or not isinstance(payload.get("rows"), list)
            ):
                raise CandidatePreparationError("SOURCE_RAW_INVALID")
            rows_by_day: dict[date, Mapping[str, Any]] = {}
            for row in payload["rows"]:
                if not isinstance(row, Mapping):
                    raise CandidatePreparationError("SOURCE_RAW_INVALID")
                trading_day = date.fromisoformat(str(row.get("date", ""))[:10])
                if trading_day in rows_by_day:
                    raise CandidatePreparationError("SOURCE_RAW_DATE_DUPLICATE")
                rows_by_day[trading_day] = row
            request_sha256 = sha256(_canonical_json(request)).hexdigest()
            for raw_day in artifact.get("proved_dates", ()):
                trading_day = date.fromisoformat(str(raw_day))
                row = rows_by_day.get(trading_day)
                if row is None:
                    raise CandidatePreparationError("SOURCE_RAW_DATE_MISSING")
                values = _source_values(row)
                classification = _classify_source_values(values)
                if classification not in {
                    "NONPOSITIVE_CLOSE_SOURCE_FACT",
                    "ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT",
                }:
                    raise CandidatePreparationError("SOURCE_RAW_CLASSIFICATION_MISMATCH")
                put((symbol, contract, trading_day), SourceProof(
                    request_sha256=request_sha256,
                    response_sha256=response_sha256,
                    observed_at=observed_at,
                    classification=classification,
                    source_values=values,
                ))
    return result


def build_recovery_source_proof_index(
    recovery_candidate: Mapping[str, Any], *, attempt: Path
) -> dict[tuple[str, str, date], SourceProof]:
    """Verify a completed recovery attempt and expose only its frozen target rows."""
    plan_sha256 = recovery_candidate.get("plan_sha256")
    body = dict(recovery_candidate)
    body.pop("plan_sha256", None)
    if (
        not isinstance(plan_sha256, str)
        or sha256(_canonical_json(body)).hexdigest() != plan_sha256
        or recovery_candidate.get("schema")
        != "subing-d1-source-response-recovery-candidate-v1"
    ):
        raise CandidatePreparationError("RECOVERY_PLAN_INVALID")
    requests = recovery_candidate.get("requests")
    contract = recovery_candidate.get("execution_contract")
    if not isinstance(requests, list) or not isinstance(contract, Mapping):
        raise CandidatePreparationError("RECOVERY_PLAN_INVALID")
    if attempt.name != contract.get("attempt_id"):
        raise CandidatePreparationError("RECOVERY_ATTEMPT_INVALID")
    try:
        root = attempt.resolve(strict=True)
        if root != attempt or attempt.is_symlink() or not attempt.is_dir():
            raise OSError
        receipt = json.loads((attempt / "invocation-receipt.json").read_bytes())
        result_body = json.loads((attempt / "source-only-result.json").read_bytes())
        journal = [
            json.loads(line)
            for line in (attempt / "journal.jsonl").read_text().splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidatePreparationError("RECOVERY_ATTEMPT_INVALID") from exc
    expected_count = len(requests)
    budget = recovery_candidate.get("budget", {})
    expected_targets = budget.get("expected_date_identities")
    expected_context = budget.get("allowed_response_context_dates")
    summary = result_body.get("summary", {})
    outcome = result_body.get("attempt", {})
    if (
        receipt.get("plan_sha256") != plan_sha256
        or receipt.get("attempt_id") != attempt.name
        or receipt.get("provider_request_limit") != expected_count
        or receipt.get("expected_date_identities") != expected_targets
        or receipt.get("concurrency") != 1
        or receipt.get("retries_allowed") != 0
        or receipt.get("canonical_writes_allowed") is not False
        or receipt.get("database_writes_allowed") is not False
        or receipt.get("manager_apply_allowed") is not False
        or result_body.get("plan_sha256") != plan_sha256
        or result_body.get("status") != "completed"
        or result_body.get("failed") is not None
        or result_body.get("unexecuted") != []
        or result_body.get("retries") != 0
        or result_body.get("canonical_writes") != 0
        or result_body.get("database_writes") != 0
        or result_body.get("manager_apply") is not False
        or summary.get("requests_planned") != expected_count
        or summary.get("requests_started") != expected_count
        or summary.get("responses_saved") != expected_count
        or summary.get("requests_failed") != 0
        or summary.get("requests_unexecuted") != 0
        or summary.get("target_dates_planned") != expected_targets
        or summary.get("target_rows_saved") != expected_targets
        or summary.get("context_rows_saved") != expected_context
        or summary.get("rows_saved") != expected_targets + expected_context
        or outcome.get("outcome_unknown") is not False
        or outcome.get("requests_started") != expected_count
        or outcome.get("responses_saved") != expected_count
        or outcome.get("retry_allowed") is not False
        or outcome.get("state") != "response_saved"
        or len(journal) != expected_count * 2
    ):
        raise CandidatePreparationError("RECOVERY_ATTEMPT_INCOMPLETE")

    proofs: dict[tuple[str, str, date], SourceProof] = {}
    actual_rows = 0
    actual_context_rows = 0
    for sequence, raw_request in enumerate(requests, 1):
        if not isinstance(raw_request, Mapping):
            raise CandidatePreparationError("RECOVERY_PLAN_INVALID")
        transport = {
            "method": "futures.get_exchange_daily",
            "contract": raw_request.get("contract"),
            "start": raw_request.get("start"),
            "end": raw_request.get("end"),
            "expected_dates": raw_request.get("target_dates"),
        }
        started, saved = journal[(sequence - 1) * 2:sequence * 2]
        filename = f"source-response-{sequence:04d}.json"
        if (
            started != {
                "schema_version": 1,
                "sequence": sequence,
                "state": "started",
                "request": transport,
            }
            or saved.get("schema_version") != 1
            or saved.get("sequence") != sequence
            or saved.get("state") != "response_saved"
            or saved.get("payload_file") != filename
        ):
            raise CandidatePreparationError("RECOVERY_JOURNAL_INVALID")
        raw, observed_at = _read_raw_file(attempt, Path(filename))
        response_sha256 = sha256(raw).hexdigest()
        if response_sha256 != saved.get("payload_sha256"):
            raise CandidatePreparationError("RECOVERY_RAW_HASH_MISMATCH")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidatePreparationError("RECOVERY_RAW_INVALID") from exc
        if payload.get("request") != transport or not isinstance(payload.get("rows"), list):
            raise CandidatePreparationError("RECOVERY_RAW_INVALID")
        if saved.get("row_count") != len(payload["rows"]):
            raise CandidatePreparationError("RECOVERY_JOURNAL_ROW_COUNT_INVALID")
        actual_rows += len(payload["rows"])
        rows_by_day: dict[date, Mapping[str, Any]] = {}
        allowed_days = {
            date.fromisoformat(str(value))
            for value in raw_request.get("allowed_response_dates", ())
        }
        ordered_days: list[date] = []
        for row in payload["rows"]:
            if not isinstance(row, Mapping):
                raise CandidatePreparationError("RECOVERY_RAW_INVALID")
            raw_day = date.fromisoformat(str(row.get("date", ""))[:10])
            if (
                row.get("order_book_id") != raw_request.get("contract")
                or raw_day not in allowed_days
            ):
                raise CandidatePreparationError("RECOVERY_RAW_IDENTITY_INVALID")
            if raw_day in rows_by_day:
                raise CandidatePreparationError("RECOVERY_RAW_DATE_DUPLICATE")
            rows_by_day[raw_day] = row
            ordered_days.append(raw_day)
        if ordered_days != sorted(ordered_days):
            raise CandidatePreparationError("RECOVERY_RAW_DATE_ORDER_INVALID")
        target_days = {
            date.fromisoformat(str(value))
            for value in raw_request.get("target_dates", ())
        }
        actual_context_rows += len(set(rows_by_day) - target_days)
        for raw_day in sorted(target_days):
            row = rows_by_day.get(raw_day)
            if row is None:
                raise CandidatePreparationError("RECOVERY_RAW_DATE_MISSING")
            values = _source_values(row)
            classification = _classify_source_values(values)
            if classification not in {
                "POSITIVE_OHLC_SOURCE_FACT",
                "NONPOSITIVE_CLOSE_SOURCE_FACT",
                "ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT",
            }:
                raise CandidatePreparationError("RECOVERY_RAW_CLASSIFICATION_INVALID")
            key = (str(raw_request.get("symbol")), str(raw_request.get("contract")), raw_day)
            if key in proofs:
                raise CandidatePreparationError("RECOVERY_SOURCE_PROOF_DUPLICATE")
            proofs[key] = SourceProof(
                request_sha256=str(raw_request.get("request_sha256")),
                response_sha256=response_sha256,
                observed_at=observed_at,
                classification=classification,
                source_values=values,
            )
    if (
        len(proofs) != expected_targets
        or actual_context_rows != expected_context
        or actual_rows != expected_targets + expected_context
    ):
        raise CandidatePreparationError("RECOVERY_ATTEMPT_INCOMPLETE")
    return proofs


def prepare_replacement_candidate(
    *,
    target: Mapping[str, Any],
    partition: CatalogPartition,
    active_root: Path,
    candidate_root: Path,
    proofs: Mapping[tuple[str, str, date], SourceProof],
) -> PreparedCandidate:
    """Freeze one replacement under an isolated root without changing Catalog."""
    if target.get("operation") != "REPLACE_EXISTING_PARTITION":
        raise CandidatePreparationError("TARGET_OPERATION_INVALID")
    month = str(target.get("month", ""))
    if (
        partition.dataset.symbol != target.get("symbol")
        or partition.dataset.series_or_contract != target.get("contract")
        or month != f"{partition.year:04d}-{partition.month:02d}"
    ):
        raise CandidatePreparationError("TARGET_IDENTITY_DRIFT")
    try:
        relative = partition.file_path.relative_to(active_root).as_posix()
    except ValueError as exc:
        raise CandidatePreparationError("OLD_FILE_URI_DRIFT") from exc
    if relative != target.get("old_file_uri"):
        raise CandidatePreparationError("OLD_FILE_URI_DRIFT")
    payload = partition.file_path.read_bytes()
    if sha256(payload).hexdigest() != target.get("old_file_sha256"):
        raise CandidatePreparationError("OLD_FILE_HASH_DRIFT")
    if partition.source_quality_sha256 != target.get("old_source_quality_sha256"):
        raise CandidatePreparationError("OLD_QUALITY_HASH_DRIFT")

    active_store = CanonicalMonthlyStore(active_root)
    bars, existing_facts = active_store.read_catalog_partition_quality(partition)
    affected = {date.fromisoformat(str(value)) for value in target.get("affected_dates", ())}
    facts_by_day = {fact.trading_day: fact for fact in existing_facts}
    bars_by_day = {bar.trading_day: bar for bar in bars}
    if len(facts_by_day) != len(existing_facts) or len(bars_by_day) != len(bars):
        raise CandidatePreparationError("PARTITION_DATE_DUPLICATE")

    converted: list[NonpositiveCloseFact] = []
    for trading_day in sorted(affected):
        if trading_day in facts_by_day:
            continue
        bar = bars_by_day.get(trading_day)
        if bar is None:
            raise CandidatePreparationError("AFFECTED_DATE_MISSING")
        if bar.close > 0:
            raise CandidatePreparationError("AFFECTED_DATE_NOT_NONPOSITIVE")
        proof = proofs.get((partition.dataset.symbol, partition.dataset.series_or_contract, trading_day))
        if proof is None:
            raise CandidatePreparationError("SOURCE_PROOF_MISSING")
        if proof.classification != "NONPOSITIVE_CLOSE_SOURCE_FACT":
            raise CandidatePreparationError("SOURCE_PROOF_CLASSIFICATION_MISMATCH")
        if proof.source_values is None or any(
            proof.source_values.get(field) != getattr(bar, field)
            for field in ("open", "high", "low", "close", "volume", "turnover", "open_interest")
        ):
            raise CandidatePreparationError("SOURCE_ROW_MISMATCH")
        if bar.turnover is None:
            raise CandidatePreparationError("SOURCE_TURNOVER_MISSING")
        converted.append(NonpositiveCloseFact(
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            turnover=bar.turnover,
            open_interest=bar.open_interest,
            request_sha256=proof.request_sha256,
            response_sha256=proof.response_sha256,
            observed_at=proof.observed_at,
        ))

    remaining = tuple(bar for bar in bars if bar.trading_day not in affected)
    if any(bar.close <= 0 for bar in remaining):
        raise CandidatePreparationError("UNPLANNED_NONPOSITIVE_CLOSE")
    facts: tuple[SourceQualityFact, ...] = tuple(sorted(
        (*existing_facts, *converted), key=lambda fact: fact.bar_end
    ))
    expected = tuple(sorted((*(bar.bar_end for bar in remaining), *(fact.bar_end for fact in facts))))
    candidate_store = CanonicalMonthlyStore(candidate_root)
    published = candidate_store.publish(PublishRequest(
        dataset=partition.dataset,
        year=partition.year,
        month=partition.month,
        bars=remaining,
        expected_bar_ends=expected,
        price_unavailable=tuple(
            fact for fact in facts if isinstance(fact, PriceUnavailableFact)
        ),
        nonpositive_close=tuple(
            fact for fact in facts if isinstance(fact, NonpositiveCloseFact)
        ),
    ))
    candidate_bytes = published.parquet_path.read_bytes()
    sidecar_path, sidecar_sha256 = _write_quality_sidecar(
        published.parquet_path.parent, facts
    )
    sidecar_facts = _read_quality_sidecar(sidecar_path, sidecar_sha256)
    verified_partition = CatalogPartition(
        dataset=published.dataset,
        year=published.year,
        month=published.month,
        coverage_start=published.coverage_start,
        coverage_end=published.coverage_end,
        file_path=published.parquet_path,
        row_count=published.row_count,
        source_coverage_start=published.source_coverage_start,
        source_coverage_end=published.source_coverage_end,
        source_quality=sidecar_facts,
        source_quality_sha256=published.source_quality_sha256,
    )
    verified_bars, verified_facts = candidate_store.read_catalog_partition_quality(
        verified_partition
    )
    content = _content_body(verified_bars, verified_facts)
    manifest = {
        "state": "CANDIDATE_FROZEN",
        "operation": target.get("operation"),
        "symbol": partition.dataset.symbol,
        "contract": partition.dataset.series_or_contract,
        "month": month,
        "partition_id": target.get("partition_id"),
        "old_file_uri": relative,
        "old_file_sha256": target.get("old_file_sha256"),
        "old_source_quality_sha256": target.get("old_source_quality_sha256"),
        "candidate_file_uri": published.parquet_path.relative_to(candidate_root).as_posix(),
        "candidate_file_sha256": sha256(candidate_bytes).hexdigest(),
        "candidate_content_sha256": sha256(_canonical_json(content)).hexdigest(),
        "candidate_source_quality_sha256": published.source_quality_sha256,
        "candidate_quality_sidecar_uri": sidecar_path.relative_to(candidate_root).as_posix(),
        "candidate_quality_sidecar_sha256": sidecar_sha256,
        "row_count": published.row_count,
        "source_quality_count": len(facts),
        "affected_dates": sorted(day.isoformat() for day in affected),
        "coverage_start": _iso(published.coverage_start),
        "coverage_end": _iso(published.coverage_end),
        "source_coverage_start": _iso(published.source_coverage_start),
        "source_coverage_end": _iso(published.source_coverage_end),
    }
    return PreparedCandidate(manifest=manifest, partition=published)


def prepare_create_candidate(
    *,
    target: Mapping[str, Any],
    dataset: DatasetKey,
    candidate_root: Path,
    proofs: Mapping[tuple[str, str, date], SourceProof],
    bar_ends_by_day: Mapping[date, datetime],
) -> PreparedCandidate:
    """Freeze one previously absent mixed D1 partition from exact source rows."""
    if target.get("operation") != "CREATE_MIXED_UNION_PARTITION":
        raise CandidatePreparationError("TARGET_OPERATION_INVALID")
    month = str(target.get("month", ""))
    if dataset.symbol != target.get("symbol") or dataset.series_or_contract != target.get("contract"):
        raise CandidatePreparationError("TARGET_IDENTITY_DRIFT")
    year, month_number = (int(value) for value in month.split("-"))
    affected = {date.fromisoformat(str(value)) for value in target.get("affected_dates", ())}
    if set(bar_ends_by_day) != affected:
        raise CandidatePreparationError("CREATE_ENDPOINT_SCOPE_INVALID")
    expected_classifications = {
        date.fromisoformat(str(item.get("trading_day"))): item.get("source_classification")
        for item in target.get("expected_endpoint_classifications", ())
        if isinstance(item, Mapping)
    }
    if set(expected_classifications) != affected:
        raise CandidatePreparationError("CREATE_CLASSIFICATION_SCOPE_INVALID")

    bars: list[CanonicalBar] = []
    facts: list[NonpositiveCloseFact] = []
    for trading_day in sorted(affected):
        proof = proofs.get((dataset.symbol, dataset.series_or_contract, trading_day))
        if proof is None or proof.source_values is None:
            raise CandidatePreparationError("SOURCE_PROOF_MISSING")
        if proof.classification != expected_classifications[trading_day]:
            raise CandidatePreparationError("SOURCE_PROOF_CLASSIFICATION_MISMATCH")
        values = proof.source_values
        required = tuple(values.get(field) for field in (
            "open", "high", "low", "close", "volume", "turnover",
        ))
        if any(value is None for value in required):
            raise CandidatePreparationError("SOURCE_ROW_MISMATCH")
        open_, high, low, close, volume, turnover = cast(
            tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal],
            required,
        )
        bar_end = bar_ends_by_day[trading_day]
        if proof.classification == "POSITIVE_OHLC_SOURCE_FACT":
            bars.append(CanonicalBar(
                bar_end=bar_end,
                trading_day=trading_day,
                open=open_, high=high, low=low, close=close, volume=volume,
                turnover=turnover,
                open_interest=values.get("open_interest"),
            ))
        elif proof.classification == "NONPOSITIVE_CLOSE_SOURCE_FACT":
            facts.append(NonpositiveCloseFact(
                bar_end=bar_end,
                trading_day=trading_day,
                open=open_, high=high, low=low, close=close, volume=volume,
                turnover=turnover,
                open_interest=values.get("open_interest"),
                request_sha256=proof.request_sha256,
                response_sha256=proof.response_sha256,
                observed_at=proof.observed_at,
            ))
        else:
            raise CandidatePreparationError("SOURCE_PROOF_CLASSIFICATION_MISMATCH")

    expected = tuple(bar_ends_by_day[day] for day in sorted(affected))
    candidate_store = CanonicalMonthlyStore(candidate_root)
    published = candidate_store.publish(PublishRequest(
        dataset=dataset,
        year=year,
        month=month_number,
        bars=tuple(bars),
        expected_bar_ends=expected,
        nonpositive_close=tuple(facts),
    ))
    candidate_bytes = published.parquet_path.read_bytes()
    sidecar_path, sidecar_sha256 = _write_quality_sidecar(
        published.parquet_path.parent, tuple(facts)
    )
    sidecar_facts = _read_quality_sidecar(sidecar_path, sidecar_sha256)
    verified_partition = CatalogPartition(
        dataset=published.dataset,
        year=published.year,
        month=published.month,
        coverage_start=published.coverage_start,
        coverage_end=published.coverage_end,
        file_path=published.parquet_path,
        row_count=published.row_count,
        source_coverage_start=published.source_coverage_start,
        source_coverage_end=published.source_coverage_end,
        source_quality=sidecar_facts,
        source_quality_sha256=published.source_quality_sha256,
    )
    verified_bars, verified_facts = candidate_store.read_catalog_partition_quality(
        verified_partition
    )
    content = _content_body(verified_bars, verified_facts)
    manifest = {
        "state": "CANDIDATE_FROZEN",
        "operation": target.get("operation"),
        "symbol": dataset.symbol,
        "contract": dataset.series_or_contract,
        "month": month,
        "partition_id": None,
        "old_file_uri": None,
        "old_file_sha256": None,
        "old_source_quality_sha256": None,
        "candidate_file_uri": published.parquet_path.relative_to(candidate_root).as_posix(),
        "candidate_file_sha256": sha256(candidate_bytes).hexdigest(),
        "candidate_content_sha256": sha256(_canonical_json(content)).hexdigest(),
        "candidate_source_quality_sha256": published.source_quality_sha256,
        "candidate_quality_sidecar_uri": sidecar_path.relative_to(candidate_root).as_posix(),
        "candidate_quality_sidecar_sha256": sidecar_sha256,
        "row_count": published.row_count,
        "source_quality_count": len(facts),
        "affected_dates": sorted(day.isoformat() for day in affected),
        "expected_endpoints_sha256": target.get("expected_endpoints_sha256"),
        "coverage_start": _iso(published.coverage_start),
        "coverage_end": _iso(published.coverage_end),
        "source_coverage_start": _iso(published.source_coverage_start),
        "source_coverage_end": _iso(published.source_coverage_end),
    }
    return PreparedCandidate(manifest=manifest, partition=published)


def _read_raw_file(root: Path, relative: Path) -> tuple[bytes, datetime]:
    path = root / relative
    resolved = path.resolve(strict=True)
    if resolved == root or root not in resolved.parents:
        raise CandidatePreparationError("SOURCE_RAW_PATH_INVALID")
    try:
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
                raise OSError
            raw = os.read(fd, info.st_size + 1)
            if len(raw) != info.st_size:
                raise OSError
            return raw, datetime.fromtimestamp(info.st_mtime, tz=UTC)
        finally:
            os.close(fd)
    except OSError as exc:
        raise CandidatePreparationError("SOURCE_RAW_UNREADABLE") from exc


def _source_values(row: Mapping[str, Any]) -> dict[str, Decimal | None]:
    try:
        turnover = row.get("turnover", row.get("total_turnover"))
        values: dict[str, Decimal | None] = {
            field: Decimal(str(row[field]))
            for field in ("open", "high", "low", "close", "volume")
        }
        values["turnover"] = Decimal(str(turnover))
        values["open_interest"] = (
            None if row.get("open_interest") is None else Decimal(str(row["open_interest"]))
        )
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise CandidatePreparationError("SOURCE_RAW_VALUE_INVALID") from exc
    if any(value is not None and not value.is_finite() for value in values.values()):
        raise CandidatePreparationError("SOURCE_RAW_VALUE_INVALID")
    return values


def _classify_source_values(values: Mapping[str, Decimal | None]) -> str:
    prices = tuple(values.get(field) for field in ("open", "high", "low", "close"))
    if any(value is None for value in prices):
        return "PRICE_FIELDS_INVALID"
    open_, high, low, close = prices
    assert open_ is not None and high is not None and low is not None and close is not None
    if close <= 0:
        return "NONPOSITIVE_CLOSE_SOURCE_FACT"
    if open_ <= 0 or high <= 0 or low <= 0:
        return "ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT"
    return "POSITIVE_OHLC_SOURCE_FACT"


def _write_quality_sidecar(
    directory: Path, facts: tuple[SourceQualityFact, ...]
) -> tuple[Path, str]:
    payload = _canonical_json({
        "schema": "canonical-source-quality-sidecar-v1",
        "source_quality": [fact.to_record() for fact in facts],
    }) + b"\n"
    digest = sha256(payload).hexdigest()
    name = f"quality.{digest}.json"
    temporary = f".quality.{uuid.uuid4().hex}.tmp"
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            if os.write(fd, payload) != len(payload):
                raise OSError("short write")
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(
                temporary, name,
                src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing = _read_relative_bytes(directory_fd, name)
            if existing != payload:
                raise CandidatePreparationError("QUALITY_SIDECAR_CONFLICT") from None
        if _read_relative_bytes(directory_fd, name) != payload:
            raise CandidatePreparationError("QUALITY_SIDECAR_INVALID")
        os.fsync(directory_fd)
    except CandidatePreparationError:
        raise
    except OSError as exc:
        raise CandidatePreparationError("QUALITY_SIDECAR_WRITE_FAILED") from exc
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)
    return directory / name, digest


def _read_quality_sidecar(path: Path, expected_sha256: str) -> tuple[SourceQualityFact, ...]:
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        raw = _read_relative_bytes(directory_fd, path.name)
    finally:
        os.close(directory_fd)
    if sha256(raw).hexdigest() != expected_sha256:
        raise CandidatePreparationError("QUALITY_SIDECAR_HASH_MISMATCH")
    try:
        payload = json.loads(raw)
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema") != "canonical-source-quality-sidecar-v1"
            or not isinstance(payload.get("source_quality"), list)
        ):
            raise ValueError
        return tuple(source_quality_fact_from_record(item) for item in payload["source_quality"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CandidatePreparationError("QUALITY_SIDECAR_INVALID") from exc


def _read_relative_bytes(directory_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CandidatePreparationError("QUALITY_SIDECAR_INVALID")
        raw = os.read(fd, info.st_size + 1)
        if len(raw) != info.st_size:
            raise CandidatePreparationError("QUALITY_SIDECAR_INVALID")
        return raw
    finally:
        os.close(fd)


def _content_body(bars: tuple[Any, ...], facts: tuple[SourceQualityFact, ...]) -> dict[str, Any]:
    return {
        "bars": [_bar_record(bar) for bar in bars],
        "source_quality": [fact.to_record() for fact in facts],
    }


def _bar_record(bar: Any) -> dict[str, str]:
    return {
        "bar_end": bar.bar_end.isoformat(),
        "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": "" if bar.turnover is None else str(bar.turnover),
        "open_interest": "" if bar.open_interest is None else str(bar.open_interest),
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(letter not in "0123456789abcdef" for letter in value):
        raise CandidatePreparationError("SOURCE_PROOF_INVALID")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()
