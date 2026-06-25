from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.manifest import CsvManifest  # noqa: E402
from app.services.tqsdk_ingest.client import create_tqsdk_api  # noqa: E402
from app.services.tqsdk_ingest.db import TqSdkIngestRecorder  # noqa: E402
from app.services.tqsdk_ingest.downloader import close_api, download_main_1m_csv  # noqa: E402
from app.services.tqsdk_ingest.products import selected_product_specs  # noqa: E402
from app.services.tqsdk_ingest.transformer import build_month_chunks, canonical_path, month_key, raw_path, transform_downloader_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download TqSdk main-continuous 1m bars by product/month")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--start-date", type=_parse_date)
    run.add_argument("--end-date", type=_parse_date)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--limit", type=int)
    args = parser.parse_args()

    end_date = args.end_date or date.today()
    start_date = args.start_date or (end_date - timedelta(days=365))
    if end_date < start_date:
        raise SystemExit("--end-date must be greater than or equal to --start-date")

    specs = selected_product_specs(args.products)
    chunks = [(spec, chunk) for spec in specs for chunk in build_month_chunks(start_date, end_date)]
    manifest = CsvManifest(PROJECT_ROOT / "data/manifests/tqsdk_bars_1m.csv")
    executed = 0
    for spec, chunk in chunks:
        if args.limit is not None and executed >= args.limit:
            break
        key = month_key(spec, chunk)
        if not manifest.should_run(key, resume=args.resume, retry_failed=args.retry_failed):
            print(f"skip {key}")
            continue
        if args.dry_run:
            print(f"dry-run {key} {spec.download_symbol} {chunk.start} {chunk.end}")
            executed += 1
            continue
        try:
            result = _run_chunk(spec=spec, chunk=chunk)
            manifest.mark(key, "success")
            print(f"success {key}: {result}")
        except Exception as exc:
            manifest.mark(key, "failed", _safe_error(exc))
            print(f"failed {key}: {_safe_error(exc)}")
            if not args.retry_failed:
                raise
        executed += 1


def _run_chunk(*, spec, chunk) -> str:
    data_root = PROJECT_ROOT / "data"
    tmp_csv = data_root / "tmp/tqsdk_downloads" / f"{spec.product}_{chunk.key_suffix}_1m.csv"
    api = None
    with SessionLocal() as session:
        recorder = TqSdkIngestRecorder(session=session, project_root=PROJECT_ROOT)
        task = recorder.start_task(spec=spec, chunk_start=chunk.start, chunk_end=chunk.end)
        try:
            api = create_tqsdk_api()
            download_main_1m_csv(api=api, spec=spec, start=chunk.start, end=chunk.end, output_path=tmp_csv)
            raw_frame, canonical_frame = transform_downloader_csv(tmp_csv, spec=spec, year=chunk.year, month=chunk.month)
            quality = recorder.record_chunk(
                task=task,
                spec=spec,
                year=chunk.year,
                month=chunk.month,
                chunk_start=chunk.start,
                chunk_end=chunk.end,
                raw_path=raw_path(data_root, spec, chunk.year, chunk.month),
                raw_frame=raw_frame,
                canonical_path=canonical_path(data_root, spec, chunk.year, chunk.month),
                canonical_frame=canonical_frame,
                source_csv=tmp_csv,
            )
            recorder.finish_task(task, status="success", row_count=len(canonical_frame))
            session.commit()
            return f"rows={len(canonical_frame)} quality={quality.status}"
        except Exception as exc:
            recorder.finish_task(task, status="failed", error=_safe_error(exc))
            session.commit()
            raise
        finally:
            if api is not None:
                close_api(api)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    return text if len(text) <= 500 else text[:497] + "..."


if __name__ == "__main__":
    main()

