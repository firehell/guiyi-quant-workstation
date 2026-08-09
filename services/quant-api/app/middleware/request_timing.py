"""请求耗时日志中间件。

按总耗时分级记录（debug / info / warning），用于识别慢 API；不修改响应体或状态码。
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """在请求完成后记录 method、path、status、耗时与响应字节数。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        total_ms = (time.perf_counter() - started) * 1000
        response_bytes = int(response.headers.get("content-length", "0") or 0)
        message = (
            f"request method={request.method} path={request.url.path} "
            f"status={response.status_code} total_ms={total_ms:.1f} response_bytes={response_bytes}"
        )
        # 慢请求分级：≥5s warning，≥1s info，其余 debug
        if total_ms >= 5000:
            logger.warning("slow request %s", message)
        elif total_ms >= 1000:
            logger.info("slow request %s", message)
        else:
            logger.debug(message)
        return response
