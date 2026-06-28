# BacktestResult v1.0 唯一标准模型

生成时间：2026-06-28  
适用阶段：V1 Web 研究闭环 / JM V1-Final 后续报告口径加固  
交付类型：设计文档，不是业务代码实现  

## 1. 模型定位

`BacktestResult v1.0` 是归一量化回测结果的唯一事实模型。它只保存两类事实：

1. `report`：本次回测的摘要、元数据、绩效指标。
2. `trades`：逐笔完整交易事实。

`BacktestResult v1.0` 不保存任何曲线。资金曲线、回撤曲线、月度收益、方向收益、日夜盘统计、exit_reason 统计、图表展示数据，都必须由 `trades` 按确定规则临时推导。

本标准用于解决旧口径中 report / trade / equity_curve / drawdown_curve 互相不一致的问题。回测结果不等于实盘结果，不得据此直接进入自动交易。

## 2. 强制存储规则

### 2.1 根对象

根对象只能包含：

- `schema_version`
- `generated_at`
- `report`
- `trades`

根对象禁止包含：

- `equity_curve`
- `drawdown_curve`
- `balance_curve`
- `orders`
- `fills`
- `daily_results`
- `curve`
- `curves`

### 2.2 trade 是唯一盈亏事实源

每一笔 `trade` 必须包含：

- 交易身份：`trade_id`、`sequence`
- 合约与周期：`symbol`、`exchange`、`research_contract`、`entry_contract`、`exit_contract`、`timeframe`
- 成交事实：`direction`、`volume`、`entry_time`、`entry_price`、`exit_time`、`exit_price`
- 成本与收益：`contract_multiplier`、`price_tick`、`gross_pnl`、`commission`、`slippage`、`net_pnl`
- 保证金：`margin_ratio`、`margin_required`
- 复盘与风险：`holding_bars`、`entry_reason`、`exit_reason`、`rollover_forced_exit`、`delivery_risk_exit`

`trade` 禁止保存曲线派生字段：

- `balance`
- `equity`
- `equity_after_trade`
- `drawdown`
- `drawdown_pct`
- `peak_equity`

### 2.3 report 只保存摘要和元数据

`report` 保存：

- 身份字段：`result_id`、`task_no`、`report_no`、`status`
- 引擎和策略字段：`engine_type`、`engine_version`、`strategy_code`、`strategy_version`
- 数据字段：`symbol`、`exchange`、`research_contract`、`timeframe`、`start`、`end`、`data_source`、`data_role`、`data_version`、`quality_status`
- 指标字段：总收益、年化收益、最大回撤、胜率、盈亏比、期望值、手续费、滑点、保证金、最大连亏等

`report` 禁止保存 curve 数组。`final_equity` 必须等于：

```text
initial_capital + sum(trades[*].net_pnl)
```

## 3. 曲线推导规则

标准曲线定义为“已实现权益曲线”，只在查询、展示、分析时临时推导。

排序规则：

```text
(exit_time, sequence, trade_id) ASC
```

权益推导：

```text
equity_0 = report.initial_capital
equity_n = equity_(n-1) + sorted_trades[n].net_pnl
```

回撤推导：

```text
peak_n = max(equity_0 ... equity_n)
drawdown_amount_n = peak_n - equity_n
drawdown_pct_n = drawdown_amount_n / peak_n
```

聚合规则：

- 月度收益：按 `exit_time` 所属月份分组，汇总 `net_pnl`。
- 方向收益：按 `direction` 分组，汇总 `gross_pnl`、`commission`、`slippage`、`net_pnl`。
- 日夜盘统计：按 `entry_time` 的交易时段标记分组，汇总 trade。
- exit_reason 统计：按 `exit_reason` 分组，汇总 trade。

Web 或 API 可以返回 derived curve，但不得写回 `BacktestResult`、`report` JSON 或数据库事实表。

