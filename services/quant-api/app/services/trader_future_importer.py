from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path
from uuid import uuid4

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
CHECK_RULE_VERSION = "canonical_bars_v0"

PERIOD_DIRS = {
    "5m": "5分钟主力连续",
    "15m": "15 分钟主力连续",
    "30m": "30 分钟主力连续",
    "60m": "60 分钟主力连续",
    "1d": "日线主力连续",
}

PERIOD_DELTAS = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "60m": timedelta(minutes=60),
    "1d": timedelta(days=1),
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


@dataclass
class WrittenParquetFile:
    path: Path
    frame: pd.DataFrame
    start_time: datetime
    end_time: datetime
    data_version: str
    quality: dict[str, object]
    status: str
    checksum: str


class TraderFutureCsvImporter:
    def __init__(self, session: Session, raw_root: Path, parquet_root: Path) -> None:
        self.session = session
        self.raw_root = raw_root
        self.parquet_root = parquet_root

    def import_files(
        self,
        instrument_names: list[str] | None = None,
        periods: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ImportSummary:
        self._ensure_data_source()
        summary = ImportSummary()
        selected_periods = periods or list(PERIOD_DIRS)
        for period in selected_periods:
            for csv_path in self._iter_csv_files(period, instrument_names):
                try:
                    rows = self._import_file(csv_path, period, start=start, end=end)
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

    def _import_file(self, csv_path: Path, period: str, start: datetime | None = None, end: datetime | None = None) -> int:
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
        if start is not None:
            df = df[df["datetime"] >= pd.Timestamp(start.replace(tzinfo=None))]
        if end is not None:
            df = df[df["datetime"] <= pd.Timestamp(end.replace(tzinfo=None))]
        if df.empty:
            raise ValueError(f"empty csv: {csv_path}")

        self._ensure_exchange(exchange_code)
        self._ensure_instrument(symbol, instrument_name, exchange_code, sector)
        self._ensure_contract(contract_code, symbol, exchange_code, instrument_name)

        written_files = self._write_parquet_files(df, exchange_code, symbol, contract_code, period)
        for written_file in written_files:
            self._upsert_file_and_quality_report(
                task=task,
                written_file=written_file,
                symbol=symbol,
                contract_code=contract_code,
                period=period,
                csv_path=csv_path,
                instrument_name=instrument_name,
            )

        task.start_time = min(file.start_time for file in written_files)
        task.end_time = max(file.end_time for file in written_files)
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "file_count": len(written_files),
            "file_paths": [str(file.path) for file in written_files],
            "row_count": len(df),
            "quality_status": self._aggregate_status(file.status for file in written_files),
        }
        return len(df)

    def _read_csv(self, csv_path: Path, instrument_name: str, symbol: str, exchange_code: str, period: str, contract_code: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        required = {"Date", "Time", "Open", "Close", "High", "Low", "Volume", "Amount"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"missing columns {sorted(missing)} in {csv_path}")

        open_interest = self._optional_numeric_column(df, ["OpenInterest", "Open Interest", "Open_Interest", "open_interest", "持仓量"])
        normalized = pd.DataFrame(
            {
                "datetime": pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str)),
                "open": pd.to_numeric(df["Open"], errors="coerce").astype("float64"),
                "high": pd.to_numeric(df["High"], errors="coerce").astype("float64"),
                "low": pd.to_numeric(df["Low"], errors="coerce").astype("float64"),
                "close": pd.to_numeric(df["Close"], errors="coerce").astype("float64"),
                "volume": pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64"),
                "turnover": pd.to_numeric(df["Amount"], errors="coerce").astype("float64"),
                "open_interest": open_interest,
            }
        )
        normalized["symbol"] = symbol
        normalized["contract"] = contract_code
        normalized["exchange"] = exchange_code
        normalized["trading_day"] = normalized["datetime"].map(self._trading_day)
        normalized["period"] = period
        normalized["provider"] = PROVIDER
        normalized = normalized.sort_values("datetime").dropna(subset=["datetime", "open", "high", "low", "close"])
        normalized = normalized[
            [
                "symbol",
                "contract",
                "exchange",
                "datetime",
                "trading_day",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "open_interest",
                "period",
                "provider",
                "turnover",
            ]
        ]
        return normalized

    def _write_parquet_files(self, df: pd.DataFrame, exchange_code: str, symbol: str, contract_code: str, period: str) -> list[WrittenParquetFile]:
        written_files: list[WrittenParquetFile] = []
        created_at = utc_now()
        for year, group in df.groupby(df["datetime"].dt.year, sort=True):
            output = group.copy()
            start_time = output["datetime"].min().to_pydatetime()
            end_time = output["datetime"].max().to_pydatetime()
            data_version = f"{PROVIDER}_{period}_{symbol}_{int(year)}_canonical_v1"
            output["data_version"] = data_version
            output["created_at"] = created_at
            directory = (
                self.parquet_root
                / "canonical"
                / "bars"
                / f"provider={PROVIDER}"
                / f"period={period}"
                / f"exchange={exchange_code}"
                / f"symbol={symbol}"
                / f"contract={contract_code}"
                / f"year={int(year)}"
            )
            directory.mkdir(parents=True, exist_ok=True)
            output_path = directory / "part-000.parquet"
            output.to_parquet(output_path, index=False)
            quality = self._quality(output, period)
            status = self._quality_status(quality)
            written_files.append(
                WrittenParquetFile(
                    path=output_path,
                    frame=output,
                    start_time=start_time,
                    end_time=end_time,
                    data_version=data_version,
                    quality=quality,
                    status=status,
                    checksum=self._checksum(output_path),
                )
            )
        return written_files

    def _upsert_file_and_quality_report(
        self,
        task: DataDownloadTask,
        written_file: WrittenParquetFile,
        symbol: str,
        contract_code: str,
        period: str,
        csv_path: Path,
        instrument_name: str,
    ) -> None:
        market_file = self.session.scalar(
            select(MarketDataFile).where(
                MarketDataFile.provider == PROVIDER,
                MarketDataFile.data_type == DATA_TYPE,
                MarketDataFile.contract_code == contract_code,
                MarketDataFile.period == period,
                MarketDataFile.start_time == written_file.start_time,
                MarketDataFile.end_time == written_file.end_time,
                MarketDataFile.data_version == written_file.data_version,
            )
        )
        if market_file is None:
            market_file = MarketDataFile(
                provider=PROVIDER,
                data_type=DATA_TYPE,
                instrument_symbol=symbol,
                contract_code=contract_code,
                period=period,
                start_time=written_file.start_time,
                end_time=written_file.end_time,
                data_version=written_file.data_version,
            )
            self.session.add(market_file)

        market_file.task_id = task.id
        market_file.file_path = str(written_file.path)
        market_file.row_count = len(written_file.frame)
        market_file.file_size_bytes = written_file.path.stat().st_size
        market_file.checksum = written_file.checksum
        market_file.quality_status = written_file.status
        self.session.flush()

        self.session.execute(
            delete(DataQualityReport).where(
                DataQualityReport.provider == PROVIDER,
                DataQualityReport.data_type == DATA_TYPE,
                DataQualityReport.contract_code == contract_code,
                DataQualityReport.period == period,
                DataQualityReport.start_time == written_file.start_time,
                DataQualityReport.end_time == written_file.end_time,
            )
        )
        quality = written_file.quality
        self.session.add(
            DataQualityReport(
                file_id=market_file.id,
                task_id=task.id,
                provider=PROVIDER,
                data_type=DATA_TYPE,
                instrument_symbol=symbol,
                contract_code=contract_code,
                period=period,
                start_time=written_file.start_time,
                end_time=written_file.end_time,
                status=written_file.status,
                missing_bars=int(quality["missing_bars"]),
                duplicated_bars=int(quality["duplicated_bars"]),
                abnormal_price_count=int(quality["abnormal_price_count"]),
                abnormal_volume_count=int(quality["abnormal_volume_count"]),
                details={
                    "source_file": str(csv_path),
                    "instrument_name": instrument_name,
                    "rows": len(written_file.frame),
                    "columns": list(written_file.frame.columns),
                    "check_rule_version": CHECK_RULE_VERSION,
                    "gap_count": quality["gap_count"],
                    "gap_samples": quality["gap_samples"],
                    "duplicate_samples": quality["duplicate_samples"],
                    "abnormal_price_samples": quality["abnormal_price_samples"],
                    "abnormal_volume_samples": quality["abnormal_volume_samples"],
                    "abnormal_open_interest_count": quality["abnormal_open_interest_count"],
                    "abnormal_open_interest_samples": quality["abnormal_open_interest_samples"],
                },
            )
        )

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
    def _quality(df: pd.DataFrame, period: str) -> dict[str, object]:
        sorted_df = df.sort_values("datetime")
        duplicated_mask = sorted_df["datetime"].duplicated()
        abnormal_price_mask = (sorted_df["high"] < sorted_df[["open", "close", "low"]].max(axis=1)) | (
            sorted_df["low"] > sorted_df[["open", "close", "high"]].min(axis=1)
        )
        abnormal_volume_mask = sorted_df["volume"] < 0
        abnormal_open_interest_mask = sorted_df["open_interest"].notna() & (sorted_df["open_interest"] < 0)
        missing_bars, gap_samples = TraderFutureCsvImporter._missing_bars(sorted_df, period)
        return {
            "missing_bars": missing_bars,
            "gap_count": len(gap_samples),
            "gap_samples": gap_samples,
            "duplicated_bars": int(duplicated_mask.sum()),
            "duplicate_samples": TraderFutureCsvImporter._datetime_samples(sorted_df.loc[duplicated_mask, "datetime"]),
            "abnormal_price_count": int(abnormal_price_mask.sum()),
            "abnormal_price_samples": TraderFutureCsvImporter._datetime_samples(sorted_df.loc[abnormal_price_mask, "datetime"]),
            "abnormal_volume_count": int(abnormal_volume_mask.sum()),
            "abnormal_volume_samples": TraderFutureCsvImporter._datetime_samples(sorted_df.loc[abnormal_volume_mask, "datetime"]),
            "abnormal_open_interest_count": int(abnormal_open_interest_mask.sum()),
            "abnormal_open_interest_samples": TraderFutureCsvImporter._datetime_samples(sorted_df.loc[abnormal_open_interest_mask, "datetime"]),
        }

    @staticmethod
    def _quality_status(quality: dict[str, object]) -> str:
        failed_count = (
            int(quality["abnormal_price_count"])
            + int(quality["abnormal_volume_count"])
            + int(quality["abnormal_open_interest_count"])
        )
        if failed_count > 0:
            return "failed"
        warning_count = int(quality["duplicated_bars"]) + int(quality["missing_bars"])
        return "warning" if warning_count > 0 else "passed"

    @staticmethod
    def _aggregate_status(statuses: object) -> str:
        status_set = set(statuses)
        if "failed" in status_set:
            return "failed"
        if "warning" in status_set:
            return "warning"
        return "passed"

    @staticmethod
    def _missing_bars(df: pd.DataFrame, period: str) -> tuple[int, list[dict[str, object]]]:
        expected_delta = PERIOD_DELTAS[period]
        unique_times = list(df["datetime"].drop_duplicates().sort_values())
        missing = 0
        samples: list[dict[str, object]] = []
        for previous, current in zip(unique_times, unique_times[1:], strict=False):
            diff = current.to_pydatetime() - previous.to_pydatetime()
            if diff <= expected_delta:
                continue
            missing_for_gap = int(diff / expected_delta) - 1
            missing += missing_for_gap
            if len(samples) < 10:
                samples.append(
                    {
                        "from": previous.isoformat(),
                        "to": current.isoformat(),
                        "missing_bars": missing_for_gap,
                    }
                )
        return missing, samples

    @staticmethod
    def _datetime_samples(values: pd.Series) -> list[str]:
        return [value.isoformat() for value in values.head(10)]

    @staticmethod
    def _optional_numeric_column(df: pd.DataFrame, names: list[str]) -> pd.Series:
        for name in names:
            if name in df.columns:
                return pd.to_numeric(df[name], errors="coerce").astype("float64")
        return pd.Series([pd.NA] * len(df), dtype="Float64")

    @staticmethod
    def _trading_day(value: pd.Timestamp):
        if value.time().hour >= 21:
            return (value + pd.Timedelta(days=1)).date()
        return value.date()

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
