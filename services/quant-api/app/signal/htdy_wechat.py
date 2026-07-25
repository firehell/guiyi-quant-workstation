from __future__ import annotations

from typing import Any

from app.models.signal import HtdyObservationAlert


def build_htdy_wechat_payload(alert: HtdyObservationAlert) -> dict[str, Any]:
    direction = {
        "long": "买多观察",
        "short": "卖空观察",
        "conflict": "多空冲突观察",
    }.get(alert.direction, "未知观察")
    content = "\n".join(
        (
            "## 火天大有原版 XMA 实时观察",
            "",
            "> observation_only / future_looking / repainting_risk=known",
            "",
            f"- 品种：{alert.symbol.upper()}",
            f"- 研究主连：{alert.continuous_contract}",
            f"- 实际合约：{alert.actual_contract}",
            f"- 周期：{alert.period}",
            f"- 观察：{direction}",
            f"- bar_end：{alert.bar_end.isoformat()}",
            f"- 观察价格：{alert.trigger_price}",
            "",
            "该指标包含未来函数，当前预警可能重绘、消失或反向。",
            "仅供人工观察，不是交易指令，不自动下单。",
        )
    )
    return {"msgtype": "markdown", "markdown": {"content": content}}


__all__ = ["build_htdy_wechat_payload"]
