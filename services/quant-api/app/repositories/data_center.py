from sqlalchemy import select
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
    return list(session.scalars(select(Contract).order_by(Contract.exchange_code, Contract.instrument_symbol, Contract.contract_code)))


def list_download_tasks(session: Session) -> list[DataDownloadTask]:
    return list(session.scalars(select(DataDownloadTask).order_by(DataDownloadTask.created_at.desc(), DataDownloadTask.id.desc())))


def list_quality_reports(session: Session) -> list[DataQualityReport]:
    return list(session.scalars(select(DataQualityReport).order_by(DataQualityReport.created_at.desc(), DataQualityReport.id.desc())))


def list_coverage(session: Session) -> list[MarketDataFile]:
    return list(session.scalars(select(MarketDataFile).order_by(MarketDataFile.updated_at.desc(), MarketDataFile.id.desc())))
