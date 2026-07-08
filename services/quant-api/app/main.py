from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.backtests import router as backtests_router
from app.api.backtests import watchlists_router
from app.api.data_center import compat_router, router as data_center_router
from app.api.futures_research import router as futures_research_router
from app.api.market import router as market_router
from app.api.reviews import router as reviews_router
from app.api.signals import router as signals_router
from app.websocket.backtests import router as backtest_ws_router
from app.websocket.signals import router as signal_ws_router

app = FastAPI(title="归一量化 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.get("/api/dashboard/summary")
def dashboard_summary():
    return {
        "data_status": "mock",
        "strategies": 3,
        "backtests": 0,
        "signals_today": 0,
        "risk_status": "research_only",
    }
