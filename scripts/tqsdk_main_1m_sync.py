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
from app.services.tqsdk_ingest.client import create_tqsdk_api  # noqa: E402
from app.services.tqsdk_ingest.db import TqSdkIngestRecorder  # noqa: E402
from app.services.tqsdk_ingest.downloader import close_api, download_main_1m_csv  # noqa: E402
from app.services.tqsdk_ingest.manifest import TqSdkCsvManifest  # noqa: E402
from app.services.tqsdk_ingest.parquet import sha256_file  # noqa: E402
from app.services.tqsdk_ingest.products import selected_product_specs  # noqa: E402
from app.services.tqsdk_ingest.transformer import build_month_chunks, canonical_path, month_key, raw_path, transform_downloader_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download TqSdk main-continuous 1m bars")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--product", action="append", dest="product_items")
    run.add_argument("--products", nargs="+")
    run.add_argument("--start-date", type=_parse_date)
    run.add_argument("--end-date", type=_parse_date)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--limit", type=int)
    args = parser.parse_args()

    end_date = args.end_date or date.today()
    start_date = args.start_date or (end_date - timedelta(days=365))
    products = (args.product_items or []) + (args.products or [])
    manifest = TqSdkCsvManifest(PROJECT_ROOT / "data/manifests/tqsdk_main_1m_manifest.csv")
    executed = 0
    for spec in selected_product_specs(products or None):
        for chunk in build_month_chunks(start_date, end_date):
            if args.limit is not None and executed >= args.limit:
                return
            key = month_key(spec, chunk, data_type="main_continuous")
            if not manifest.should_run(key, resume=args.resume, retry_failed=args.retry_failed, force=args.force):
                print(f"skip {key}")
                continue
            if args.dry_run:
                print(f"dry-run {key} {spec.download_symbol} {chunk.start} {chunk.end}")
                executed += 1
                continue
            try:
                result = run_main_chunk(spec=spec, chunk=chunk)
                manifest.mark(key=key, status="success", **result)
                print(f"success {key}: rows={result['rows']}")
            except Exception as exc:
                manifest.mark(
                    key=key,
                    provider="tqsdk",
                    data_type="main_continuous",
                    product=spec.product,
                    exchange=spec.exchange,
                    source_symbol=spec.download_symbol,
                    period="1m",
                    chunk_start=chunk.start,
                    chunk_end=chunk.end,
                    status="failed",
                    error=_safe_error(exc),
                )
                print(f"failed {key}: {_safe_error(exc)}")
            executed += 1


def run_main_chunk(*, spec, chunk) -> dict[str, object]:
    data_root = PROJECT_ROOT / "data"
    tmp_csv = data_root / "tmp/tqsdk_downloads" / f"{spec.product}_{chunk.key_suffix}_main_1m.csv"
    api = None
    with SessionLocal() as session:
        recorder = TqSdkIngestRecorder(session=session, project_root=PROJECT_ROOT)
        task = recorder.start_task(spec=spec, chunk_start=chunk.start, chunk_end=chunk.end, data_type="main_continuous")
        try:
            api = create_tqsdk_api()
            download_main_1m_csv(api=api, spec=spec, start=chunk.start, end=chunk.end, output_path=tmp_csv)
            raw_frame, canonical_frame = transform_downloader_csv(tmp_csv, spec=spec, year=chunk.year, month=chunk.month, data_type="main_continuous")
            raw_file = raw_path(data_root, spec, chunk.year, chunk.month, data_type="main_continuous")
            canonical_file = canonical_path(data_root, spec, chunk.year, chunk.month, data_type="main_continuous")
            recorder.record_chunk(
                task=task,
                spec=spec,
                year=chunk.year,
                month=chunk.month,
                chunk_start=chunk.start,
                chunk_end=chunk.end,
                raw_path=raw_file,
                raw_frame=raw_frame,
                canonical_path=canonical_file,
                canonical_frame=canonical_frame,
                source_csv=tmp_csv,
                data_type="main_continuous",
            )
            recorder.finish_task(task, status="success", row_count=len(canonical_frame))
            session.commit()
            return {
                "provider": "tqsdk",
                "data_type": "main_continuous",
                "product": spec.product,
                "exchange": spec.exchange,
                "contract": spec.contract_code,
                "source_symbol": spec.download_symbol,
                "period": "1m",
                "chunk_start": chunk.start,
                "chunk_end": chunk.end,
                "raw_path": raw_file,
                "canonical_path": canonical_file,
                "rows": len(canonical_frame),
                "checksum": sha256_file(canonical_file),
            }
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
