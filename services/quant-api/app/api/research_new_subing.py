"""Read-only delivery of frozen New SuBing research packets."""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.new_subing_research.store import ResultStoreError, list_results, page_result, read_result

router = APIRouter(prefix="/api/v1/research/new-subing", tags=["new-subing-research"])
_RUN = re.compile(r"[0-9a-f]{64}\Z")


def _root() -> Path | None:
    value = os.getenv("GUIYI_NEW_SUBING_RESULTS_ROOT")
    return Path(value) if value else None


def _fail(exc: ResultStoreError) -> HTTPException:
    code = str(exc)
    if code == "RESULT_NOT_FOUND":
        return HTTPException(status_code=404, detail={"code": code})
    if code in {"RUN_ID_INVALID", "PAGE_INVALID", "CURSOR_INVALID"}:
        return HTTPException(status_code=422, detail={"code": code})
    return HTTPException(status_code=409, detail={"code": code})


def _read(run_id: str) -> dict:
    if not _RUN.fullmatch(run_id):
        raise HTTPException(status_code=422, detail={"code": "RUN_ID_INVALID"})
    root = _root()
    if root is None:
        raise HTTPException(status_code=404, detail={"code": "RESULT_NOT_FOUND"})
    try:
        return read_result(root, run_id)
    except ResultStoreError as exc:
        raise _fail(exc) from exc


@router.get("/profiles")
def profiles() -> dict:
    # Rule authority remains in the pure core; do not copy it into this API.
    from guiyi_quant.new_subing import profile_payload

    rules = profile_payload()
    return {"strategy_code": "new_subing_v1", "profiles": [
        {"profile_id": str(rules["profile_id"]), "product": product,
         "initial_cash": str(rules["initial_cash"]), "validation_status": "HISTORICAL_RESEARCH_ONLY", "rules": rules["rules"]}
        for product in ("AL", "RB", "TA")
    ], "case_parity": "PENDING", "oos_status": "NOT_PROVEN", "auto_order": False}


@router.get("/runs")
def runs() -> dict:
    root = _root()
    if root is None:
        return {"runs": []}
    try:
        return {"runs": list_results(root)}
    except ResultStoreError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    packet = _read(run_id)
    return {"metadata": packet["metadata"], "summary": packet["summary"], "diagnostics": packet["diagnostics"]}


def _page(run_id: str, kind: str, limit: int, cursor: str | None) -> dict:
    if not _RUN.fullmatch(run_id):
        raise HTTPException(status_code=422, detail={"code": "RUN_ID_INVALID"})
    root = _root()
    if root is None:
        raise HTTPException(status_code=404, detail={"code": "RESULT_NOT_FOUND"})
    try:
        return page_result(root, run_id, kind, limit=limit, cursor=cursor)
    except ResultStoreError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{run_id}/decisions")
def decisions(run_id: str, limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=512)) -> dict:
    return _page(run_id, "decisions", limit, cursor)


@router.get("/runs/{run_id}/trades")
def trades(run_id: str, limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=512)) -> dict:
    return _page(run_id, "trades", limit, cursor)


@router.get("/runs/{run_id}/equity")
def equity(run_id: str, limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=512)) -> dict:
    return _page(run_id, "equity", limit, cursor)
