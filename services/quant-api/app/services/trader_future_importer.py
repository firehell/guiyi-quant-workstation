from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import os

import pandas as pd
from sqlalchemy import delete, select
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

PROVIDER = "trader_future_data"
DATA_TYPE = "main_continuous_kline"

PERIOD_DIRS = {
    "5m": "5分钟主力连续",
    "15m": "15 分钟主力连续",
    "30m": "30 分钟主力连续",
    "60m": "60 分钟主力连续",
    "1d": "日线主力连续",
}

PERIOD_FILE_SUFFIX = {
    "5m": "5分钟",
    "15m": "15分钟",
    "30m": "30分钟",
    "60m": "60分钟",
    "1d": "日线",
}

INSTRUMENT_SYMBOLS = {
    "螺纹": ("rb", "SHFE", "black"),
    "热卷": ("hc", "SHFE", "black"),
    "铁矿石": ("i", "DCE", "black"),
    "焦炭": ("j", "DCE", "black"),
    "焦煤": ("jm", "DCE", "black"),
    "硅铁": ("SF", "CZCE", "black"),
    "锰硅": ("SM", "CZCE", "black"),
    "玻璃": ("FG", "CZCE", "chemical"),
    "纯碱": ("SA", "CZCE", "chemical"),
    "甲醇": ("MA", "CZCE", "chemical"),
    "PTA": ("TA", "CZCE", "chemical"),
    "PVC": ("v", "DCE", "chemical"),
    "PP": ("pp", "DCE", "chemical"),
    "塑料": ("l", "DCE", "chemical"),
    "苯乙烯": ("eb", "DCE", "chemical"),
    "乙二醇": ("eg", "DCE", "chemical"),
    "原油": ("sc", "INE", "energy"),
    "燃油": ("fu", "SHFE", "energy"),
    "低硫燃油": ("lu", "INE", "energy"),
    "沥青": ("bu", "SHFE", "energy"),
    "液化气": ("pg", "DCE", "energy"),
    "沪铜": ("cu", "SHFE", "metal"),
    "沪铝": ("al", "SHFE", "metal"),
    "沪锌": ("zn", "SHFE", "metal"),
    "沪铅": ("pb", "SHFE", "metal"),
    "沪镍": ("ni", "SHFE", "metal"),
    "沪锡": ("sn", "SHFE", "metal"),
    "沪金": ("au", "SHFE", "precious_metal"),
    "沪银": ("ag", "SHFE", "precious_metal"),
    "橡胶": ("ru", "SHFE", "chemical"),
    "20号胶": ("nr", "INE", "chemical"),
    "不锈钢": ("ss", "SHFE", "black"),
    "氧化铝": ("ao", "SHFE", "metal"),
    "碳酸锂": ("lc", "GFEX", "chemical"),
    "工业硅": ("si", "GFEX", "chemical"),
    "沪深300股指": ("IF", "CFFEX", "financial"),
    "中证500股指": ("IC", "CFFEX", "financial"),
    "中证1000股指": ("IM", "CFFEX", "financial"),
    "上证50股指": ("IH", "CFFEX", "financial"),
    "五年国债": ("TF", "CFFEX", "financial"),
    "十年国债": ("T", "CFFEX", "financial"),
    "三十年国债": ("TL", "CFFEX", "financial"),
    "豆一": ("a", "DCE", "agriculture"),
    "豆二": ("b", "DCE", "agriculture"),
    "豆粕": ("m", "DCE", "agriculture"),
    "豆油": ("y", "DCE", "agriculture"),
    "棕榈油": ("p", "DCE", "agriculture"),
    "玉米": ("c", "DCE", "agriculture"),
    "淀粉": ("cs", "DCE", "agriculture"),
    "鸡蛋": ("jd", "DCE", "agriculture"),
    "生猪": ("lh", "DCE", "agriculture"),
    "白糖": ("SR", "CZCE", "agriculture"),
    "郑棉": ("CF", "CZCE", "agriculture"),
    "菜油": ("OI", "CZCE", "agriculture"),
    "菜粕": ("RM", "CZCE", "agriculture"),
    "苹果": ("AP", "CZCE", "agriculture"),
    "红枣": ("CJ", "CZCE", "agriculture"),
    "花生": ("PK", "CZCE", "agriculture"),
}

