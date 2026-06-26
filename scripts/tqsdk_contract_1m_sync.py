from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.tqsdk_ingest.client import create_tqsdk_api  # noqa: E402
from app.services.tqsdk_ingest.db import TqSdkIngestRecorder  # noqa: E402
from app.services.tqsdk_ingest.downloader import close_api, download_1m_csv  # noqa: E402
from app.services.tqsdk_ingest.manifest import TqSdkCsvManifest  # noqa: E402
from app.services.tqsdk_ingest.products import product_spec  # noqa: E402
from app.services.tqsdk_ingest.transformer import build_month_chunks, canonical_path, month_key, raw_path, transform_downloader_csv  # noqa: E402
from app.services.tqsdk_ingest.parquet import sha256_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download TqSdk real-contract 1m bars from a CSV plan")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--plan", default="data/manifests/tqsdk_contract_1m_download_plan.csv")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--contract", action="append", dest="contracts")
    run.add_argument("--start-date", type=_parse_date)
    run.add_argument("--end-date", type=_parse_date)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--limit", type=int)
    args = parser.parse_args()

    plan_path = PROJECT_ROOT / args.plan
    plan = pd.read_csv(plan_path, dtype=str).fillna("")
    if args.products:
        allowed = {product_spec(item).product for item in args.products}
        plan = plan[plan["product"].isin(allowed)]
    if args.contracts:
        allowed_contracts = set(args.contracts)
        plan = plan[plan["contract_code"].isin(allowed_contracts) | plan["source_symbol"].isin(allowed_contracts)]

    manifest = TqSdkCsvManifest(PROJECT_ROOT / "data/manifests/tqsdk_contract_1m_manifest.csv")
    executed = 0
    for row in plan.to_dict("records"):
        spec = product_spec(str(row["product"]))
        source_symbol = str(row["source_symbol"] or row["contract_code"])
        contract_code = str(row["contract_code"] or source_symbol)
        start = args.start_date or date.fromisoformat(str(row["download_start"]))
        end = args.end_date or date.fromisoformat(str(row["download_end"]))
        for chunk in build_month_chunks(start, end):
            if args.limit is not None and executed >= args.limit:
                return
            key = month_key(spec, chunk, data_type="contract", contract_code=contract_code)
            if not manifest.should_run(key, resume=args.resume, retry_failed=args.retry_failed, force=args.force):
                print(f"skip {key}")
                continue
            if args.dry_run:
                print(f"dry-run {key} {source_symbol} {chunk.start} {chunk.end}")
                executed += 1
                continue
            try:
                result = _run_contract_chunk(spec=spec, source_symbol=source_symbol, contract_code=contract_code, chunk=chunk)
                manifest.mark(key=key, status="success", **result)
                print(f"success {key}: rows={result['rows']}")
            except Exception as exc:
                manifest.mark(
                    key=key,
                    provider="tqsdk",
                    data_type="contract",
                    product=spec.product,
                    exchange=spec.exchange,
                    contract=contract_code,
                    source_symbol=source_symbol,
                    period="1m",
                    chunk_start=chunk.start,
                    chunk_end=chunk.end,
                    status="failed",
                    error=_safe_error(exc),
                )
                print(f"failed {key}: {_safe_error(exc)}")
            executed += 1


def _run_contract_chunk(*, spec, source_symbol: str, contract_code: str, chunk) -> dict[str, object]:
    data_root = PROJECT_ROOT / "data"
    tmp_csv = data_root / "tmp/tqsdk_downloads" / f"{source_symbol}_{chunk.key_suffix}_contract_1m.csv"
    api = None
    with SessionLocal() as session:
        recorder = TqSdkIngestRecorder(session=session, project_root=PROJECT_ROOT)
        task = recorder.start_task(spec=spec, chunk_start=chunk.start, chunk_end=chunk.end, data_type="contract", contract_code=contract_code)
        try:
            api = create_tqsdk_api()
            download_1m_csv(api=api, source_symbol=source_symbol, start=chunk.start, end=chunk.end, output_path=tmp_csv)
            raw_frame, canonical_frame = transform_downloader_csv(
                tmp_csv,
                spec=spec,
                year=chunk.year,
                month=chunk.month,
                data_type="contract",
                source_symbol=source_symbol,
                contract_code=contract_code,
            )
            raw_file = raw_path(data_root, spec, chunk.year, chunk.month, data_type="contract", contract_code=contract_code)
            canonical_file = canonical_path(data_root, spec, chunk.year, chunk.month, data_type="contract", contract_code=contract_code)
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
                data_type="contract",
            )
            recorder.finish_task(task, status="success", row_count=len(canonical_frame))
            session.commit()
            return {
                "provider": "tqsdk",
                "data_type": "contract",
                "product": spec.product,
                "exchange": spec.exchange,
                "contract": contract_code,
                "source_symbol": source_symbol,
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
