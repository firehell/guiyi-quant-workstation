"""Runtime 运维健康检查响应模型（Pydantic）。

与 ``build_runtime_health`` 输出结构一致；部分组件为真实探测（db/redis/rq），
其余为退役 stub（live_checkpoints、archive、after_market_scheduler、notification_retry）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RuntimeComponentHealth(BaseModel):
    """通用组件健康（DB、Redis 等单点探测）。"""

    status: str
    latency_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeRqQueueHealth(BaseModel):
    """单个 RQ 队列的积压与 registry 计数。"""

    name: str
    status: str
    queued_count: int = 0
    started_count: int = 0
    failed_count: int = 0
    deferred_count: int = 0
    scheduled_count: int = 0
    worker_present: bool = False
    error_type: str | None = None


class RuntimeRqWorkerHealth(BaseModel):
    """单个 RQ worker 及其监听队列列表。"""

    name: str
    state: str | None = None
    queues: list[str] = Field(default_factory=list)


class RuntimeRqHealth(BaseModel):
    """RQ 子系统聚合（队列列表 + worker 覆盖）。"""

    status: str
    queues: list[RuntimeRqQueueHealth] = Field(default_factory=list)
    worker_count: int = 0
    workers: list[RuntimeRqWorkerHealth] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


class RuntimeCheckpointRow(BaseModel):
    """（历史）Live checkpoint 行结构；退役组件仍保留 schema 以兼容响应形状。"""

    id: int
    provider: str
    instrument_symbol: str
    contract_code: str
    period: str
    source_mode: str
    status: str
    lag_seconds: int | None = None
    consecutive_error_count: int = 0
    last_success_at: str | None = None
    last_run_at: str | None = None
    last_bar_at: str | None = None
    last_error_type: str | None = None
    updated_at: str | None = None


class RuntimeLiveCheckpointsHealth(BaseModel):
    """盘中 Live checkpoint 健康（已退役 stub，status=disabled, retired=True）。"""

    status: str
    enabled: bool = False
    retired: bool = False
    freshness_seconds: int = 300
    stale: bool = False
    polling_expected: bool = False
    market_phase: str = "unknown"
    ingest_count: int = 0
    aggregation_count: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    latest_success_at: str | None = None
    latest_error: dict[str, Any] | None = None
    recent_ingest: list[RuntimeCheckpointRow] = Field(default_factory=list)
    recent_aggregation: list[RuntimeCheckpointRow] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


class RuntimeNotificationRetryHealth(BaseModel):
    """企业微信通知重试健康（已退役 stub）。"""

    status: str
    enabled: bool = False
    retired: bool = False
    channel: str = "enterprise_wechat"
    total_count: int = 0
    retry_pending_count: int = 0
    due_retry_count: int = 0
    failed_count: int = 0
    sent_count: int = 0
    skipped_count: int = 0
    pending_count: int = 0
    next_retry_at: str | None = None
    last_sent_at: str | None = None
    last_failed_at: str | None = None
    last_error_type_counts: dict[str, int] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


class RuntimeArchiveHealth(BaseModel):
    """盘后归档任务健康（已退役 stub）。"""

    status: str
    enabled: bool = False
    retired: bool = False
    latest_task_no: str | None = None
    latest_task_status: str | None = None
    latest_contract: str | None = None
    latest_finished_at: str | None = None
    latest_error_type: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeAfterMarketSchedulerHealth(BaseModel):
    """盘后调度器健康（已退役 stub）。"""

    status: str
    enabled: bool = False
    retired: bool = False
    last_successful_trading_day: str | None = None
    latest_completed_trading_day: str | None = None
    latest_eligible_trading_day: str | None = None
    archive_lag_trading_days: int | None = None
    current_task: str | None = None
    last_error_type: str | None = None
    last_error_at: str | None = None
    retry_count: int = 0
    scheduler_heartbeat: dict[str, Any] | None = None
    next_retry_at: str | None = None
    authorization_hash: str | None = None
    lock_status: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeHealthComponents(BaseModel):
    """各子组件健康快照的容器。"""

    db: RuntimeComponentHealth
    redis: RuntimeComponentHealth
    rq: RuntimeRqHealth
    live_checkpoints: RuntimeLiveCheckpointsHealth
    archive: RuntimeArchiveHealth
    after_market_scheduler: RuntimeAfterMarketSchedulerHealth
    notification_retry: RuntimeNotificationRetryHealth


class RuntimeHealthOut(BaseModel):
    """``/api/runtime/health`` 顶层响应；顶层 readonly 标志声明无写操作授权。"""

    status: str
    generated_at: str
    readonly: bool = True
    would_start_services: bool = False
    would_enqueue_jobs: bool = False
    would_send_notifications: bool = False
    components: RuntimeHealthComponents
