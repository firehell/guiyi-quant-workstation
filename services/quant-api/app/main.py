from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="归一量化 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "guiyi-quant-api",
        "version": "0.1.0",
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
