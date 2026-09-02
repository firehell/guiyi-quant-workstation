"""Runtime 运维健康检查响应模型（Pydantic）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuntimeComponentHealth(BaseModel):
    """通用组件健康（DB、Redis 等单点探测）。"""

    status: str
    latency_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeLiveMarketHealth(BaseModel):
    """Live V1 的短 TTL Redis heartbeat 快照。"""

    status: str
    configured_enabled: bool = False
    operational_count: int = 0
    subscribed_count: int = 0
    last_heartbeat_at: str | None = None
    last_bar_at: str | None = None
    phase_counts: dict[str, int] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


class RuntimeAfterMarketFailureNotification(BaseModel):
    """Owner PushPlus 的一次 provider acceptance 尝试，不代表送达。"""

    attempted_at: str
    state: Literal["provider_accepted", "failed"]
    error_type: str | None = None


class RuntimeAfterMarketRun(BaseModel):
    """盘后一次运行的公开摘要。"""

    trading_day: str
    status: str
    attempts: int
    started_at: str
    finished_at: str
    products: list[str] = Field(default_factory=list)
    error_code: str | None = None
    failure_notification: RuntimeAfterMarketFailureNotification | None = None


class RuntimeAfterMarketCurrentRun(BaseModel):
    """当前盘后自然运行的 crash-visible 摘要。"""

    scheduled_date: str
    started_at: str
    products: list[str] = Field(default_factory=list)


class RuntimeAfterMarketHealth(BaseModel):
    """由本地公开状态文件派生的盘后维护摘要。"""

    status: str
    configured_enabled: bool = False
    run_state: str = "disabled"
    expected_trading_day: str | None = None
    current_run: RuntimeAfterMarketCurrentRun | None = None
    last_run: RuntimeAfterMarketRun | None = None
    last_successful_trading_day: str | None = None
    last_failure: dict[str, str] | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeAlertNotificationHealth(BaseModel):
    """Secret-safe structural notification audience readiness."""

    transport: str
    configured: bool = False
    audience_count: int = 0
    would_send: bool = False


class RuntimeAlertHealth(BaseModel):
    """Alert activation、notification transport 与短 TTL heartbeat 摘要。"""

    status: str
    configured_enabled: bool = False
    notification: RuntimeAlertNotificationHealth
    last_heartbeat_at: str | None = None
    enabled_rule_count: int = 0
    scope_product_count: int = 0
    processing_state: str = "unobserved"
    notification_state: str = "unobserved"
    last_processed_bar_at: str | None = None
    last_processing_success_at: str | None = None
    last_processing_failure_at: str | None = None
    processing_error_type: str | None = None
    last_event_at: str | None = None
    last_transport_attempt_at: str | None = None
    last_provider_accepted_at: str | None = None
    last_notification_failure_at: str | None = None
    notification_acknowledged_at: str | None = None
    notification_error_type: str | None = None
    consecutive_notification_failures: int = 0
    error_type: str | None = None


class RuntimeHealthComponents(BaseModel):
    """各子组件健康快照的容器。"""

    db: RuntimeComponentHealth
    redis: RuntimeComponentHealth
    live_market: RuntimeLiveMarketHealth
    after_market: RuntimeAfterMarketHealth
    alert: RuntimeAlertHealth


class RuntimeHealthOut(BaseModel):
    """``/api/runtime/health`` 顶层响应；顶层 readonly 标志声明无写操作授权。"""

    status: str
    generated_at: str
    readonly: bool = True
    would_start_services: bool = False
    would_enqueue_jobs: bool = False
    would_send_notifications: bool = False
    components: RuntimeHealthComponents
