from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RuntimeComponentHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeRqQueueHealth(BaseModel):
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
    name: str
    state: str | None = None
    queues: list[str] = Field(default_factory=list)


class RuntimeRqHealth(BaseModel):
    status: str
    queues: list[RuntimeRqQueueHealth] = Field(default_factory=list)
    worker_count: int = 0
    workers: list[RuntimeRqWorkerHealth] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


class RuntimeCheckpointRow(BaseModel):
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
    status: str
    enabled: bool = False
    freshness_seconds: int = 300
    stale: bool = False
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
    status: str
    enabled: bool = False
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


class RuntimeSchedulerHealth(BaseModel):
    status: str
    enabled: bool = False
    heartbeat_at: str | None = None
    heartbeat_age_seconds: int | None = None
    last_cycle_status: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeArchiveHealth(BaseModel):
    status: str
    enabled: bool = False
    latest_task_no: str | None = None
    latest_task_status: str | None = None
    latest_contract: str | None = None
    latest_finished_at: str | None = None
    latest_error_type: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class RuntimeHealthComponents(BaseModel):
    db: RuntimeComponentHealth
    redis: RuntimeComponentHealth
    rq: RuntimeRqHealth
    scheduler: RuntimeSchedulerHealth
    live_checkpoints: RuntimeLiveCheckpointsHealth
    archive: RuntimeArchiveHealth
    notification_retry: RuntimeNotificationRetryHealth


class RuntimeHealthOut(BaseModel):
    status: str
    generated_at: str
    readonly: bool = True
    would_start_services: bool = False
    would_enqueue_jobs: bool = False
    would_send_notifications: bool = False
    components: RuntimeHealthComponents
