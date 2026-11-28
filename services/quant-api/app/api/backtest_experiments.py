"""Historical comparison and validation endpoints for the Backtest Center."""

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import ValidationError

from app.api.backtest_center import Writes, get_store
from app.backtest_center.contracts import BacktestError
from app.backtest_center.experiments import (
    ExperimentRequest,
    create_experiment,
    list_experiments,
    read_experiment,
)

router = APIRouter(prefix="/api/v1/backtests/experiments", tags=["backtest-center"])
ExperimentId = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]
ExperimentKind = Literal["comparison", "oos", "walk_forward"]


def _read(store, experiment_id):
    try:
        experiment = read_experiment(store, experiment_id)
    except sqlite3.Error:
        raise HTTPException(503, detail={"code": "EXPERIMENT_STORE_UNAVAILABLE"}) from None
    if experiment is None:
        raise HTTPException(404, detail={"code": "EXPERIMENT_NOT_FOUND"})
    return experiment


@router.get("")
def experiments(
    store=Depends(get_store),
    *,
    kind: ExperimentKind | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
):
    try:
        return list_experiments(store, kind=kind, limit=limit, offset=offset)
    except sqlite3.Error:
        raise HTTPException(503, detail={"code": "EXPERIMENT_STORE_UNAVAILABLE"}) from None


@router.post("", status_code=202, dependencies=Writes)
def submit_experiment(request: ExperimentRequest, store=Depends(get_store)):
    try:
        return create_experiment(store, request)
    except BacktestError as exc:
        status = {
            "EXPERIMENT_REQUEST_KEY_CONFLICT": 409,
            "EXPERIMENT_QUEUE_FULL": 429,
        }.get(exc.code, 422)
        raise HTTPException(status, detail={"code": exc.code}) from None
    except ValidationError:
        raise HTTPException(422, detail={"code": "EXPERIMENT_FOLD_CONFIG_INVALID"}) from None
    except sqlite3.Error:
        raise HTTPException(503, detail={"code": "EXPERIMENT_SUBMIT_UNKNOWN"}) from None


@router.get("/{experiment_id}")
def experiment(experiment_id: ExperimentId, store=Depends(get_store)):
    return _read(store, experiment_id)


@router.get("/{experiment_id}/evidence")
def evidence(experiment_id: ExperimentId, store=Depends(get_store)):
    data = _read(store, experiment_id)["evidence"]
    if data is None:
        raise HTTPException(409, detail={"code": "EXPERIMENT_EVIDENCE_UNAVAILABLE"})
    return data