## 4. JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://guiyi-quant.local/schemas/backtest-result-v1.0.json",
  "title": "BacktestResultV1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "generated_at", "report", "trades"],
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "backtest_result.v1.0"
    },
    "generated_at": {
      "type": "string",
      "format": "date-time"
    },
    "report": {
      "$ref": "#/$defs/BacktestReportV1"
    },
    "trades": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/BacktestTradeV1"
      }
    }
  },
  "not": {
    "anyOf": [
      { "required": ["equity_curve"] },
      { "required": ["drawdown_curve"] },
      { "required": ["balance_curve"] },
      { "required": ["orders"] },
      { "required": ["fills"] },
      { "required": ["daily_results"] },
      { "required": ["curve"] },
      { "required": ["curves"] }
    ]
  },
  "$defs": {
    "BacktestReportV1": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "result_id",
        "task_no",
        "report_no",
        "status",
        "engine_type",
        "engine_version",
        "strategy_code",
        "strategy_version",
        "symbol",
        "exchange",
        "research_contract",
        "timeframe",
        "start",
        "end",
        "data_source",
        "data_role",
        "data_version",
        "quality_status",
        "initial_capital",
        "final_equity",
        "total_gross_pnl",
        "total_net_pnl",
        "total_return",
        "annual_return",
        "max_drawdown_amount",
        "max_drawdown_pct",
        "trade_count",
        "win_rate",
        "profit_loss_ratio",
        "expectancy",
        "max_consecutive_losses",
        "total_commission",
        "total_slippage",
        "max_margin_required",
        "max_margin_usage_pct",
        "rollover_exit_count",
        "delivery_risk_exit_count",
        "average_holding_bars"
      ],
      "properties": {
        "result_id": { "type": "string", "minLength": 1 },
        "task_no": { "type": "string", "minLength": 1 },
        "report_no": { "type": "string", "minLength": 1 },
        "status": {
          "type": "string",
          "enum": ["success", "failed", "diagnostic_only", "invalid"]
        },
        "engine_type": { "type": "string", "minLength": 1 },
        "engine_version": { "type": ["string", "null"] },
        "strategy_code": { "type": "string", "minLength": 1 },
        "strategy_version": { "type": "string", "minLength": 1 },
        "symbol": { "type": "string", "minLength": 1 },
        "exchange": { "type": "string", "minLength": 1 },
        "research_contract": { "type": "string", "minLength": 1 },
        "timeframe": { "type": "string", "minLength": 1 },
        "start": { "type": "string", "format": "date-time" },
        "end": { "type": "string", "format": "date-time" },
        "data_source": { "type": "string", "minLength": 1 },
        "data_role": {
          "type": "string",
          "enum": ["primary", "validation", "legacy_reference"]
        },
        "data_version": { "type": ["string", "null"] },
        "quality_status": {
          "type": "string",
          "enum": ["passed", "warning", "failed", "unknown"]
        },
        "initial_capital": { "type": "number", "exclusiveMinimum": 0 },
        "final_equity": { "type": "number" },
        "total_gross_pnl": { "type": "number" },
        "total_net_pnl": { "type": "number" },
        "total_return": { "type": "number" },
        "annual_return": { "type": "number" },
        "max_drawdown_amount": { "type": "number", "minimum": 0 },
        "max_drawdown_pct": { "type": "number", "minimum": 0 },
        "trade_count": { "type": "integer", "minimum": 0 },
        "win_rate": { "type": "number", "minimum": 0, "maximum": 1 },
        "profit_loss_ratio": { "type": "number", "minimum": 0 },
        "expectancy": { "type": "number" },
        "max_consecutive_losses": { "type": "integer", "minimum": 0 },
        "total_commission": { "type": "number", "minimum": 0 },
        "total_slippage": { "type": "number", "minimum": 0 },
        "max_margin_required": { "type": "number", "minimum": 0 },
        "max_margin_usage_pct": { "type": "number", "minimum": 0 },
        "rollover_exit_count": { "type": "integer", "minimum": 0 },
        "delivery_risk_exit_count": { "type": "integer", "minimum": 0 },
        "average_holding_bars": { "type": ["number", "null"], "minimum": 0 }
      },
      "not": {
        "anyOf": [
          { "required": ["equity_curve"] },
          { "required": ["drawdown_curve"] },
          { "required": ["balance_curve"] },
          { "required": ["curve"] },
          { "required": ["curves"] }
        ]
      }
    },
    "BacktestTradeV1": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "trade_id",
        "sequence",
        "symbol",
        "exchange",
        "research_contract",
        "entry_contract",
        "exit_contract",
        "timeframe",
        "direction",
        "volume",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "contract_multiplier",
        "price_tick",
        "gross_pnl",
        "commission",
        "slippage",
        "net_pnl",
        "margin_ratio",
        "margin_required",
        "holding_bars",
        "entry_reason",
        "exit_reason",
        "rollover_forced_exit",
        "delivery_risk_exit"
      ],
      "properties": {
        "trade_id": { "type": "string", "minLength": 1 },
        "sequence": { "type": "integer", "minimum": 1 },
        "symbol": { "type": "string", "minLength": 1 },
        "exchange": { "type": "string", "minLength": 1 },
        "research_contract": { "type": "string", "minLength": 1 },
        "entry_contract": { "type": "string", "minLength": 1 },
        "exit_contract": { "type": "string", "minLength": 1 },
        "timeframe": { "type": "string", "minLength": 1 },
        "direction": {
          "type": "string",
          "enum": ["long", "short"]
        },
        "volume": { "type": "integer", "minimum": 1 },
        "entry_time": { "type": "string", "format": "date-time" },
        "entry_signal_time": { "type": ["string", "null"], "format": "date-time" },
        "entry_price": { "type": "number", "exclusiveMinimum": 0 },
        "exit_time": { "type": "string", "format": "date-time" },
        "exit_signal_time": { "type": ["string", "null"], "format": "date-time" },
        "exit_price": { "type": "number", "exclusiveMinimum": 0 },
        "contract_multiplier": { "type": "integer", "minimum": 1 },
        "price_tick": { "type": "number", "exclusiveMinimum": 0 },
        "gross_pnl": { "type": "number" },
        "commission": { "type": "number", "minimum": 0 },
        "slippage": { "type": "number", "minimum": 0 },
        "net_pnl": { "type": "number" },
        "margin_ratio": { "type": "number", "minimum": 0 },
        "margin_required": { "type": "number", "minimum": 0 },
        "holding_bars": { "type": "integer", "minimum": 0 },
        "entry_reason": { "type": "string", "minLength": 1 },
        "exit_reason": { "type": "string", "minLength": 1 },
        "stop_loss_price": { "type": ["number", "null"], "exclusiveMinimum": 0 },
        "rollover_forced_exit": { "type": "boolean" },
        "delivery_risk_exit": { "type": "boolean" },
        "parameter_source": { "type": ["string", "null"] },
        "main_contract_source": {
          "type": ["object", "null"],
          "additionalProperties": true
        },
        "fee_rule_source": {
          "type": ["object", "null"],
          "additionalProperties": true
        }
      },
      "not": {
        "anyOf": [
          { "required": ["balance"] },
          { "required": ["equity"] },
          { "required": ["equity_after_trade"] },
          { "required": ["drawdown"] },
          { "required": ["drawdown_pct"] },
          { "required": ["peak_equity"] }
        ]
      }
    }
  }
}
```

## 5. Python dataclass

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isclose
from typing import Any, Literal


SCHEMA_VERSION = "backtest_result.v1.0"
MONEY_TOLERANCE = 1e-6
RATIO_TOLERANCE = 1e-9


Direction = Literal["long", "short"]
ResultStatus = Literal["success", "failed", "diagnostic_only", "invalid"]
DataRole = Literal["primary", "validation", "legacy_reference"]
QualityStatus = Literal["passed", "warning", "failed", "unknown"]


@dataclass(frozen=True)
class BacktestTradeV1:
    trade_id: str
    sequence: int
    symbol: str
    exchange: str
    research_contract: str
    entry_contract: str
    exit_contract: str
    timeframe: str
    direction: Direction
    volume: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    contract_multiplier: int
    price_tick: float
    gross_pnl: float
    commission: float
    slippage: float
    net_pnl: float
    margin_ratio: float
    margin_required: float
    holding_bars: int
    entry_reason: str
    exit_reason: str
    rollover_forced_exit: bool
    delivery_risk_exit: bool
    entry_signal_time: datetime | None = None
    exit_signal_time: datetime | None = None
    stop_loss_price: float | None = None
    parameter_source: str | None = None
    main_contract_source: dict[str, Any] | None = None
    fee_rule_source: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_text(self.trade_id, "trade_id")
        _require_text(self.symbol, "symbol")
        _require_text(self.exchange, "exchange")
        _require_text(self.research_contract, "research_contract")
        _require_text(self.entry_contract, "entry_contract")
        _require_text(self.exit_contract, "exit_contract")
        _require_text(self.timeframe, "timeframe")
        _require_text(self.entry_reason, "entry_reason")
        _require_text(self.exit_reason, "exit_reason")

        if self.sequence < 1:
            raise ValueError("sequence must be >= 1")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.volume < 1:
            raise ValueError("volume must be >= 1")
        if self.entry_price <= 0 or self.exit_price <= 0:
            raise ValueError("entry_price and exit_price must be positive")
        if self.contract_multiplier < 1:
            raise ValueError("contract_multiplier must be >= 1")
        if self.price_tick <= 0:
            raise ValueError("price_tick must be positive")
        if self.commission < 0 or self.slippage < 0:
            raise ValueError("commission and slippage must be >= 0")
        if self.margin_ratio < 0 or self.margin_required < 0:
            raise ValueError("margin_ratio and margin_required must be >= 0")
        if self.holding_bars < 0:
            raise ValueError("holding_bars must be >= 0")
        if self.entry_time > self.exit_time:
            raise ValueError("entry_time cannot be later than exit_time")
        if self.stop_loss_price is not None and self.stop_loss_price <= 0:
            raise ValueError("stop_loss_price must be positive when provided")

        expected_gross = self.derived_gross_pnl()
        if not isclose(self.gross_pnl, expected_gross, abs_tol=MONEY_TOLERANCE):
            raise ValueError("gross_pnl must equal price difference * volume * contract_multiplier")
        expected_net = self.gross_pnl - self.commission - self.slippage
        if not isclose(self.net_pnl, expected_net, abs_tol=MONEY_TOLERANCE):
            raise ValueError("net_pnl must equal gross_pnl - commission - slippage")

    def derived_gross_pnl(self) -> float:
        if self.direction == "long":
            return (self.exit_price - self.entry_price) * self.volume * self.contract_multiplier
        return (self.entry_price - self.exit_price) * self.volume * self.contract_multiplier


@dataclass(frozen=True)
class BacktestReportV1:
    result_id: str
    task_no: str
    report_no: str
    status: ResultStatus
    engine_type: str
    engine_version: str | None
    strategy_code: str
    strategy_version: str
    symbol: str
    exchange: str
    research_contract: str
    timeframe: str
    start: datetime
    end: datetime
    data_source: str
    data_role: DataRole
    data_version: str | None
    quality_status: QualityStatus
    initial_capital: float
    final_equity: float
    total_gross_pnl: float
    total_net_pnl: float
    total_return: float
    annual_return: float
    max_drawdown_amount: float
    max_drawdown_pct: float
    trade_count: int
    win_rate: float
    profit_loss_ratio: float
    expectancy: float
    max_consecutive_losses: int
    total_commission: float
    total_slippage: float
    max_margin_required: float
    max_margin_usage_pct: float
    rollover_exit_count: int
    delivery_risk_exit_count: int
    average_holding_bars: float | None

    def __post_init__(self) -> None:
        for field_name in (
            "result_id",
            "task_no",
            "report_no",
            "engine_type",
            "strategy_code",
            "strategy_version",
            "symbol",
            "exchange",
            "research_contract",
            "timeframe",
            "data_source",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.status not in {"success", "failed", "diagnostic_only", "invalid"}:
            raise ValueError("invalid status")
        if self.data_role not in {"primary", "validation", "legacy_reference"}:
            raise ValueError("invalid data_role")
        if self.quality_status not in {"passed", "warning", "failed", "unknown"}:
            raise ValueError("invalid quality_status")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        if self.trade_count < 0:
            raise ValueError("trade_count must be >= 0")
        if not 0 <= self.win_rate <= 1:
            raise ValueError("win_rate must be in [0, 1]")
        for field_name in (
            "max_drawdown_amount",
            "max_drawdown_pct",
            "profit_loss_ratio",
            "total_commission",
            "total_slippage",
            "max_margin_required",
            "max_margin_usage_pct",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be >= 0")
        if self.max_consecutive_losses < 0:
            raise ValueError("max_consecutive_losses must be >= 0")
        if self.rollover_exit_count < 0 or self.delivery_risk_exit_count < 0:
            raise ValueError("exit counts must be >= 0")
        if self.average_holding_bars is not None and self.average_holding_bars < 0:
            raise ValueError("average_holding_bars must be >= 0 when provided")


@dataclass(frozen=True)
class DerivedEquityPoint:
    point_index: int
    point_time: datetime | None
    equity: float
    drawdown_amount: float
    drawdown_pct: float
    source_trade_id: str | None = None


@dataclass(frozen=True)
class BacktestResultV1:
    schema_version: str
    generated_at: datetime
    report: BacktestReportV1
    trades: tuple[BacktestTradeV1, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        self._validate_report_matches_trades()

    def sorted_trades(self) -> tuple[BacktestTradeV1, ...]:
        return tuple(sorted(self.trades, key=lambda trade: (trade.exit_time, trade.sequence, trade.trade_id)))

    def derive_equity_curve(self) -> tuple[DerivedEquityPoint, ...]:
        points: list[DerivedEquityPoint] = []
        equity = self.report.initial_capital
        peak = equity
        points.append(
            DerivedEquityPoint(
                point_index=0,
                point_time=self.report.start,
                equity=equity,
                drawdown_amount=0.0,
                drawdown_pct=0.0,
            )
        )
        for index, trade in enumerate(self.sorted_trades(), start=1):
            equity += trade.net_pnl
            peak = max(peak, equity)
            drawdown_amount = peak - equity
            drawdown_pct = drawdown_amount / peak if peak else 0.0
            points.append(
                DerivedEquityPoint(
                    point_index=index,
                    point_time=trade.exit_time,
                    equity=equity,
                    drawdown_amount=drawdown_amount,
                    drawdown_pct=drawdown_pct,
                    source_trade_id=trade.trade_id,
                )
            )
        return tuple(points)

    def _validate_report_matches_trades(self) -> None:
        trades = self.trades
        total_gross_pnl = sum(trade.gross_pnl for trade in trades)
        total_net_pnl = sum(trade.net_pnl for trade in trades)
        total_commission = sum(trade.commission for trade in trades)
        total_slippage = sum(trade.slippage for trade in trades)
        final_equity = self.report.initial_capital + total_net_pnl
        derived_curve = self.derive_equity_curve()
        max_drawdown_amount = max(point.drawdown_amount for point in derived_curve)
        max_drawdown_pct = max(point.drawdown_pct for point in derived_curve)

        _assert_close(self.report.total_gross_pnl, total_gross_pnl, "total_gross_pnl")
        _assert_close(self.report.total_net_pnl, total_net_pnl, "total_net_pnl")
        _assert_close(self.report.total_commission, total_commission, "total_commission")
        _assert_close(self.report.total_slippage, total_slippage, "total_slippage")
        _assert_close(self.report.final_equity, final_equity, "final_equity")
        _assert_close(self.report.max_drawdown_amount, max_drawdown_amount, "max_drawdown_amount")
        _assert_close(self.report.max_drawdown_pct, max_drawdown_pct, "max_drawdown_pct", tolerance=RATIO_TOLERANCE)

        if self.report.trade_count != len(trades):
            raise ValueError("trade_count must equal len(trades)")
        if self.report.max_margin_required != max((trade.margin_required for trade in trades), default=0.0):
            raise ValueError("max_margin_required must be derived from trades")
        if self.report.rollover_exit_count != sum(1 for trade in trades if trade.rollover_forced_exit):
            raise ValueError("rollover_exit_count must be derived from trades")
        if self.report.delivery_risk_exit_count != sum(1 for trade in trades if trade.delivery_risk_exit):
            raise ValueError("delivery_risk_exit_count must be derived from trades")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _assert_close(actual: float, expected: float, field_name: str, *, tolerance: float = MONEY_TOLERANCE) -> None:
    if not isclose(actual, expected, abs_tol=tolerance):
        raise ValueError(f"{field_name} does not match trades-derived value")
```

