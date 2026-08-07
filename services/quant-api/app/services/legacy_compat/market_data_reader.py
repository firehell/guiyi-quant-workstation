"""Profile/filesystem historical bar reader (legacy compatibility only).

Active historical consumers must use MarketDataService / CanonicalBarLoader.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.market_data_roles import ACTIVE_DATA_ROLE, ACTIVE_PRIMARY_PROVIDERS
from app.services.data_profile_registry import DataProfileRegistry
from app.services.profile_lineage import ProfileLineage, ProfileLineageResolver, resolve_source_interval
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION

logger = logging.getLogger(__name__)


def _worst_quality_status(statuses: set[str]) -> str:
    for status in ("failed", "warning", "unchecked", "passed"):
        if status in statuses:
            return status
    return "unchecked"

# ---------------------------------------------------------------------------
# Historical bar unique-key definition and data-source priority (DATA-FINAL-002)
# ---------------------------------------------------------------------------
# Unique key for historical 1d bars: symbol + contract_role + trading_day + interval
#   - contract_role: "dominant_main" for *.MAIN, "actual_contract" otherwise
#   - _dedupe_partition_column() already partitions 1d/1w by trading_day
#   - _find_files() filters by symbol + contract + period
#   => the effective unique key is (symbol, contract, trading_day, period)
#
# Data-source priority (high → low):
#   1. direct 1d    — N/A (1d is NOT in RQDATA_DIRECT_PERIODS, always derived from 1m at ingest)
#   2. historical   — Parquet files (data_role='primary'), queried via _find_files()
#   3. derived 1d   — from 1m aggregation (bar_aggregation.py), only used at ingest to produce Parquet
#   4. live 1d      — retired (poll-live / Task06); not merged with historical
#
# Conclusion: API query for 1d only goes through historical Parquet path.
#   Conflict detection only needs to operate within historical files.
# ---------------------------------------------------------------------------


def _quality_warning_reasons(reports: list[DataQualityReport], status: str) -> list[str]:
    if status != "warning":
        return []
    reasons: list[str] = []
    abnormal_price_count = sum(report.abnormal_price_count for report in reports)
    abnormal_volume_count = sum(report.abnormal_volume_count for report in reports)
    missing_bars = sum(report.missing_bars for report in reports)
    duplicated_bars = sum(report.duplicated_bars for report in reports)
    if abnormal_price_count:
        reasons.append(f"abnormal_price_count={abnormal_price_count}")
    if abnormal_volume_count:
        reasons.append(f"abnormal_volume_count={abnormal_volume_count}")
    if missing_bars:
        reasons.append(f"missing_bars={missing_bars}")
    if duplicated_bars:
        reasons.append(f"duplicated_bars={duplicated_bars}")
    if not reasons:
        reasons.append("quality_report_warning")
    return reasons


class MarketDataReader:
    def __init__(self, session: Session, project_root: Path = PROJECT_ROOT) -> None:
        self.session = session
        self.project_root = project_root

    def load_bars_from_market_file(
        self,
        *,
        market_data_file_id: int,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        passed_only: bool = True,
        expected_provider: str | None = None,
        expected_data_role: str | None = None,
        expected_quality_status: str | None = None,
        expected_data_version: str | None = None,
        expected_checksum: str | None = None,
        limit: int | None = None,
        tail: bool = False,
    ) -> list[dict[str, Any]]:
        """Read one server-selected immutable asset without resolving current bindings."""
        market_file = self.session.get(MarketDataFile, market_data_file_id)
        if market_file is None:
            raise ValueError("market_data_file_missing")
        if (
            market_file.instrument_symbol != symbol
            or market_file.contract_code != contract
            or market_file.period != period
        ):
            raise ValueError("market_data_file_identity_mismatch")
        if market_file.provider not in ACTIVE_PRIMARY_PROVIDERS or market_file.data_role != ACTIVE_DATA_ROLE:
            raise ValueError("market_data_file_source_blocked")
        if passed_only and market_file.quality_status != "passed":
            raise ValueError("market_data_file_quality_blocked")
        expected_values = {
            "provider": expected_provider,
            "data_role": expected_data_role,
            "quality_status": expected_quality_status,
            "data_version": expected_data_version,
            "checksum": expected_checksum,
        }
        for field, expected in expected_values.items():
            if expected is not None and getattr(market_file, field) != expected:
                raise ValueError(f"market_data_file_{field}_mismatch")
        if self._naive(market_file.start_time) > self._naive(start) or self._naive(market_file.end_time) < self._naive(end):
            raise ValueError("market_data_file_range_not_covered")
        if not self._market_file_path(market_file).is_file():
            raise ValueError("market_data_file_physical_missing")

        return self._load_bars_from_market_files(
            [market_file],
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            limit=limit,
            tail=tail,
            deduplicate=False,
        )

    def load_bars_from_market_files(
        self,
        *,
        market_data_file_ids: Sequence[int],
        asset_evidence: Sequence[Mapping[str, Any]],
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        passed_only: bool = False,
        limit: int | None = None,
        tail: bool = False,
        deduplicate: bool = True,
        naive_timezone: ZoneInfo | None = None,
    ) -> list[dict[str, Any]]:
        """Read the exact frozen asset set without resolving current active files."""
        market_files = self._exact_market_files(
            market_data_file_ids=market_data_file_ids,
            asset_evidence=asset_evidence,
            symbol=symbol,
            contract=contract,
            period=period,
            passed_only=passed_only,
        )
        return self._load_bars_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            limit=limit,
            tail=tail,
            deduplicate=deduplicate,
            naive_timezone=naive_timezone,
        )

    def load_bars(
        self,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        provider: str | None = None,
        data_role: str | None = None,
        limit: int | None = None,
        *,
        tail: bool = False,
        passed_only: bool = False,
        profile_id: str | None = None,
    ) -> list[dict[str, Any]]:
        market_files = self.find_market_files(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            provider=provider,
            data_role=data_role,
            passed_only=passed_only,
            profile_id=profile_id,
        )
        return self._load_bars_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            limit=limit,
            tail=tail,
            deduplicate=True,
        )

    def _load_bars_from_market_files(
        self,
        market_files: Sequence[MarketDataFile],
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        limit: int | None,
        tail: bool,
        deduplicate: bool,
        naive_timezone: ZoneInfo | None = None,
    ) -> list[dict[str, Any]]:
        if not market_files:
            return []

        files = [self._market_file_path(item) for item in market_files]
        dedupe_partition = self._dedupe_partition_column(period)
        dedupe_rank_select = (
            f""",
                row_number() over (
                    partition by {dedupe_partition}
                    order by
                        case provider
                            when 'rqdata' then 0
                            when 'local_parquet' then 1
                            else 2
                        end,
                        datetime desc
                ) as dedupe_rank
            """
            if deduplicate
            else ""
        )
        base_select = f"""
            select
                symbol,
                contract,
                exchange,
                datetime,
                trading_day,
                open,
                high,
                low,
                close,
                volume,
                open_interest,
                turnover,
                period,
                provider,
                data_version
                {dedupe_rank_select}
            from read_parquet({self._paths_literal(files)}, union_by_name = true)
            where symbol = ?
              and contract = ?
              and period = ?
              and datetime >= ?
              and datetime <= ?
        """
        params: list[Any] = [
            symbol,
            contract,
            period,
            self._query_naive(start, naive_timezone),
            self._query_naive(end, naive_timezone),
        ]

        dedupe_filter = "where dedupe_rank = 1" if deduplicate else ""
        if tail and limit is not None:
            sql = f"""
                select *
                from (
                    {base_select}
                ) deduped
                {dedupe_filter}
                order by datetime desc
                limit ?
            """
            params.append(limit)
            sql = f"""
                select *
                from ({sql}) latest
                order by
                    datetime,
                    case provider
                        when 'rqdata' then 0
                        when 'local_parquet' then 1
                        else 2
                    end
            """
        else:
            sql = f"""
                select *
                from (
                    {base_select}
                ) deduped
                {dedupe_filter}
                order by
                    datetime,
                    case provider
                        when 'rqdata' then 0
                        when 'local_parquet' then 1
                        else 2
                    end
            """
            if limit is not None:
                sql += " limit ?"
                params.append(limit)

        with duckdb.connect(database=":memory:") as connection:
            frame = connection.execute(sql, params).fetchdf()
        return [self._row_to_bar(row) for row in frame.to_dict("records")]

    def load_latest_bars(
        self,
        symbol: str,
        contract: str,
        period: str,
        limit: int,
        provider: str | None = None,
        data_role: str | None = None,
        *,
        passed_only: bool = False,
        profile_id: str | None = None,
    ) -> list[dict[str, Any]]:
        files = self._find_files(
            symbol=symbol,
            contract=contract,
            period=period,
            start=datetime.min,
            end=datetime.max,
            provider=provider,
            data_role=data_role,
            passed_only=passed_only,
            profile_id=profile_id,
        )
        if not files:
            return []

        sql = f"""
            select *
            from (
                select
                    symbol,
                    contract,
                    exchange,
                    datetime,
                    trading_day,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    open_interest,
                    turnover,
                    period,
                    provider,
                    data_version
                from read_parquet({self._paths_literal(files)}, union_by_name = true)
                where symbol = ?
                  and contract = ?
                  and period = ?
                order by datetime desc
                limit ?
            )
            order by
                datetime,
                case provider
                    when 'rqdata' then 0
                    when 'local_parquet' then 1
                    else 2
                end
        """
        with duckdb.connect(database=":memory:") as connection:
            frame = connection.execute(sql, [symbol, contract, period, limit]).fetchdf()
        return [self._row_to_bar(row) for row in frame.to_dict("records")]

    def get_cross_file_conflicts(
        self,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        provider: str | None = None,
        data_role: str | None = None,
        *,
        max_details: int = 20,
    ) -> list[dict[str, Any]]:
        """Detect cross-file OHLCV conflicts for the same unique key.

        A *conflict* occurs when the same dedupe key (trading_day for 1d/1w,
        datetime for intraday) appears in multiple active Parquet files with
        **different** OHLCV values.  Same-value duplicates are NOT conflicts —
        they are the expected scenario documented in DATA-FINAL-001.

        Returns a list of conflict dicts, each containing:
          - dedupe_key: the partition key value (e.g. "2020-01-02")
          - occurrence_count: how many rows share this key
          - conflicting_fields: list of field names that differ
          - details: per-file values (open/high/low/close/volume/data_version/file_path)
        """
        market_files = self.find_market_files(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            provider=provider,
            data_role=data_role,
        )
        return self._get_cross_file_conflicts_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            max_details=max_details,
        )

    def get_cross_file_conflicts_from_market_files(
        self,
        *,
        market_data_file_ids: Sequence[int],
        asset_evidence: Sequence[Mapping[str, Any]],
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        max_details: int = 20,
    ) -> list[dict[str, Any]]:
        """Inspect conflicts in the exact frozen asset set only."""
        market_files = self._exact_market_files(
            market_data_file_ids=market_data_file_ids,
            asset_evidence=asset_evidence,
            symbol=symbol,
            contract=contract,
            period=period,
            passed_only=False,
        )
        return self._get_cross_file_conflicts_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            max_details=max_details,
        )

    def _get_cross_file_conflicts_from_market_files(
        self,
        market_files: Sequence[MarketDataFile],
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        max_details: int,
    ) -> list[dict[str, Any]]:
        files = [self._market_file_path(item) for item in market_files]
        if len(files) <= 1:
            return []

        dedupe_partition = self._dedupe_partition_column(period)
        paths_literal = self._paths_literal(files)

        conflict_sql = f"""
            WITH grouped AS (
                SELECT
                    {dedupe_partition} AS dedupe_key,
                    COUNT(*) AS occurrence_count,
                    COUNT(DISTINCT CAST(open AS VARCHAR)) AS distinct_open,
                    COUNT(DISTINCT CAST(high AS VARCHAR)) AS distinct_high,
                    COUNT(DISTINCT CAST(low AS VARCHAR)) AS distinct_low,
                    COUNT(DISTINCT CAST(close AS VARCHAR)) AS distinct_close,
                    COUNT(DISTINCT CAST(volume AS VARCHAR)) AS distinct_volume,
                    MIN(CAST(open AS DOUBLE)) AS min_open,
                    MAX(CAST(open AS DOUBLE)) AS max_open,
                    MIN(CAST(close AS DOUBLE)) AS min_close,
                    MAX(CAST(close AS DOUBLE)) AS max_close,
                    MIN(CAST(volume AS DOUBLE)) AS min_volume,
                    MAX(CAST(volume AS DOUBLE)) AS max_volume
                FROM read_parquet({paths_literal}, union_by_name = true)
                WHERE symbol = ?
                  AND contract = ?
                  AND period = ?
                  AND datetime >= ?
                  AND datetime <= ?
                GROUP BY {dedupe_partition}
                HAVING COUNT(*) > 1
            )
            SELECT * FROM grouped
            WHERE distinct_open > 1
               OR distinct_high > 1
               OR distinct_low > 1
               OR distinct_close > 1
               OR distinct_volume > 1
            ORDER BY dedupe_key
        """
        params: list[Any] = [symbol, contract, period, self._naive(start), self._naive(end)]

        with duckdb.connect(database=":memory:") as connection:
            frame = connection.execute(conflict_sql, params).fetchdf()

        if frame.empty:
            return []

        conflicts: list[dict[str, Any]] = []
        for row in frame.to_dict("records"):
            conflicting_fields: list[str] = []
            if row.get("distinct_open", 0) > 1:
                conflicting_fields.append("open")
            if row.get("distinct_high", 0) > 1:
                conflicting_fields.append("high")
            if row.get("distinct_low", 0) > 1:
                conflicting_fields.append("low")
            if row.get("distinct_close", 0) > 1:
                conflicting_fields.append("close")
            if row.get("distinct_volume", 0) > 1:
                conflicting_fields.append("volume")

            dedupe_key = row["dedupe_key"]
            if isinstance(dedupe_key, pd.Timestamp):
                dedupe_key = dedupe_key.strftime("%Y-%m-%d %H:%M:%S")
            else:
                dedupe_key = str(dedupe_key)

            conflicts.append({
                "dedupe_key": dedupe_key,
                "occurrence_count": int(row["occurrence_count"]),
                "conflicting_fields": conflicting_fields,
                "value_ranges": {
                    "open": [float(row["min_open"]), float(row["max_open"])] if row.get("distinct_open", 0) > 1 else None,
                    "close": [float(row["min_close"]), float(row["max_close"])] if row.get("distinct_close", 0) > 1 else None,
                    "volume": [float(row["min_volume"]), float(row["max_volume"])] if row.get("distinct_volume", 0) > 1 else None,
                },
                "file_count": len(files),
                "assets": [self.asset_evidence(item) for item in market_files],
            })
            if len(conflicts) >= max_details:
                break

        return conflicts

    def get_quality_status(
        self,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        provider: str | None = None,
        data_role: str | None = None,
    ) -> dict[str, Any]:
        market_files = self.find_market_files(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            provider=provider,
            data_role=data_role,
        )
        return self._get_quality_status_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
        )

    def get_quality_status_from_market_files(
        self,
        *,
        market_data_file_ids: Sequence[int],
        asset_evidence: Sequence[Mapping[str, Any]],
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Return quality for the exact frozen asset set without active selection."""
        market_files = self._exact_market_files(
            market_data_file_ids=market_data_file_ids,
            asset_evidence=asset_evidence,
            symbol=symbol,
            contract=contract,
            period=period,
            passed_only=False,
        )
        return self._get_quality_status_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
        )

    def _get_quality_status_from_market_files(
        self,
        market_files: Sequence[MarketDataFile],
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        asset_statuses = {(item.quality_status or "unchecked").lower() for item in market_files}
        file_ids = [item.id for item in market_files]
        query = select(DataQualityReport).where(
            DataQualityReport.file_id.in_(file_ids),
            DataQualityReport.instrument_symbol == symbol,
            DataQualityReport.contract_code == contract,
            DataQualityReport.period == period,
            DataQualityReport.start_time <= end,
            DataQualityReport.end_time >= start,
        )
        reports = [
            report
            for report in self.session.scalars(query)
            if isinstance(report.details, dict) and report.details.get("check_rule_version") == RQDATA_CANONICAL_CHECK_RULE_VERSION
        ]
        if not reports:
            # Still check cross-file conflicts even without quality reports
            conflicts = self._get_cross_file_conflicts_from_market_files(
                market_files,
                symbol=symbol,
                contract=contract,
                period=period,
                start=start,
                end=end,
                max_details=20,
            )
            cross_file_conflicts = len(conflicts)
            status = _worst_quality_status(asset_statuses | ({"warning"} if cross_file_conflicts else set()))
            warning_reasons = [
                f"market_data_file_quality={asset_status}"
                for asset_status in sorted(asset_statuses)
                if asset_status in {"warning", "failed"}
            ]
            if cross_file_conflicts:
                warning_reasons.append(f"cross_file_conflicts={cross_file_conflicts}")
            return {
                "status": status,
                "missing_bars": 0,
                "duplicated_bars": 0,
                "abnormal_price_count": 0,
                "abnormal_volume_count": 0,
                "report_count": 0,
                "warning_reasons": warning_reasons,
                "cross_file_conflicts": cross_file_conflicts,
                "conflict_details": conflicts if conflicts else None,
            }
        statuses = {(report.status or "unchecked").lower() for report in reports}
        status = _worst_quality_status(statuses | asset_statuses)
        warning_reasons = _quality_warning_reasons(reports, status)
        warning_reasons.extend(
            f"market_data_file_quality={asset_status}"
            for asset_status in sorted(asset_statuses)
            if asset_status in {"warning", "failed"}
        )

        # Cross-file conflict detection (DATA-FINAL-002)
        conflicts = self._get_cross_file_conflicts_from_market_files(
            market_files,
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            max_details=20,
        )
        cross_file_conflicts = len(conflicts)
        if cross_file_conflicts > 0 and status == "passed":
            status = "warning"
        if cross_file_conflicts > 0:
            warning_reasons = list(warning_reasons) + [f"cross_file_conflicts={cross_file_conflicts}"]
        warning_reasons = list(dict.fromkeys(warning_reasons))

        if cross_file_conflicts > 0:
            logger.warning(
                "cross_file_conflicts detected symbol=%s contract=%s period=%s count=%d",
                symbol, contract, period, cross_file_conflicts,
            )

        return {
            "status": status,
            "missing_bars": sum(report.missing_bars for report in reports),
            "duplicated_bars": sum(report.duplicated_bars for report in reports),
            "abnormal_price_count": sum(report.abnormal_price_count for report in reports),
            "abnormal_volume_count": sum(report.abnormal_volume_count for report in reports),
            "report_count": len(reports),
            "warning_reasons": warning_reasons,
            "cross_file_conflicts": cross_file_conflicts,
            "conflict_details": conflicts if conflicts else None,
        }

    def resolve_profile_lineage(
        self,
        *,
        consumer: str,
        symbol: str,
        contract: str,
        period: str,
        profile_id: str | None,
        allow_warning_quality: bool = False,
    ) -> ProfileLineage:
        return ProfileLineageResolver(self.session).resolve(
            consumer=consumer,  # type: ignore[arg-type]
            symbol=symbol,
            contract=contract,
            period=period,
            profile_id=profile_id,
            allow_warning_quality=allow_warning_quality,
        )

    def get_coverage(
        self,
        symbol: str | None = None,
        contract: str | None = None,
        period: str | None = None,
        data_role: str | None = None,
        *,
        passed_only: bool = False,
    ) -> list[MarketDataFile]:
        query = select(MarketDataFile).where(MarketDataFile.quality_status != "failed", MarketDataFile.file_path.contains("/canonical/bars/"))
        if passed_only:
            query = query.where(MarketDataFile.quality_status == "passed")
        query = self._apply_active_filters(query, provider=None, data_role=data_role)
        if symbol is not None:
            query = query.where(MarketDataFile.instrument_symbol == symbol)
        if contract is not None:
            query = query.where(MarketDataFile.contract_code == contract)
        if period is not None:
            query = query.where(MarketDataFile.period == period)
        return list(self.session.scalars(query.order_by(MarketDataFile.start_time)))

    def find_market_files(
        self,
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        provider: str | None = None,
        data_role: str | None = None,
        passed_only: bool = False,
        profile_id: str | None = None,
    ) -> list[MarketDataFile]:
        if profile_id:
            market_file = DataProfileRegistry(self.session, self.project_root).resolve_active_market_file(
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
            )
            return [market_file] if market_file is not None else []
        query = select(MarketDataFile).where(
            MarketDataFile.instrument_symbol == symbol,
            MarketDataFile.contract_code == contract,
            MarketDataFile.period == period,
            MarketDataFile.start_time <= end,
            MarketDataFile.end_time >= start,
            MarketDataFile.quality_status != "failed",
            MarketDataFile.file_path.contains("/canonical/bars/"),
        )
        if passed_only:
            query = query.where(MarketDataFile.quality_status == "passed")
        query = self._apply_active_filters(query, provider=provider, data_role=data_role)
        return list(self.session.scalars(query.order_by(MarketDataFile.start_time, MarketDataFile.id)))

    def asset_evidence(self, market_file: MarketDataFile) -> dict[str, Any]:
        source_interval, source_interval_basis = resolve_source_interval(
            self.session,
            market_file,
            project_root=self.project_root,
        )
        return {
            "market_data_file_id": market_file.id,
            "data_version": market_file.data_version,
            "provider": market_file.provider,
            "data_role": market_file.data_role,
            "quality_status": market_file.quality_status,
            "checksum": market_file.checksum,
            "start_time": market_file.start_time.isoformat(),
            "end_time": market_file.end_time.isoformat(),
            "source_interval": source_interval,
            "source_interval_basis": source_interval_basis,
        }

    def _exact_market_files(
        self,
        *,
        market_data_file_ids: Sequence[int],
        asset_evidence: Sequence[Mapping[str, Any]],
        symbol: str,
        contract: str,
        period: str,
        passed_only: bool,
    ) -> list[MarketDataFile]:
        file_ids = tuple(market_data_file_ids)
        evidence_items = tuple(asset_evidence)
        if len(file_ids) != len(evidence_items) or len(set(file_ids)) != len(file_ids):
            raise ValueError("market_data_file_identity_mismatch")

        market_files: list[MarketDataFile] = []
        for market_data_file_id, frozen_evidence in zip(file_ids, evidence_items, strict=True):
            if (
                not isinstance(market_data_file_id, int)
                or isinstance(market_data_file_id, bool)
                or frozen_evidence.get("market_data_file_id") != market_data_file_id
            ):
                raise ValueError("market_data_file_identity_mismatch")
            market_file = self.session.get(
                MarketDataFile,
                market_data_file_id,
                populate_existing=True,
            )
            if market_file is None:
                raise ValueError("market_data_file_missing")
            if (
                market_file.instrument_symbol != symbol
                or market_file.contract_code != contract
                or market_file.period != period
            ):
                raise ValueError("market_data_file_identity_mismatch")
            if (
                market_file.provider not in ACTIVE_PRIMARY_PROVIDERS
                or market_file.data_role != ACTIVE_DATA_ROLE
                or market_file.quality_status == "failed"
            ):
                raise ValueError("market_data_file_source_blocked")
            if passed_only and market_file.quality_status != "passed":
                raise ValueError("market_data_file_quality_blocked")
            if not self._market_file_path(market_file).is_file():
                raise ValueError("market_data_file_physical_missing")

            current_evidence = self.asset_evidence(market_file)
            for field, actual in current_evidence.items():
                if frozen_evidence.get(field) != actual:
                    error_field = "identity" if field == "market_data_file_id" else field
                    raise ValueError(f"market_data_file_{error_field}_mismatch")
            market_files.append(market_file)
        return market_files

    def _find_files(
        self,
        symbol: str,
        contract: str,
        period: str,
        start: datetime,
        end: datetime,
        provider: str | None,
        data_role: str | None,
        passed_only: bool = False,
        profile_id: str | None = None,
    ) -> list[Path]:
        return [
            self._market_file_path(item)
            for item in self.find_market_files(
                symbol=symbol,
                contract=contract,
                period=period,
                start=start,
                end=end,
                provider=provider,
                data_role=data_role,
                passed_only=passed_only,
                profile_id=profile_id,
            )
        ]

    def _market_file_path(self, market_file: MarketDataFile) -> Path:
        path = Path(market_file.file_path)
        return path if path.is_absolute() else self.project_root / path

    @staticmethod
    def _apply_active_filters(query: Any, *, provider: str | None, data_role: str | None) -> Any:
        requested_role = data_role or ACTIVE_DATA_ROLE
        if requested_role != ACTIVE_DATA_ROLE:
            return query.where(False)
        if provider is not None:
            if provider not in ACTIVE_PRIMARY_PROVIDERS:
                return query.where(False)
            return query.where(MarketDataFile.provider == provider, MarketDataFile.data_role == ACTIVE_DATA_ROLE)
        return query.where(MarketDataFile.provider.in_(ACTIVE_PRIMARY_PROVIDERS), MarketDataFile.data_role == ACTIVE_DATA_ROLE)

    @staticmethod
    def _paths_literal(paths: list[Path]) -> str:
        escaped = [str(path).replace("'", "''") for path in paths]
        return "[" + ", ".join(f"'{path}'" for path in escaped) + "]"

    @staticmethod
    def _dedupe_partition_column(period: str) -> str:
        normalized = period.strip().lower()
        if normalized in {"1d", "1w"}:
            return "coalesce(cast(trading_day as varchar), cast(datetime as varchar))"
        return "datetime"

    @staticmethod
    def _naive(value: datetime) -> datetime:
        return value.replace(tzinfo=None)

    @staticmethod
    def _query_naive(
        value: datetime,
        timezone: ZoneInfo | None,
    ) -> datetime:
        if timezone is None or value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=None)
        return value.astimezone(timezone).replace(tzinfo=None)

    @staticmethod
    def _row_to_bar(row: dict[str, Any]) -> dict[str, Any]:
        timestamp = row["datetime"].to_pydatetime() if isinstance(row["datetime"], pd.Timestamp) else row["datetime"]
        trading_day = row["trading_day"]
        if isinstance(trading_day, pd.Timestamp):
            trading_day = trading_day.date()
        open_interest = row.get("open_interest")
        return {
            "time": timestamp.isoformat(),
            "datetime": timestamp,
            "trading_day": trading_day,
            "symbol": row["symbol"],
            "contract": row["contract"],
            "exchange": row["exchange"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
            "openInterest": None if pd.isna(open_interest) else float(open_interest),
            "turnover": None if pd.isna(row.get("turnover")) else float(row["turnover"]),
            "period": row["period"],
            "provider": row["provider"],
            "data_version": row.get("data_version"),
        }
