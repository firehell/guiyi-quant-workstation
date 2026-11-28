"""归一量化 FastAPI 应用入口。

当前挂载 Market 行情、Alert、快期模拟账户监控与 Runtime 运维只读 API。
存活探针（liveness）与详细运维健康检查分层：本模块提供轻量
`/health` 别名，完整组件状态见 `/api/runtime/health`。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse
import logging
import os

from app.api.simulation_center import router as simulation_center_router
from app.api.simulation_monitor import router as simulation_monitor_router
from app.api.alerts import router as alerts_router
from app.api.market import router as market_router
from app.api.market_newow import router as market_newow_router
from app.api.newow_backtests import router as newow_backtests_router
from app.api.backtest_center import router as backtest_center_router, workstation_lifespan
from app.api.backtest_experiments import router as backtest_experiments_router
from app.api.market_messages import router as market_messages_router
from app.api.market_subing_reference import router as market_subing_reference_router
from app.api.market_live import router as market_live_router
from app.api.runtime import router as runtime_router
from app.api.reference_trading import router as reference_trading_router
from app.api.subing_model import router as subing_model_router
from app.api.strategy_center import router as strategy_center_router
from app.api.subing_portfolio import router as subing_portfolio_router
from app.middleware.request_timing import RequestTimingMiddleware
from app.services.newow_reference_mode import market_reference_receipts_only
from app.market_data.market_foundation_scope import formal_tick_requested, require_formal_tick_socket
from app.version import APP_VERSION

logging.basicConfig(level=logging.INFO)

# 本地 Vite 开发服务器默认来源；生产环境通过 CORS_ORIGINS 追加
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def resolve_cors_origins() -> list[str]:
    """合并默认与 CORS_ORIGINS 环境变量中的跨域来源。

    环境变量格式为逗号分隔的 origin 列表；去重后返回，供 CORSMiddleware 使用。
    """
    extra = os.getenv("CORS_ORIGINS", "")
    origins = list(DEFAULT_CORS_ORIGINS)
    for item in extra.split(","):
        normalized = item.strip()
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


app = FastAPI(title="归一量化 API", version=APP_VERSION, lifespan=workstation_lifespan)


if formal_tick_requested():
    from app.api.market_live import MarketDisplayRuntime
    from app.db.session import SessionLocal, engine
    from app.market_data.composition import canonical_root, open_market_home_live_service, open_market_read_service
    from app.redis_connections import get_async_redis_connection

    async def verify_socket_binding(redis):
        await require_formal_tick_socket(redis, engine.url, canonical_root())

    app.state.market_display_runtime = MarketDisplayRuntime(
        open_market_read_service, get_async_redis_connection, open_market_home_live_service,
        verify_socket_binding,
    )
    app.state.market_foundation_reference_sessions = SessionLocal


app.add_middleware(RequestTimingMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)
# CORS：允许凭证、全部方法与请求头；来源由 resolve_cors_origins 白名单控制
app.add_middleware(
    CORSMiddleware,
    expose_headers=["ETag", "Server-Timing"],
    allow_origins=resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def isolate_legacy_newow_calculation(request, call_next):
    path = request.url.path.rstrip("/")
    prefix = "/api/v1/market/newow/"
    if (market_reference_receipts_only() and path.startswith(prefix)
            and path not in {prefix + "product-capabilities", prefix + "home-projection"}):
        return JSONResponse({"detail": {"code": "NEWOW_AFTER_MARKET_ONLY"}}, status_code=409)
    return await call_next(request)


# Market + Alert + Runtime 运维面
app.include_router(simulation_center_router)
app.include_router(simulation_monitor_router)
app.include_router(market_router)
app.include_router(market_newow_router)
app.include_router(newow_backtests_router)
app.include_router(backtest_center_router)
app.include_router(backtest_experiments_router)
app.include_router(market_messages_router)
app.include_router(market_subing_reference_router)
app.include_router(market_live_router)
app.include_router(alerts_router)
app.include_router(runtime_router)
app.include_router(reference_trading_router)
app.include_router(subing_model_router)
app.include_router(subing_portfolio_router)
app.include_router(strategy_center_router)


@app.get("/health")
@app.get("/api/health")
@app.get("/healthz")
def health_check():
    """存活探针（liveness）：多路径别名共享同一响应体。

    不探测 DB/Redis，仅声明进程可读；详细分层健康见 ``/api/runtime/health``。
    """
    return {
        "status": "ok",
        "service": "guiyi-quant-api",
        "version": APP_VERSION,
        "readonly": True,
    }
