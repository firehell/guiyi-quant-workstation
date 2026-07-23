---
inclusion: always
---

# 安全与风控规范（CRITICAL）

> ⚠️ 本文件规则为**强制执行级别**，任何违反都可能造成真实资金损失。

## 绝对禁止事项

```
❌ 硬编码任何凭据（API Key / 密码 / Token / 经纪商账户）
❌ 在回测环境外执行真实下单指令
❌ 跳过风控检查直接调用交易接口
❌ 使用浮点数进行资金计算（必须用 Decimal）
❌ 删除或覆盖 data/raw/ 下的原始数据
❌ 在未经验证的策略上分配超过测试资金的仓位
```

## 风控参数（从 .env 读取）

```python
MAX_POSITION_RATIO = float(os.getenv("RISK_MAX_POSITION_RATIO", "0.2"))
MAX_DAILY_LOSS = float(os.getenv("RISK_MAX_DAILY_LOSS", "0.05"))
MAX_DRAWDOWN = float(os.getenv("RISK_MAX_DRAWDOWN", "0.15"))
```

## 资金计算规范

```python
from decimal import Decimal, ROUND_HALF_UP

# ✅ 正确
price = Decimal("4521.50")
quantity = Decimal("2")
value = price * quantity  # Decimal 运算

# ❌ 错误
value = 4521.50 * 2  # 浮点误差不可接受
```

## 环境隔离

```python
import os

TRADING_ENV = os.getenv("APP_ENV", "development")

def submit_order(order: Order) -> None:
    if TRADING_ENV == "production":
        # 生产环境：真实下单前必须二次确认
        assert order.risk_checked, "风控未通过，拒绝下单"
        assert order.value <= MAX_SINGLE_ORDER_VALUE
        real_broker.submit(order)
    else:
        # 非生产环境：只允许模拟下单
        paper_broker.submit(order)
```

## 风控检查清单

提交涉及交易逻辑的 PR 前，必须确认：

- [ ] 是否有仓位上限检查？
- [ ] 是否有单日亏损熔断？
- [ ] 是否有最大回撤自动停止？
- [ ] 是否处理了网络断线/行情中断的异常？
- [ ] 是否有重复下单防护（幂等性）？
- [ ] 所有资金计算是否使用 Decimal？

## 日志要求

所有交易操作必须记录结构化日志：

```python
logger.info("order_submitted", extra={
    "strategy": strategy_id,
    "symbol": symbol,
    "direction": direction,
    "price": str(price),   # Decimal 转 str
    "quantity": str(quantity),
    "env": TRADING_ENV,
    "timestamp": datetime.utcnow().isoformat()
})
```
