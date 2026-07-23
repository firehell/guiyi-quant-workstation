"""同步 RQData 主力日线 baseline 样本（按品种）。

CLI 入口：选品种 → DominantDailyBaselineIngestor → commit。
默认起始日为 ``DEFAULT_MARKET_SAMPLE_START``（样本窗，非全历史）。
真实拉取逻辑在 ``app.services.rqdata_ingest.ingestors.DominantDailyBaselineIngestor``。
"""

from rqdata_sync_common import DEFAULT_MARKET_SAMPLE_START, PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import DominantDailyBaselineIngestor


def main() -> None:
    parser = base_parser("Sync RQData dominant daily baseline samples")
    parser.run_parser.set_defaults(start_date=DEFAULT_MARKET_SAMPLE_START)  # type: ignore[attr-defined]
    args = parser.parse_args()
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()

        def run_product(product: str):
            result = DominantDailyBaselineIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=args.start_date,
                end_date=args.end_date,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_dominant_daily_baseline", products, run_product)


if __name__ == "__main__":
    main()