EXCHANGES = {
    "SHFE": "上海期货交易所",
    "DCE": "大连商品交易所",
    "CZCE": "郑州商品交易所",
    "INE": "上海国际能源交易中心",
    "CFFEX": "中国金融期货交易所",
    "GFEX": "广州期货交易所",
    "UNKNOWN": "未知交易所",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ImportSummary:
    imported_files: int = 0
    imported_rows: int = 0
    failed_files: int = 0


class TraderFutureCsvImporter:
    def __init__(self, session: Session, raw_root: Path, parquet_root: Path) -> None:
        self.session = session
        self.raw_root = raw_root
        self.parquet_root = parquet_root

    def import_files(self, instrument_names: list[str] | None = None, periods: list[str] | None = None) -> ImportSummary:
        self._ensure_data_source()
        summary = ImportSummary()
        selected_periods = periods or list(PERIOD_DIRS)
        for period in selected_periods:
            for csv_path in self._iter_csv_files(period, instrument_names):
                try:
                    rows = self._import_file(csv_path, period)
                    summary.imported_files += 1
                    summary.imported_rows += rows
                except Exception as exc:
                    summary.failed_files += 1
                    self._record_failed_task(csv_path, period, str(exc))
        return summary

    def _iter_csv_files(self, period: str, instrument_names: list[str] | None) -> list[Path]:
        directory = self.raw_root / PERIOD_DIRS[period]
        if not directory.exists():
            return []
        files = sorted(directory.glob("*.csv"))
        if instrument_names:
            allowed = set(instrument_names)
            files = [path for path in files if self._instrument_name_from_path(path) in allowed]
        return files

    def _import_file(self, csv_path: Path, period: str) -> int:
        instrument_name = self._instrument_name_from_path(csv_path)
        symbol, exchange_code, sector = self._instrument_meta(instrument_name)
        contract_code = f"{symbol}.MAIN"
        started_at = utc_now()

        task = DataDownloadTask(
            task_no=f"dt-{uuid4().hex[:16]}",
            provider=PROVIDER,
            data_type=DATA_TYPE,
            instrument_symbol=symbol,
            contract_code=contract_code,
            period=period,
            start_time=started_at,
            end_time=started_at,
            status="running",
            progress=0,
            started_at=started_at,
        )
        self.session.add(task)
        self.session.flush()

        df = self._read_csv(csv_path, instrument_name, symbol, exchange_code, period, contract_code)
        if df.empty:
            raise ValueError(f"empty csv: {csv_path}")

        self._ensure_exchange(exchange_code)
        self._ensure_instrument(symbol, instrument_name, exchange_code, sector)
        self._ensure_contract(contract_code, symbol, exchange_code, instrument_name)

        start_time = df["datetime"].min().to_pydatetime()
        end_time = df["datetime"].max().to_pydatetime()
        output_path = self._write_parquet(df, exchange_code, symbol, period)
        checksum = self._checksum(output_path)
        quality = self._quality(df)
        status = "passed" if quality["abnormal_price_count"] == 0 and quality["abnormal_volume_count"] == 0 and quality["duplicated_bars"] == 0 else "warning"

        data_version = f"{PROVIDER}_{period}_{start_time:%Y%m%d}_{end_time:%Y%m%d}"
        market_file = self.session.scalar(
            select(MarketDataFile).where(
                MarketDataFile.provider == PROVIDER,
                MarketDataFile.data_type == DATA_TYPE,
                MarketDataFile.contract_code == contract_code,
                MarketDataFile.period == period,
                MarketDataFile.start_time == start_time,
                MarketDataFile.end_time == end_time,
                MarketDataFile.data_version == data_version,
            )
        )
        if market_file is None:
            market_file = MarketDataFile(
                provider=PROVIDER,
                data_type=DATA_TYPE,
                instrument_symbol=symbol,
                contract_code=contract_code,
                period=period,
                start_time=start_time,
                end_time=end_time,
                data_version=data_version,
            )
            self.session.add(market_file)

        market_file.task_id = task.id
        market_file.file_path = str(output_path)
        market_file.row_count = len(df)
        market_file.file_size_bytes = output_path.stat().st_size
        market_file.checksum = checksum
        market_file.quality_status = status
        self.session.flush()

        self.session.execute(
            delete(DataQualityReport).where(
                DataQualityReport.provider == PROVIDER,
                DataQualityReport.data_type == DATA_TYPE,
                DataQualityReport.contract_code == contract_code,
                DataQualityReport.period == period,
                DataQualityReport.start_time == start_time,
                DataQualityReport.end_time == end_time,
            )
        )
        report = DataQualityReport(
            file_id=market_file.id,
            task_id=task.id,
            provider=PROVIDER,
            data_type=DATA_TYPE,
            instrument_symbol=symbol,
            contract_code=contract_code,
            period=period,
            start_time=start_time,
            end_time=end_time,
            status=status,
            missing_bars=0,
            duplicated_bars=quality["duplicated_bars"],
            abnormal_price_count=quality["abnormal_price_count"],
            abnormal_volume_count=quality["abnormal_volume_count"],
            details={
                "source_file": str(csv_path),
                "instrument_name": instrument_name,
                "rows": len(df),
                "columns": list(df.columns),
            },
        )
        self.session.add(report)

        task.start_time = start_time
        task.end_time = end_time
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "file_path": str(output_path),
            "row_count": len(df),
            "quality_status": status,
        }
        return len(df)

    def _read_csv(self, csv_path: Path, instrument_name: str, symbol: str, exchange_code: str, period: str, contract_code: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        required = {"Date", "Time", "Open", "Close", "High", "Low", "Volume", "Amount"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"missing columns {sorted(missing)} in {csv_path}")

        normalized = pd.DataFrame(
            {
                "datetime": pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str)),
                "open": pd.to_numeric(df["Open"], errors="coerce"),
                "high": pd.to_numeric(df["High"], errors="coerce"),
                "low": pd.to_numeric(df["Low"], errors="coerce"),
                "close": pd.to_numeric(df["Close"], errors="coerce"),
                "volume": pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64"),
                "amount": pd.to_numeric(df["Amount"], errors="coerce"),
                "open_interest": None,
            }
        )
        normalized["provider"] = PROVIDER
        normalized["data_type"] = DATA_TYPE
        normalized["instrument_name"] = instrument_name
        normalized["instrument_symbol"] = symbol
        normalized["contract_code"] = contract_code
        normalized["exchange"] = exchange_code
        normalized["period"] = period
        normalized = normalized.sort_values("datetime").dropna(subset=["datetime", "open", "high", "low", "close"])
        return normalized

    def _write_parquet(self, df: pd.DataFrame, exchange_code: str, symbol: str, period: str) -> Path:
        first_year = int(df["datetime"].dt.year.min())
        last_year = int(df["datetime"].dt.year.max())
        directory = (
            self.parquet_root
            / "market"
            / f"provider={PROVIDER}"
            / f"data_type={DATA_TYPE}"
            / f"period={period}"
            / f"exchange={exchange_code}"
            / f"instrument={symbol}"
            / f"year={first_year}-{last_year}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        output_path = directory / "part-000.parquet"
        df.to_parquet(output_path, index=False)
        return output_path

    def _ensure_data_source(self) -> None:
        source_specs = [
            {
                "name": "交易练习者主力连续",
                "provider": PROVIDER,
                "status": "enabled",
                "priority": 10,
                "config": {"storage": "parquet", "data_type": DATA_TYPE},
                "remark": "本地 raw/trader_Future_data 主力连续研究数据",
            },
            {
                "name": "天勤 TqSdk",
                "provider": "tqsdk",
                "status": "planned",
                "priority": 20,
                "config": {"credential_env": ["TQSDK_USERNAME", "TQSDK_PASSWORD"]},
                "remark": "核心目标数据源，V0 先保留配置",
            },
            {
                "name": "Tushare Pro",
                "provider": "tushare",
                "status": "enabled" if os.getenv("TUSHARE_TOKEN") else "disabled",
                "priority": 30,
                "config": {"credential_env": "TUSHARE_TOKEN"},
                "remark": "合约、交易日历等元数据补充源",
            },
            {
                "name": "RQData",
                "provider": "rqdata",
                "status": "planned",
                "priority": 40,
                "config": {"credential_source": "local_env_or_license"},
                "remark": "补充数据源，V0 不阻塞主链路",
            },
        ]
        for spec in source_specs:
            source = self.session.scalar(select(DataSource).where(DataSource.provider == spec["provider"]))
            if source is None:
                self.session.add(DataSource(**spec))
                continue
            source.name = str(spec["name"])
            source.status = str(spec["status"])
            source.priority = int(spec["priority"])
            source.config = dict(spec["config"])
            source.remark = str(spec["remark"])

    def _ensure_exchange(self, exchange_code: str) -> None:
        if self.session.scalar(select(Exchange).where(Exchange.code == exchange_code)):
            return
        self.session.add(Exchange(code=exchange_code, name=EXCHANGES.get(exchange_code, EXCHANGES["UNKNOWN"]), country="CN"))

    def _ensure_instrument(self, symbol: str, name: str, exchange_code: str, sector: str) -> None:
        if self.session.scalar(select(Instrument).where(Instrument.symbol == symbol)):
            return
        self.session.add(Instrument(symbol=symbol, name=name, exchange_code=exchange_code, sector=sector, category="futures"))

    def _ensure_contract(self, contract_code: str, symbol: str, exchange_code: str, instrument_name: str) -> None:
        if self.session.scalar(select(Contract).where(Contract.contract_code == contract_code)):
            return
        self.session.add(
            Contract(
                contract_code=contract_code,
                instrument_symbol=symbol,
                exchange_code=exchange_code,
                name=f"{instrument_name}主力连续",
                status="research",
                raw_symbol=f"{instrument_name}-主连",
                provider=PROVIDER,
            )
        )

    def _record_failed_task(self, csv_path: Path, period: str, error: str) -> None:
        now = utc_now()
        task = DataDownloadTask(
            task_no=f"dt-{uuid4().hex[:16]}",
            provider=PROVIDER,
            data_type=DATA_TYPE,
            period=period,
            start_time=now,
            end_time=now,
            status="failed",
            progress=0,
            error_message=error,
            result={"source_file": str(csv_path)},
            started_at=now,
            finished_at=now,
        )
        self.session.add(task)

    @staticmethod
    def _instrument_name_from_path(csv_path: Path) -> str:
        return csv_path.name.split("-主连-", maxsplit=1)[0]

    @staticmethod
    def _instrument_meta(instrument_name: str) -> tuple[str, str, str]:
        if instrument_name in INSTRUMENT_SYMBOLS:
            return INSTRUMENT_SYMBOLS[instrument_name]
        fallback = f"CN{sha256(instrument_name.encode('utf-8')).hexdigest()[:8].upper()}"
        return fallback, "UNKNOWN", "unknown"

    @staticmethod
    def _quality(df: pd.DataFrame) -> dict[str, int]:
        duplicated = int(df["datetime"].duplicated().sum())
        abnormal_price = int(
            (
                (df["high"] < df[["open", "close", "low"]].max(axis=1))
                | (df["low"] > df[["open", "close", "high"]].min(axis=1))
            ).sum()
        )
        abnormal_volume = int((df["volume"] < 0).sum())
        return {
            "duplicated_bars": duplicated,
            "abnormal_price_count": abnormal_price,
            "abnormal_volume_count": abnormal_volume,
        }

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
