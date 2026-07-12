from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION

ACTIVE_PRIMARY_PROVIDERS = frozenset({"local_parquet", "rqdata"})
ACTIVE_DATA_ROLE = "primary"


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
    ) -> list[dict[str, Any]]:
        files = self._find_files(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            provider=provider,
            data_role=data_role,
            passed_only=passed_only,
        )
        if not files:
            return []

        dedupe_partition = self._dedupe_partition_column(period)
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
                data_version,
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
            from read_parquet({self._paths_literal(files)}, union_by_name = true)
            where symbol = ?
              and contract = ?
              and period = ?
              and datetime >= ?
              and datetime <= ?
        """
        params: list[Any] = [symbol, contract, period, self._naive(start), self._naive(end)]

        if tail and limit is not None:
            sql = f"""
                select *
                from (
                    {base_select}
                ) deduped
                where dedupe_rank = 1
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
                where dedupe_rank = 1
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
        query = select(DataQualityReport).where(
            DataQualityReport.instrument_symbol == symbol,
            DataQualityReport.contract_code == contract,
            DataQualityReport.period == period,
            DataQualityReport.start_time <= end,
            DataQualityReport.end_time >= start,
        )
        if provider is not None:
            query = query.where(DataQualityReport.provider == provider)
        query = query.join(MarketDataFile, DataQualityReport.file_id == MarketDataFile.id)
        query = self._apply_active_filters(query, provider=provider, data_role=data_role)
        reports = [
            report
            for report in self.session.scalars(query)
            if isinstance(report.details, dict) and report.details.get("check_rule_version") == RQDATA_CANONICAL_CHECK_RULE_VERSION
        ]
        if not reports:
            return {
                "status": "unchecked",
                "missing_bars": 0,
                "duplicated_bars": 0,
                "abnormal_price_count": 0,
                "abnormal_volume_count": 0,
                "report_count": 0,
                "warning_reasons": [],
            }
        statuses = {report.status for report in reports}
        status = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
        warning_reasons = _quality_warning_reasons(reports, status)
        return {
            "status": status,
            "missing_bars": sum(report.missing_bars for report in reports),
            "duplicated_bars": sum(report.duplicated_bars for report in reports),
            "abnormal_price_count": sum(report.abnormal_price_count for report in reports),
            "abnormal_volume_count": sum(report.abnormal_volume_count for report in reports),
            "report_count": len(reports),
            "warning_reasons": warning_reasons,
        }

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
    ) -> list[Path]:
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
        files = []
        for market_file in self.session.scalars(query.order_by(MarketDataFile.start_time)):
            path = Path(market_file.file_path)
            files.append(path if path.is_absolute() else self.project_root / path)
        return files

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
