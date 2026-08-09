"""归一量化 FastAPI 应用入口。

当前仅挂载 Market 行情与 Runtime 运维只读 API；data_center HTTP、Signal/Review/Strategy
等已退役表面均未注册。存活探针（liveness）与详细运维健康检查分层：本模块提供轻量
`/health` 别名，完整组件状态见 `/api/runtime/health`。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

from app.api.market import router as market_router
from app.api.market_live import router as market_live_router
from app.api.runtime import router as runtime_router
from app.middleware.request_timing import RequestTimingMiddleware

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


app = FastAPI(title="归一量化 API", version="0.1.0")

app.add_middleware(RequestTimingMiddleware)
# CORS：允许凭证、全部方法与请求头；来源由 resolve_cors_origins 白名单控制
app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 仅 Market + Runtime 运维面；data_center HTTP 与 Signal/Review/Strategy 路由未挂载
app.include_router(market_router)
app.include_router(market_live_router)
app.include_router(runtime_router)


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
        "version": "0.1.0",
        "readonly": True,
    }
