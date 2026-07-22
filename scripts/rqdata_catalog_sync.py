"""同步 RQData 期货品种目录、交易日历与交易时段。

CLI 入口：解析参数 → CatalogIngestor.run → commit。
真实拉取逻辑在 ``app.services.rqdata_ingest.ingestors.CatalogIngestor``。
``--dry-run`` 只打印范围，不创建 client、不写库。
"""

from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import CatalogIngestor


def main() -> None:
    parser = base_parser("Sync RQData futures catalog, calendar, and sessions")
    args = parser.parse_args()
    with SessionLocal() as session:
        if args.dry_run:
            print(f"dry-run catalog {args.start_date}..{args.end_date} products={args.products or 'all'}")
            return
        result = CatalogIngestor(session=session, client=rq_client(), project_root=PROJECT_ROOT).run(
            start_date=args.start_date,
            end_date=args.end_date,
            products=args.products,
        )
        session.commit()
        print(f"success catalog rows={result.rows} files={result.files}")


if __name__ == "__main__":
    main()
