"""同步 RQData 连续合约复权因子（ex_factor）。

CLI 入口：选品种 → ExFactorIngestor → commit。
真实拉取逻辑在 ``app.services.rqdata_ingest.ingestors.ExFactorIngestor``。
支持 ``--dry-run`` 与 ``data/manifests/rqdata_ex_factor.csv`` 断点续跑。
"""

from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import ExFactorIngestor


def main() -> None:
    parser = base_parser("Sync RQData futures continuous adjustment factors")
    args = parser.parse_args()
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()

        def run_product(product: str):
            result = ExFactorIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=args.start_date,
                end_date=args.end_date,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_ex_factor", products, run_product)


if __name__ == "__main__":
    main()
