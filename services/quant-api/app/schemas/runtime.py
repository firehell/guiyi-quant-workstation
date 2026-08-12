"""Runtime 运维健康检查响应模型（Pydantic）。"""

from __future__ import annotations

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


class RuntimeAfterMarketRun(BaseModel):
    """盘后一次运行的公开摘要。"""

    trading_day: str
    status: str
    attempts: int
    started_at: str
    finished_at: str
    products: list[str] = Field(default_factory=list)
    error_code: str | None = None


class RuntimeAfterMarketHealth(BaseModel):
    """由本地公开状态文件派生的盘后维护摘要。"""

    status: str
    configured_enabled: bool = False
    last_run: RuntimeAfterMarketRun | None = None
    last_successful_trading_day: str | None = None
    last_failure: dict[str, str] | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeHealthComponents(BaseModel):
    """各子组件健康快照的容器。"""

    db: RuntimeComponentHealth
    redis: RuntimeComponentHealth
    live_market: RuntimeLiveMarketHealth
    after_market: RuntimeAfterMarketHealth


class RuntimeHealthOut(BaseModel):
    """``/api/runtime/health`` 顶层响应；顶层 readonly 标志声明无写操作授权。"""

    status: str
    generated_at: str
    readonly: bool = True
    would_start_services: bool = False
    would_enqueue_jobs: bool = False
    would_send_notifications: bool = False
    components: RuntimeHealthComponents
