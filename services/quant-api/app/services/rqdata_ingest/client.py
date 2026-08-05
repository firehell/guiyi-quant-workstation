from datetime import date
from importlib.metadata import version
import os
from typing import Any

import pandas as pd

from app.core.env import load_project_env
from app.data_core.product_retirement import ProductRetirementError, is_retired_identity

MIN_DOMINANT_PRICE_START = date(2010, 1, 4)


def init_rqdatac(rqdatac: Any, *, load_env_file: bool = True) -> None:
    if load_env_file:
        load_project_env()

    uri = os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF")
    if uri:
        rqdatac.init(uri=uri)
        return

    license_key = os.getenv("RQDATA_LICENSE_KEY")
    if license_key:
        rqdatac.init("license", license_key)
        return

    username = os.getenv("RQDATA_USERNAME")
    password = os.getenv("RQDATA_PASSWORD")
    if username and password:
        addr = os.getenv("RQDATA_ADDR", "rqdatad-pro.ricequant.com:16011")
        rqdatac.init(username, password, addr)
        return

    raise RuntimeError(
        "RQData credentials not configured. Set RQDATA_LICENSE_KEY, "
        "RQDATAC2_CONF, or RQDATA_USERNAME/RQDATA_PASSWORD in .env"
    )


class RqDataClient:
    def __init__(self, *, load_env_file: bool = True) -> None:
        try:
            import rqdatac  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("rqdatac is not installed; install/configure RQData before running real downloads") from exc
        self.rqdatac = rqdatac
        init_rqdatac(rqdatac, load_env_file=load_env_file)

    @staticmethod
    def underlying_symbol(product: str) -> str:
        """RQData futures APIs expect uppercase underlying symbols (RB, HC, TA)."""
        if is_retired_identity(product=product):
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_PRODUCT_RETIRED:{str(product).strip().lower()}")
        return str(product or "").upper()

    @staticmethod
    def order_book_id(contract: str) -> str:
        if is_retired_identity(contract=contract):
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_PRODUCT_RETIRED:{str(contract).strip().upper()}")
        return str(contract or "").upper()

    @staticmethod
    def rqdatac_version() -> str:
        return version("rqdatac")

    def all_future_instruments(self) -> pd.DataFrame:
        frame = self._frame(self.rqdatac.all_instruments(type="Future"))
        if frame.empty:
            return frame
        return frame[
            ~frame.apply(
                lambda row: is_retired_identity(
                    product=row.get("underlying_symbol", row.get("product")),
                    contract=row.get("order_book_id", row.get("contract")),
                ),
                axis=1,
            )
        ].reset_index(drop=True)

    def trading_dates(self, start_date: date, end_date: date) -> list[date]:
        dates = self.rqdatac.get_trading_dates(start_date=start_date, end_date=end_date)
        return [pd.to_datetime(item).date() for item in dates]

    def trading_periods(self, products: list[str]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        futures_api = getattr(self.rqdatac, "futures", None)
        for product in products:
            rq_product = self.underlying_symbol(product)
            periods = None
            if futures_api is not None and hasattr(futures_api, "get_trading_hours"):
                try:
                    periods = futures_api.get_trading_hours(rq_product)
                except Exception:
                    periods = None
            if periods is None:
                try:
                    periods = self.rqdatac.get_trading_periods(rq_product)
                except AttributeError:
                    try:
                        periods = self.rqdatac.get_trading_hours(rq_product)
                    except Exception:
                        periods = None
                except Exception:
                    periods = None
            if isinstance(periods, pd.DataFrame):
                frame = periods.copy()
                frame["product"] = product
                rows.extend(frame.to_dict("records"))
            elif isinstance(periods, list):
                rows.extend({"product": product, **item} if isinstance(item, dict) else {"product": product, "raw": item} for item in periods)
            elif periods is not None:
                rows.append({"product": product, "raw": periods})
        return pd.DataFrame(rows)

    def contract_trading_periods(
        self,
        contracts: tuple[str, ...],
        *,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        normalized = [self.order_book_id(contract) for contract in contracts]
        if not normalized or start_date > end_date:
            raise ValueError("rqdatac_contract_trading_periods_scope_invalid")
        frame = self._frame(
            self.rqdatac.get_trading_periods(
                normalized,
                start_date=start_date,
                end_date=end_date,
                frequency="1m",
                market="cn",
            )
        )
        if not isinstance(frame.index, pd.RangeIndex):
            frame = frame.reset_index()
        required = {"order_book_id", "date", "trading_hours"}
        if not required.issubset(frame.columns):
            missing = sorted(required.difference(frame.columns))
            raise RuntimeError(
                "rqdatac_contract_trading_periods_invalid_response:"
                + ",".join(missing)
            )
        result = frame.loc[:, ["order_book_id", "date", "trading_hours"]].copy()
        result["order_book_id"] = result["order_book_id"].astype(str).str.upper()
        result["date"] = pd.to_datetime(result["date"]).dt.date
        return result.reset_index(drop=True)

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        result = self.rqdatac.futures.get_dominant(rq_product, start_date=start_date, end_date=end_date, rank=rank)
        return self._frame(result)

    def continuous_contracts(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        if hasattr(self.rqdatac.futures, "get_continuous_contracts"):
            return self._frame(self.rqdatac.futures.get_continuous_contracts(rq_product, start_date=start_date, end_date=end_date))
        return pd.DataFrame()

    def listed_contracts(self, product: str, trade_date: date) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        futures_api = self.rqdatac.futures
        if not hasattr(futures_api, "get_contracts"):
            return pd.DataFrame()
        for kwargs in (
            {"date": trade_date},
            {"trading_date": trade_date},
            {"trade_date": trade_date},
        ):
            try:
                result = futures_api.get_contracts(rq_product, **kwargs)
                break
            except TypeError:
                continue
        else:
            result = futures_api.get_contracts(rq_product, trade_date)
        frame = self._frame(result)
        if frame.empty and isinstance(result, list | tuple):
            frame = pd.DataFrame({"contract": list(result)})
        elif not frame.empty and "contract" not in frame.columns:
            if 0 in frame.columns:
                frame = frame.rename(columns={0: "contract"})
            elif "0" in frame.columns:
                frame = frame.rename(columns={"0": "contract"})
        if not frame.empty and "date" not in frame.columns:
            frame["date"] = trade_date
        return frame

    def continuous_contract_by_type(self, product: str, start_date: date, end_date: date, continuous_type: str) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        futures_api = self.rqdatac.futures
        if not hasattr(futures_api, "get_continuous_contracts"):
            return pd.DataFrame()
        for extra in (
            {"type": continuous_type},
            {"continuous_type": continuous_type},
            {"contract_type": continuous_type},
        ):
            try:
                return self._frame(futures_api.get_continuous_contracts(rq_product, start_date=start_date, end_date=end_date, **extra))
            except TypeError:
                continue
        frame = self._frame(futures_api.get_continuous_contracts(rq_product, start_date=start_date, end_date=end_date))
        if continuous_type in frame.columns:
            return frame[["index", continuous_type]] if "index" in frame.columns else frame[[continuous_type]]
        return frame

    def ex_factor(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        return self._frame(self.rqdatac.futures.get_ex_factor(rq_product, start_date=start_date, end_date=end_date))

    def trading_parameters(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        rq_contract = self.order_book_id(contract)
        return self._frame(self.rqdatac.futures.get_trading_parameters(rq_contract, start_date=start_date, end_date=end_date))

    def price_tick(self, contract: str) -> float | None:
        if not hasattr(self.rqdatac, "get_tick_size"):
            return None
        result = self.rqdatac.get_tick_size(self.order_book_id(contract))
        if result is None:
            return None
        if isinstance(result, pd.Series):
            values = result.dropna()
            if values.empty:
                return None
            return float(values.iloc[0])
        if isinstance(result, pd.DataFrame):
            values = result.stack().dropna()
            if values.empty:
                return None
            return float(values.iloc[0])
        return float(result)

    def contract_multiplier(self, contract: str) -> int | None:
        if hasattr(self.rqdatac.futures, "get_contract_multiplier"):
            value = self.rqdatac.futures.get_contract_multiplier(self.order_book_id(contract))
            if value is not None:
                return int(value)
        frame = self.all_future_instruments()
        if frame.empty or "order_book_id" not in frame.columns:
            return None
        matched = frame[frame["order_book_id"].astype(str).str.upper() == self.order_book_id(contract)]
        if matched.empty:
            return None
        value = matched.iloc[0].get("contract_multiplier")
        if pd.isna(value):
            return None
        return int(value)

    def exchange_daily(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        rq_contract = self.order_book_id(contract)
        if hasattr(self.rqdatac.futures, "get_exchange_daily"):
            return self._frame(self.rqdatac.futures.get_exchange_daily(rq_contract, start_date=start_date, end_date=end_date))
        return self._frame(self.rqdatac.get_price(rq_contract, start_date=start_date, end_date=end_date, frequency="1d"))

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        rq_contract = self.order_book_id(contract)
        return self._frame(self.rqdatac.get_price(rq_contract, start_date=start_date, end_date=end_date, frequency=frequency))

    def market_data_readiness(
        self,
        *,
        expected_date: date,
        categories: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        if not hasattr(self.rqdatac, "is_data_ready"):
            raise RuntimeError("rqdatac_is_data_ready_unavailable")
        requested = list(dict.fromkeys(str(category) for category in categories))
        result = self.rqdatac.is_data_ready(
            categories=requested,
            expected_date=expected_date,
            market="cn",
        )
        frame = self._frame(result)
        required_columns = {"market", "category", "latest_date", "update_time", "expected_date", "ready"}
        if not required_columns.issubset(frame.columns):
            missing = sorted(required_columns.difference(frame.columns))
            raise RuntimeError(f"rqdatac_is_data_ready_invalid_response:{','.join(missing)}")
        rows: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            category = str(row["category"])
            if category not in requested or str(row["market"]).lower() != "cn":
                continue
            rows[category] = {
                "market": "cn",
                "category": category,
                "latest_date": _iso_date(row["latest_date"]),
                "update_time": _iso_datetime(row["update_time"]),
                "expected_date": _iso_date(row["expected_date"]),
                "ready": bool(row["ready"]),
            }
        missing_categories = sorted(set(requested).difference(rows))
        if missing_categories:
            raise RuntimeError(f"rqdatac_is_data_ready_missing_categories:{','.join(missing_categories)}")
        return rows

    def warehouse_stocks(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        result = self.rqdatac.futures.get_warehouse_stocks(rq_product, start_date=start_date, end_date=end_date)
        if result is None:
            return pd.DataFrame()
        frame = self._frame(result)
        if not frame.empty and "on_warrant" in frame.columns and "quantity" not in frame.columns:
            frame["quantity"] = frame["on_warrant"]
        return frame

    def roll_yield(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        futures_api = self.rqdatac.futures
        if not hasattr(futures_api, "get_roll_yield"):
            return pd.DataFrame()
        rq_product = self.underlying_symbol(product)
        try:
            result = futures_api.get_roll_yield(rq_product, start_date=start_date, end_date=end_date)
        except Exception:
            return pd.DataFrame()
        if result is None:
            return pd.DataFrame()
        return self._frame(result)

    def basis(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        rq_contract = self.order_book_id(contract)
        try:
            result = self.rqdatac.futures.get_basis(rq_contract, start_date=start_date, end_date=end_date)
        except Exception:
            return pd.DataFrame()
        if result is None:
            return pd.DataFrame()
        return self._frame(result)

    def member_rank(self, product: str, start_date: date, end_date: date, rank_by: str = "volume") -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        result = self.rqdatac.futures.get_member_rank(
            rq_product,
            start_date=start_date,
            end_date=end_date,
            rank_by=rank_by,
        )
        if result is None:
            return pd.DataFrame()
        return self._frame(result)

    @staticmethod
    def clamp_dominant_price_start(start_date: date) -> date:
        return max(start_date, MIN_DOMINANT_PRICE_START)

    def main_price(self, product: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        rq_product = self.underlying_symbol(product)
        effective_start = self.clamp_dominant_price_start(start_date)
        if hasattr(self.rqdatac.futures, "get_dominant_price"):
            result = self.rqdatac.futures.get_dominant_price(
                rq_product,
                start_date=effective_start,
                end_date=end_date,
                frequency=frequency,
                adjust_type="none",
                rule=0,
                rank=1,
            )
            if result is None:
                return pd.DataFrame()
            return self._frame(result)
        return self._frame(self.rqdatac.get_price(f"{rq_product}99", start_date=effective_start, end_date=end_date, frequency=frequency))

    def dominant_daily_price(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self.main_price(product, start_date, end_date, "1d")

    @staticmethod
    def _frame(value: Any) -> pd.DataFrame:
        if isinstance(value, pd.DataFrame):
            return value.reset_index(drop=False)
        if isinstance(value, pd.Series):
            return value.reset_index()
        return pd.DataFrame(value)


def _iso_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise RuntimeError("rqdatac_is_data_ready_invalid_date")
    return parsed.date().isoformat()


def _iso_datetime(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise RuntimeError("rqdatac_is_data_ready_invalid_update_time")
    return parsed.to_pydatetime().isoformat()
