from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    DataDownloadTask,
    DataQualityReport,
    DataSource,
    Exchange,
    Instrument,
    MarketDataFile,
)


def list_sources(session: Session) -> list[DataSource]:
    return list(session.scalars(select(DataSource).order_by(DataSource.priority, DataSource.id)))


def list_exchanges(session: Session) -> list[Exchange]:
    return list(session.scalars(select(Exchange).order_by(Exchange.code)))


def list_instruments(session: Session) -> list[Instrument]:
    return list(session.scalars(select(Instrument).order_by(Instrument.exchange_code, Instrument.symbol)))


def list_contracts(session: Session) -> list[Contract]:
    return list(
        session.scalars(
            select(Contract).order_by(Contract.exchange_code, Contract.instrument_symbol, Contract.contract_code)
        )
    )


def list_download_tasks(session: Session) -> list[DataDownloadTask]:
    return list(
        session.scalars(select(DataDownloadTask).order_by(DataDownloadTask.created_at.desc(), DataDownloadTask.id.desc()))
    )


def list_quality_reports(session: Session) -> list[DataQualityReport]:
    return list(
        session.scalars(
            select(DataQualityReport).order_by(DataQualityReport.created_at.desc(), DataQualityReport.id.desc())
        )
    )


def list_coverage(session: Session) -> list[MarketDataFile]:
    return list(
        session.scalars(select(MarketDataFile).order_by(MarketDataFile.updated_at.desc(), MarketDataFile.id.desc()))
    )


def _apply_market_file_filters(
    stmt: Select,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    quality: str | None = None,
    provider: str | None = None,
) -> Select:
    if symbol:
        stmt = stmt.where(MarketDataFile.instrument_symbol == symbol)
    if contract:
        stmt = stmt.where(MarketDataFile.contract_code == contract)
    if period:
        stmt = stmt.where(MarketDataFile.period == period)
    if quality:
        stmt = stmt.where(MarketDataFile.quality_status == quality)
    if provider:
        stmt = stmt.where(MarketDataFile.provider == provider)
    return stmt


def count_coverage(
    session: Session,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    quality: str | None = None,
    provider: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(MarketDataFile)
    stmt = _apply_market_file_filters(
        stmt, symbol=symbol, contract=contract, period=period, quality=quality, provider=provider
    )
    return int(session.scalar(stmt) or 0)


def list_coverage_page(
    session: Session,
    *,
    limit: int,
    offset: int,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    quality: str | None = None,
    provider: str | None = None,
) -> list[MarketDataFile]:
    stmt = select(MarketDataFile).order_by(MarketDataFile.updated_at.desc(), MarketDataFile.id.desc())
    stmt = _apply_market_file_filters(
        stmt, symbol=symbol, contract=contract, period=period, quality=quality, provider=provider
    )
    stmt = stmt.offset(offset).limit(limit)
    return list(session.scalars(stmt))


def _apply_task_filters(
    stmt: Select,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    provider: str | None = None,
    status: str | None = None,
) -> Select:
    if symbol:
        stmt = stmt.where(DataDownloadTask.instrument_symbol == symbol)
    if contract:
        stmt = stmt.where(DataDownloadTask.contract_code == contract)
    if period:
        stmt = stmt.where(DataDownloadTask.period == period)
    if provider:
        stmt = stmt.where(DataDownloadTask.provider == provider)
    if status:
        stmt = stmt.where(DataDownloadTask.status == status)
    return stmt


def count_download_tasks(
    session: Session,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    provider: str | None = None,
    status: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(DataDownloadTask)
    stmt = _apply_task_filters(stmt, symbol=symbol, contract=contract, period=period, provider=provider, status=status)
    return int(session.scalar(stmt) or 0)


def list_download_tasks_page(
    session: Session,
    *,
    limit: int,
    offset: int,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    provider: str | None = None,
    status: str | None = None,
) -> list[DataDownloadTask]:
    stmt = select(DataDownloadTask).order_by(DataDownloadTask.created_at.desc(), DataDownloadTask.id.desc())
    stmt = _apply_task_filters(stmt, symbol=symbol, contract=contract, period=period, provider=provider, status=status)
    stmt = stmt.offset(offset).limit(limit)
    return list(session.scalars(stmt))


def _apply_quality_filters(
    stmt: Select,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    quality: str | None = None,
    provider: str | None = None,
) -> Select:
    if symbol:
        stmt = stmt.where(DataQualityReport.instrument_symbol == symbol)
    if contract:
        stmt = stmt.where(DataQualityReport.contract_code == contract)
    if period:
        stmt = stmt.where(DataQualityReport.period == period)
    if quality:
        stmt = stmt.where(DataQualityReport.status == quality)
    if provider:
        stmt = stmt.where(DataQualityReport.provider == provider)
    return stmt


def count_quality_reports(
    session: Session,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    quality: str | None = None,
    provider: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(DataQualityReport)
    stmt = _apply_quality_filters(
        stmt, symbol=symbol, contract=contract, period=period, quality=quality, provider=provider
    )
    return int(session.scalar(stmt) or 0)


def list_quality_reports_page(
    session: Session,
    *,
    limit: int,
    offset: int,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    quality: str | None = None,
    provider: str | None = None,
) -> list[DataQualityReport]:
    stmt = select(DataQualityReport).order_by(DataQualityReport.created_at.desc(), DataQualityReport.id.desc())
    stmt = _apply_quality_filters(
        stmt, symbol=symbol, contract=contract, period=period, quality=quality, provider=provider
    )
    stmt = stmt.offset(offset).limit(limit)
    return list(session.scalars(stmt))