## 6. 验收规则

### 6.1 JSON Schema 验收

必须通过：

- 只含 `schema_version`、`generated_at`、`report`、`trades` 的合法样本。
- `trades=[]` 且 `trade_count=0`、`final_equity=initial_capital`、`max_drawdown_amount=0`、`max_drawdown_pct=0` 的空交易样本。
- 同一 `exit_time` 的多笔交易，使用 `sequence` 保证稳定排序。

必须拒绝：

- 根对象包含 `equity_curve`、`drawdown_curve`、`balance_curve`、`orders`、`fills`、`daily_results`。
- `trade` 缺少 `net_pnl`、`commission`、`slippage`、`contract_multiplier`、`price_tick`。
- `trade` 包含 `balance`、`equity_after_trade`、`drawdown`、`drawdown_pct`。
- `report` 包含任何 curve 字段。

### 6.2 dataclass 验收

必须验证：

- `report.final_equity == report.initial_capital + sum(trade.net_pnl)`。
- `report.total_gross_pnl == sum(trade.gross_pnl)`。
- `report.total_net_pnl == sum(trade.net_pnl)`。
- `report.total_commission == sum(trade.commission)`。
- `report.total_slippage == sum(trade.slippage)`。
- `report.trade_count == len(trades)`。
- `report.max_drawdown_amount` 和 `report.max_drawdown_pct` 只能由 `derive_equity_curve()` 得到。
- `report.max_margin_required == max(trade.margin_required)`。
- `rollover_exit_count` 和 `delivery_risk_exit_count` 只能由 trade 布尔字段汇总得到。

### 6.3 report_id=5/6 回归场景

report_id=5/6 的现有事实是标准模型的反例：

- report 表和 trade 表已能对齐。
- 旧 `equity_curve` / `drawdown_curve` 与 report/trade 不一致。

因此 v1.0 明确禁止 curve 成为存储事实。后续修复应先把 report/trade 转为 `BacktestResult v1.0`，再由 trade 推导曲线供 Web 临时展示。

## 7. 后续落地建议

本文件只是标准文档。后续如果进入实现任务，建议单独开任务：

1. 新增 `BacktestResult v1.0` 转换器。
2. 新增 schema / dataclass 单元测试。
3. 废弃 `backtest_reports.equity_curve`、`backtest_reports.drawdown_curve` JSON 字段的写入。
4. 废弃 `backtest_equity_curve`、`backtest_drawdown_curve` 作为事实表的写入。
5. API 曲线接口改为从 `backtest_trades` 临时推导返回。

后续实现仍不得覆盖旧 report_id=5/6，除非先做只读备份并由用户明确确认。
