"""Task-local read-only acceptance harness; never a Runtime entrypoint."""
from pathlib import Path
import functools
import json
import logging
import os
import sys
import time
from dotenv import load_dotenv

ROOT = Path('/Volumes/扩展盘/guiyi-quant-workstation')
load_dotenv(ROOT / '.env')
os.environ.setdefault('GUIYI_CANONICAL_DATA_ROOT', str((ROOT / 'data/parquet/canonical').resolve()))
logging.disable(logging.CRITICAL)
from app.db.session import SessionLocal, get_db
from app.db.readonly import readonly_transaction
from app.market_data.newow.product_service import NewowProductService

trace = []
original = NewowProductService._query_admitted
@functools.wraps(original)
def measured(self, request, *args, **kwargs):
    start = time.monotonic()
    try:
        return original(self, request, *args, **kwargs)
    finally:
        trace.append({'section': str(request.section), 'start': start, 'end': time.monotonic(), 'pid': os.getpid()})
NewowProductService._query_admitted = measured

def readonly_db():
    with SessionLocal() as session, readonly_transaction(session):
        yield session

if sys.argv[1] == 'preview':
    from app.preview import create_preview_app
    app = create_preview_app(enabled=True, as_of='2026-09-08T07:00:00.000001Z')
    port = 8010
else:
    from app.main import app
    from starlette.responses import JSONResponse
    app.dependency_overrides[get_db] = readonly_db
    allowed = {'/health', '/api/v1/market/bars/page', '/api/v1/market/newow/strategy-detail'}
    @app.middleware('http')
    async def readonly_allowlist(request, call_next):
        if request.method != 'GET' or request.url.path not in allowed:
            return JSONResponse(status_code=403, content={'detail': {'code': 'ACCEPTANCE_ROUTE_FORBIDDEN'}})
        return await call_next(request)
    port = 8011

if __name__ == '__main__':
    import uvicorn
    try:
        uvicorn.run(app, host='127.0.0.1', port=port, workers=1, access_log=False, log_config=None)
    finally:
        Path(sys.argv[2]).write_text(json.dumps(trace))
