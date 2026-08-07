from __future__ import annotations

from typing import Any

from app.models.signal import SignalEvent
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate

CHANNEL = "enterprise_wechat"


def build_stage9_wechat_preview(event: SignalEvent) -> dict[str, Any]:
    """Build a dry-run Enterprise WeChat markdown preview after the Stage 9 gate."""
    gate = evaluate_stage9_signal_event_gate(event)
    payload = build_stage9_wechat_payload_from_basis(gate["payload_basis"]) if gate["allowed"] else None
    return {
        "allowed": gate["allowed"],
        "blocked_reasons": gate["blocked_reasons"],
        "delivery_allowed": gate["delivery_allowed"],
        "delivery_blocked_reasons": gate["delivery_blocked_reasons"],
        "would_send": False,
        "channel": CHANNEL,
        "notification_recorded": False,
        "payload_basis": gate["payload_basis"],
        "wechat_payload": payload,
    }


def build_stage9_wechat_payload_from_basis(payload_basis: dict[str, Any]) -> dict[str, Any]:
    return _wechat_markdown_payload(payload_basis)


def _wechat_markdown_payload(payload_basis: dict[str, Any]) -> dict[str, Any]:
    return {
        "msgtype": "markdown",
        "markdown": {
            "content": _markdown_content(payload_basis),
        },
    }


def _markdown_content(payload_basis: dict[str, Any]) -> str:
    quality_status = payload_basis.get("quality_status") or {}
    quality_text = quality_status.get("status") if isinstance(quality_status, dict) else quality_status
    lines = [
        "## 归一量化观察提醒",
        "",
        "> observation_only / not_trading_instruction / auto_order=false",
        "",
        f"- 策略：{_text(payload_basis.get('strategy_name'))} {_text(payload_basis.get('strategy_version'))}",
        f"- 品种：{_text(payload_basis.get('product'))}",
        f"- 研究主连：{_text(payload_basis.get('continuous_contract'))}",
        f"- 真实合约：{_text(payload_basis.get('actual_contract'))}",
        f"- 周期：{_text(payload_basis.get('period'))}",
        f"- 方向：{_text(payload_basis.get('direction'))}",
        f"- bar_end：{_text(payload_basis.get('bar_end'))}",
        f"- trigger_price：{_text(payload_basis.get('trigger_price'))}",
        f"- 数据源：{_text(payload_basis.get('provider'))} / {_text(payload_basis.get('source'))}",
        f"- data_role：{_text(payload_basis.get('data_role'))}",
        f"- quality_status：{_text(quality_text)}",
        "",
        "仅用于人工观察，不构成交易指令，不自动下单。",
    ]
    return "\n".join(lines)


def _text(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)
