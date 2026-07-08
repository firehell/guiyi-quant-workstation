from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import (
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesExFactor,
    FuturesMemberRank,
    FuturesRollYield,
    FuturesTradingParameter,
    FuturesWarehouseStock,
    Instrument,
    MainContractMap,
)
from app.schemas.futures_research import (
    ChartSeriesSpec,
    ChartSpec,
    ColumnSpec,
    CoverageSummary,
    FuturesResearchPanelCatalogResponse,
    FuturesResearchPanelMeta,
    FuturesResearchPanelResponse,
)

PROVIDER = "rqdata"
MAX_ROWS = 5000
MAX_SPAN_DAYS = 1095
DEFAULT_SPAN_DAYS = 90
MEMBER_RANK_TOP_N = 20
VALID_MEMBER_RANK_BY = frozenset({"volume", "long", "short"})
MEMBER_RANK_BY_LABELS = {"volume": "成交量", "long": "持买仓", "short": "持卖仓"}

INDEX_FUTURES = frozenset({"if", "ih", "ic", "im"})

PANEL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "dominant": {
        "label": "主力映射",
        "description": "每日 rank=1 主力合约映射",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_main_mapping_sync.py",
    },
    "ex-factor": {
        "label": "复权因子",
        "description": "主力连续合约复权因子与切换日",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_ex_factor_sync.py",
    },
    "trading-parameters": {
        "label": "交易参数",
        "description": "保证金、手续费、tick、乘数等",
        "requires_contract": True,
        "sync_script": "scripts/rqdata_trading_params_sync.py",
    },
    "warehouse-stocks": {
        "label": "注册仓单",
        "description": "品种注册仓单数量",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_research_enhancers_sync.py",
    },
    "roll-yield": {
        "label": "展期收益",
        "description": "主力/次主力展期收益率",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_research_enhancers_sync.py",
    },
    "contract-universe": {
        "label": "可交易合约",
        "description": "每日可交易合约列表",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_contract_universe_sync.py",
    },
    "continuous-contracts": {
        "label": "近月连续",
        "description": "近月连续合约映射",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_continuous_contracts_sync.py",
    },
    "member-rank": {
        "label": "会员排名",
        "description": "品种维度会员成交量/持买仓/持卖仓排名",
        "requires_contract": False,
        "sync_script": "scripts/rqdata_member_rank_sync.py",
    },
}


