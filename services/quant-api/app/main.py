from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

from app.api.backtests import router as backtests_router
from app.api.backtests import watchlists_router
from app.api.dashboard import router as dashboard_router
from app.api.data_center import compat_router, router as data_center_router
from app.api.futures_research import router as futures_research_router
from app.api.market import router as market_router
from app.api.reviews import router as reviews_router
from app.api.runtime import router as runtime_router
from app.api.signals import router as signals_router
from app.api.strategies import router as strategies_router
from app.websocket.backtests import router as backtest_ws_router
from app.websocket.signals import router as signal_ws_router
from app.middleware.request_timing import RequestTimingMiddleware

logging.basicConfig(level=logging.INFO)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def resolve_cors_origins() -> list[str]:
    extra = os.getenv("CORS_ORIGINS", "")
    origins = list(DEFAULT_CORS_ORIGINS)
    for item in extra.split(","):
        normalized = item.strip()
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


app = FastAPI(title="归一量化 API", version="0.1.0")

app.add_middleware(RequestTimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_center_router)
app.include_router(compat_router)
app.include_router(market_router)
app.include_router(futures_research_router)
app.include_router(backtests_router)
app.include_router(watchlists_router)
app.include_router(signals_router)
app.include_router(reviews_router)
app.include_router(dashboard_router)
app.include_router(strategies_router)
app.include_router(runtime_router)
app.include_router(backtest_ws_router)
app.include_router(signal_ws_router)

@app.get("/health")
@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "guiyi-quant-api",
        "version": "0.1.0",
    }


@app.get("/healthz")
def healthz_check():
    return {
        "status": "ok",
        "service": "local-workstation",
    }