class FuturesResearchReader:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_panels(self, *, symbol: str, contract: str | None = None) -> FuturesResearchPanelCatalogResponse:
        product = _normalize_symbol(symbol)
        instrument = self.session.scalar(select(Instrument).where(func.lower(Instrument.symbol) == product))
        is_index = product in INDEX_FUTURES or (instrument and instrument.category and "股指" in instrument.category)

        panels: list[FuturesResearchPanelMeta] = []
        for panel_id, definition in PANEL_DEFINITIONS.items():
            coverage = self._local_coverage(panel_id, product)
            enabled = True
            reason = None
            if definition.get("always_disabled"):
                enabled = False
                reason = definition.get("disabled_reason")
            elif definition.get("requires_contract") and not contract:
                enabled = False
                reason = "请先选择真实合约"
            elif panel_id in {"basis", "predicted-dividend"} and not is_index:
                enabled = False
                reason = "仅股指期货品种可用"

            panels.append(
                FuturesResearchPanelMeta(
                    panel_id=panel_id,
                    label=definition["label"],
                    description=definition["description"],
                    enabled=enabled,
                    reason=reason,
                    requires_contract=definition.get("requires_contract", False),
                    sync_script=definition.get("sync_script"),
                    local_coverage_start=coverage[0],
                    local_coverage_end=coverage[1],
                )
            )
        return FuturesResearchPanelCatalogResponse(symbol=product, contract=contract, panels=panels)

    def get_panel(
        self,
        panel_id: str,
        *,
        symbol: str,
        contract: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> FuturesResearchPanelResponse:
        if panel_id not in PANEL_DEFINITIONS:
            raise HTTPException(status_code=404, detail=f"unknown research panel: {panel_id}")
        definition = PANEL_DEFINITIONS[panel_id]
        if definition.get("always_disabled"):
            raise HTTPException(status_code=422, detail=definition.get("disabled_reason"))
        if definition.get("requires_contract") and not contract:
            raise HTTPException(status_code=422, detail="contract is required for this panel")

        product = _normalize_symbol(symbol)
        resolved_start, resolved_end = _resolve_date_range(start, end)
        handlers = {
            "dominant": self._dominant_panel,
            "ex-factor": self._ex_factor_panel,
            "trading-parameters": self._trading_parameters_panel,
            "warehouse-stocks": self._warehouse_stocks_panel,
            "roll-yield": self._roll_yield_panel,
            "contract-universe": self._contract_universe_panel,
            "continuous-contracts": self._continuous_contracts_panel,
        }
        handler = handlers.get(panel_id)
        if handler is None:
            raise HTTPException(status_code=404, detail=f"unsupported research panel: {panel_id}")
        return handler(product=product, contract=contract, start=resolved_start, end=resolved_end, definition=definition)

    def get_member_rank_panel(
        self,
        *,
        symbol: str,
        contract: str | None = None,
        start: date | None = None,
        end: date | None = None,
        rank_by: str = "volume",
    ) -> FuturesResearchPanelResponse:
        normalized_rank_by = rank_by.strip().lower()
        if normalized_rank_by not in VALID_MEMBER_RANK_BY:
            raise HTTPException(status_code=422, detail=f"rank_by must be one of: {', '.join(sorted(VALID_MEMBER_RANK_BY))}")
        product = _normalize_symbol(symbol)
        resolved_start, resolved_end = _resolve_date_range(start, end)
        return self._member_rank_panel(
            product=product,
            contract=contract,
            start=resolved_start,
            end=resolved_end,
            rank_by=normalized_rank_by,
            definition=PANEL_DEFINITIONS["member-rank"],
        )

    def _dominant_panel(self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(MainContractMap)
            .where(
                func.lower(MainContractMap.instrument_symbol) == product,
                MainContractMap.rank == 1,
                MainContractMap.provider == PROVIDER,
                MainContractMap.trade_date >= start,
                MainContractMap.trade_date <= end,
            )
            .order_by(MainContractMap.trade_date.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(MainContractMap, MainContractMap.instrument_symbol, product)
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "contract_code": item.contract_code,
                "rank": item.rank,
                "rule": item.rule,
                "data_version": item.data_version,
            }
            for item in rows_db
        ]
        chart = _contract_step_chart(rows, date_key="trade_date", contract_key="contract_code")
        return _build_response(
            panel_id="dominant",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="contract_code", title="主力合约", width=120),
                ColumnSpec(key="rank", title="Rank", width=70),
                ColumnSpec(key="rule", title="规则", width=140),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _ex_factor_panel(self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(FuturesExFactor)
            .where(
                func.lower(FuturesExFactor.instrument_symbol) == product,
                FuturesExFactor.provider == PROVIDER,
                FuturesExFactor.trade_date >= start,
                FuturesExFactor.trade_date <= end,
            )
            .order_by(FuturesExFactor.trade_date.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(FuturesExFactor, FuturesExFactor.instrument_symbol, product)
        rows = []
        for item in rows_db:
            payload = item.raw_payload or {}
            rows.append(
                {
                    "trade_date": item.trade_date.isoformat(),
                    "contract_code": item.contract_code,
                    "ex_factor": _payload_decimal(payload, "ex_factor", item.prev_close_spread),
                    "ex_cum_factor": _payload_decimal(payload, "ex_cum_factor", item.prev_close_ratio),
                    "ex_end_date": _payload_date(payload, "ex_end_date"),
                    "data_version": item.data_version,
                }
            )
        x_axis = [row["trade_date"] for row in rows]
        chart = ChartSpec(
            chart_type="line",
            x_axis=x_axis,
            series=[
                ChartSeriesSpec(name="复权因子", data=[row["ex_factor"] for row in rows], y_axis_index=0),
                ChartSeriesSpec(name="累计复权因子", data=[row["ex_cum_factor"] for row in rows], y_axis_index=1),
            ],
        )
        return _build_response(
            panel_id="ex-factor",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="除权日", width=120),
                ColumnSpec(key="contract_code", title="合约", width=110),
                ColumnSpec(key="ex_factor", title="复权因子", width=110),
                ColumnSpec(key="ex_cum_factor", title="累计因子", width=110),
                ColumnSpec(key="ex_end_date", title="因子截止日", width=120),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _trading_parameters_panel(
        self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]
    ) -> FuturesResearchPanelResponse:
        contract_code = contract or ""
        rows_db = self.session.scalars(
            select(FuturesTradingParameter)
            .where(
                FuturesTradingParameter.contract_code == contract_code,
                FuturesTradingParameter.provider == PROVIDER,
                FuturesTradingParameter.trade_date >= start,
                FuturesTradingParameter.trade_date <= end,
            )
            .order_by(FuturesTradingParameter.trade_date.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds_for_contract(FuturesTradingParameter, contract_code)
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "long_margin_ratio": _decimal(item.long_margin_ratio),
                "short_margin_ratio": _decimal(item.short_margin_ratio),
                "open_commission": _decimal(item.open_commission),
                "close_commission": _decimal(item.close_commission),
                "close_today_commission": _decimal(item.close_today_commission),
                "commission_type": item.commission_type,
                "price_tick": _decimal(item.price_tick),
                "contract_multiplier": item.contract_multiplier,
                "data_version": item.data_version,
            }
            for item in rows_db
        ]
        x_axis = [row["trade_date"] for row in rows]
        chart = ChartSpec(
            chart_type="line",
            x_axis=x_axis,
            series=[
                ChartSeriesSpec(name="多头保证金率", data=[row["long_margin_ratio"] for row in rows]),
                ChartSeriesSpec(name="开仓手续费", data=[row["open_commission"] for row in rows], y_axis_index=1),
            ],
        )
        return _build_response(
            panel_id="trading-parameters",
            symbol=product,
            contract=contract_code,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="long_margin_ratio", title="多头保证金率", width=120),
                ColumnSpec(key="short_margin_ratio", title="空头保证金率", width=120),
                ColumnSpec(key="open_commission", title="开仓手续费", width=110),
                ColumnSpec(key="close_commission", title="平仓手续费", width=110),
                ColumnSpec(key="price_tick", title="最小变动", width=90),
                ColumnSpec(key="contract_multiplier", title="乘数", width=80),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _warehouse_stocks_panel(self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(FuturesWarehouseStock)
            .where(
                func.lower(FuturesWarehouseStock.instrument_symbol) == product,
                FuturesWarehouseStock.provider == PROVIDER,
                FuturesWarehouseStock.trade_date >= start,
                FuturesWarehouseStock.trade_date <= end,
            )
            .order_by(FuturesWarehouseStock.trade_date.asc(), FuturesWarehouseStock.warehouse.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(FuturesWarehouseStock, FuturesWarehouseStock.instrument_symbol, product)
        by_date: dict[str, float] = defaultdict(float)
        rows = []
        for item in rows_db:
            qty = _decimal(item.quantity)
            rows.append(
                {
                    "trade_date": item.trade_date.isoformat(),
                    "warehouse": item.warehouse or "-",
                    "quantity": qty,
                    "unit": item.unit,
                    "data_version": item.data_version,
                }
            )
            if qty is not None:
                by_date[item.trade_date.isoformat()] += qty
        x_axis = sorted(by_date.keys())
        chart = ChartSpec(
            chart_type="line",
            x_axis=x_axis,
            series=[ChartSeriesSpec(name="注册仓单合计", data=[by_date[key] for key in x_axis])],
        )
        return _build_response(
            panel_id="warehouse-stocks",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="warehouse", title="仓库", width=140),
                ColumnSpec(key="quantity", title="仓单量", width=110),
                ColumnSpec(key="unit", title="单位", width=80),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _roll_yield_panel(self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(FuturesRollYield)
            .where(
                func.lower(FuturesRollYield.instrument_symbol) == product,
                FuturesRollYield.provider == PROVIDER,
                FuturesRollYield.trade_date >= start,
                FuturesRollYield.trade_date <= end,
            )
            .order_by(FuturesRollYield.trade_date.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(FuturesRollYield, FuturesRollYield.instrument_symbol, product)
        rows = []
        for item in rows_db:
            payload = item.raw_payload or {}
            rows.append(
                {
                    "trade_date": item.trade_date.isoformat(),
                    "near_contract": item.near_contract,
                    "far_contract": item.far_contract,
                    "roll_yield": _payload_decimal(payload, "yield", item.roll_yield),
                    "annualized_yield": _payload_decimal(payload, "annualized_yield"),
                    "annualized_yield_trading": _payload_decimal(payload, "annualized_yield_trading"),
                    "data_version": item.data_version,
                }
            )
        x_axis = [row["trade_date"] for row in rows]
        chart = ChartSpec(
            chart_type="line",
            x_axis=x_axis,
            series=[
                ChartSeriesSpec(name="展期收益率", data=[row["roll_yield"] for row in rows]),
                ChartSeriesSpec(name="交易日年化", data=[row["annualized_yield_trading"] for row in rows], y_axis_index=1),
            ],
        )
        return _build_response(
            panel_id="roll-yield",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="near_contract", title="近端合约", width=110),
                ColumnSpec(key="far_contract", title="远端合约", width=110),
                ColumnSpec(key="roll_yield", title="展期收益率", width=110),
                ColumnSpec(key="annualized_yield_trading", title="交易日年化", width=120),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _contract_universe_panel(self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(FuturesContractUniverse)
            .where(
                func.lower(FuturesContractUniverse.instrument_symbol) == product,
                FuturesContractUniverse.provider == PROVIDER,
                FuturesContractUniverse.trade_date >= start,
                FuturesContractUniverse.trade_date <= end,
            )
            .order_by(FuturesContractUniverse.trade_date.asc(), FuturesContractUniverse.sort_order.asc().nulls_last())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(FuturesContractUniverse, FuturesContractUniverse.instrument_symbol, product)
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in rows_db:
            grouped[item.trade_date.isoformat()].append(item.contract_code)
        rows = [
            {
                "trade_date": trade_date,
                "contract_count": len(contracts),
                "contracts": ", ".join(contracts),
                "data_version": rows_db[0].data_version if rows_db else None,
            }
            for trade_date, contracts in grouped.items()
        ]
        x_axis = [row["trade_date"] for row in rows]
        chart = ChartSpec(
            chart_type="bar",
            x_axis=x_axis,
            series=[ChartSeriesSpec(name="可交易合约数", data=[row["contract_count"] for row in rows])],
        )
        return _build_response(
            panel_id="contract-universe",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="contract_count", title="合约数", width=90),
                ColumnSpec(key="contracts", title="合约列表", width=420),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _continuous_contracts_panel(
        self, *, product: str, contract: str | None, start: date, end: date, definition: dict[str, Any]
    ) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(FuturesContinuousContractMap)
            .where(
                func.lower(FuturesContinuousContractMap.instrument_symbol) == product,
                FuturesContinuousContractMap.provider == PROVIDER,
                FuturesContinuousContractMap.continuous_type == "front_month",
                FuturesContinuousContractMap.trade_date >= start,
                FuturesContinuousContractMap.trade_date <= end,
            )
            .order_by(FuturesContinuousContractMap.trade_date.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(FuturesContinuousContractMap, FuturesContinuousContractMap.instrument_symbol, product)
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "continuous_type": item.continuous_type,
                "contract_code": item.contract_code,
                "data_version": item.data_version,
            }
            for item in rows_db
        ]
        chart = _contract_step_chart(rows, date_key="trade_date", contract_key="contract_code")
        return _build_response(
            panel_id="continuous-contracts",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="continuous_type", title="类型", width=100),
                ColumnSpec(key="contract_code", title="近月合约", width=120),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _member_rank_panel(
        self,
        *,
        product: str,
        contract: str | None,
        start: date,
        end: date,
        rank_by: str,
        definition: dict[str, Any],
    ) -> FuturesResearchPanelResponse:
        rows_db = self.session.scalars(
            select(FuturesMemberRank)
            .where(
                func.lower(FuturesMemberRank.instrument_symbol) == product,
                FuturesMemberRank.rank_by == rank_by,
                FuturesMemberRank.provider == PROVIDER,
                FuturesMemberRank.trade_date >= start,
                FuturesMemberRank.trade_date <= end,
            )
            .order_by(FuturesMemberRank.trade_date.asc(), FuturesMemberRank.rank.asc())
            .limit(MAX_ROWS)
        ).all()
        local_min, local_max = self._coverage_bounds(FuturesMemberRank, FuturesMemberRank.instrument_symbol, product)
        rank_label = MEMBER_RANK_BY_LABELS.get(rank_by, rank_by)
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "rank": item.rank,
                "member_name": item.member_name,
                "volume": _decimal(item.volume),
                "volume_change": _decimal(item.volume_change),
                "rank_by": item.rank_by,
                "commodity_id": item.commodity_id,
                "data_version": item.data_version,
            }
            for item in rows_db
        ]
        snapshot_trade_date: date | None = None
        snapshot_rows: list[FuturesMemberRank] = []
        if rows_db:
            snapshot_trade_date = max(item.trade_date for item in rows_db)
            snapshot_rows = [item for item in rows_db if item.trade_date == snapshot_trade_date]
            snapshot_rows.sort(key=lambda item: item.rank)
            snapshot_rows = snapshot_rows[:MEMBER_RANK_TOP_N]
        snapshot_label = snapshot_trade_date.isoformat() if snapshot_trade_date else ""
        chart = ChartSpec(
            chart_type="bar",
            x_axis=[item.member_name for item in snapshot_rows],
            series=[
                ChartSeriesSpec(
                    name=f"Top{MEMBER_RANK_TOP_N} {rank_label}" + (f" ({snapshot_label})" if snapshot_label else ""),
                    data=[_decimal(item.volume) for item in snapshot_rows],
                )
            ],
        )
        if snapshot_trade_date is not None:
            for row in rows:
                row["snapshot_trade_date"] = snapshot_label
        return _build_response(
            panel_id="member-rank",
            symbol=product,
            contract=contract,
            start=start,
            end=end,
            rows=rows,
            columns=[
                ColumnSpec(key="trade_date", title="交易日", width=120),
                ColumnSpec(key="rank", title="排名", width=70),
                ColumnSpec(key="member_name", title="会员", width=140),
                ColumnSpec(key="volume", title=rank_label, width=110),
                ColumnSpec(key="volume_change", title="变动", width=100),
                ColumnSpec(key="rank_by", title="排名依据", width=90),
            ],
            chart=chart,
            local_min=local_min,
            local_max=local_max,
            data_version=rows_db[0].data_version if rows_db else None,
            sync_script=definition["sync_script"],
        )

    def _local_coverage(self, panel_id: str, product: str) -> tuple[date | None, date | None]:
        mapping = {
            "dominant": (MainContractMap, MainContractMap.instrument_symbol),
            "ex-factor": (FuturesExFactor, FuturesExFactor.instrument_symbol),
            "warehouse-stocks": (FuturesWarehouseStock, FuturesWarehouseStock.instrument_symbol),
            "roll-yield": (FuturesRollYield, FuturesRollYield.instrument_symbol),
            "contract-universe": (FuturesContractUniverse, FuturesContractUniverse.instrument_symbol),
            "continuous-contracts": (FuturesContinuousContractMap, FuturesContinuousContractMap.instrument_symbol),
            "member-rank": (FuturesMemberRank, FuturesMemberRank.instrument_symbol),
        }
        if panel_id not in mapping:
            return None, None
        model, column = mapping[panel_id]
        return self._coverage_bounds(model, column, product)

    def _coverage_bounds(self, model: Any, column: Any, product: str) -> tuple[date | None, date | None]:
        local_min = self.session.scalar(
            select(func.min(model.trade_date)).where(func.lower(column) == product, model.provider == PROVIDER)
        )
        local_max = self.session.scalar(
            select(func.max(model.trade_date)).where(func.lower(column) == product, model.provider == PROVIDER)
        )
        return local_min, local_max

    def _coverage_bounds_for_contract(self, model: Any, contract_code: str) -> tuple[date | None, date | None]:
        local_min = self.session.scalar(
            select(func.min(model.trade_date)).where(model.contract_code == contract_code, model.provider == PROVIDER)
        )
        local_max = self.session.scalar(
            select(func.max(model.trade_date)).where(model.contract_code == contract_code, model.provider == PROVIDER)
        )
        return local_min, local_max


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().lower()


def _resolve_date_range(start: date | None, end: date | None) -> tuple[date, date]:
    today = date.today()
    resolved_end = end or today
    resolved_start = start or (resolved_end - timedelta(days=DEFAULT_SPAN_DAYS))
    if resolved_start > resolved_end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    if (resolved_end - resolved_start).days > MAX_SPAN_DAYS:
        raise HTTPException(status_code=422, detail=f"date span exceeds {MAX_SPAN_DAYS} days")
    return resolved_start, resolved_end


def _decimal(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _payload_decimal(payload: dict[str, Any], *keys: str, fallback: Decimal | None = None) -> float | None:
    for key in keys:
        if key in payload and payload[key] is not None:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                continue
    return _decimal(fallback)


def _payload_date(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value)[:10]


def _contract_step_chart(rows: list[dict[str, Any]], *, date_key: str, contract_key: str) -> ChartSpec:
    if not rows:
        return ChartSpec(chart_type="step", x_axis=[], series=[])
    contracts = sorted({str(row[contract_key]) for row in rows if row.get(contract_key)})
    contract_index = {code: index for index, code in enumerate(contracts)}
    x_axis = [str(row[date_key]) for row in rows]
    data = [contract_index.get(str(row.get(contract_key)), None) for row in rows]
    return ChartSpec(
        chart_type="step",
        x_axis=x_axis,
        y_axis_categories=contracts,
        series=[ChartSeriesSpec(name="合约", data=data)],
    )


def _build_response(
    *,
    panel_id: str,
    symbol: str,
    contract: str | None,
    start: date,
    end: date,
    rows: list[dict[str, Any]],
    columns: list[ColumnSpec],
    chart: ChartSpec,
    local_min: date | None,
    local_max: date | None,
    data_version: str | None,
    sync_script: str | None,
) -> FuturesResearchPanelResponse:
    requested_filled = bool(rows) and (local_min is None or local_min <= start) and (local_max is None or local_max >= end)
    empty_reason = None
    if not rows:
        script_hint = f"请运行 {sync_script}" if sync_script else "请先完成数据同步"
        coverage_hint = ""
        if local_min and local_max:
            coverage_hint = f"本地覆盖 {local_min.isoformat()} ~ {local_max.isoformat()}，"
        empty_reason = f"{coverage_hint}当前区间无数据。{script_hint}"
    return FuturesResearchPanelResponse(
        panel_id=panel_id,
        symbol=symbol,
        contract=contract,
        start=start,
        end=end,
        data_version=data_version,
        row_count=len(rows),
        coverage=CoverageSummary(
            local_min_date=local_min,
            local_max_date=local_max,
            requested_start=start,
            requested_end=end,
            requested_filled=requested_filled,
        ),
        chart=chart,
        columns=columns,
        rows=rows,
        empty_reason=empty_reason,
    )
