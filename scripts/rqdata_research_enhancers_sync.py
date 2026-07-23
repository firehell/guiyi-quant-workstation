"""同步 RQData 研究增强字段：仓单、展期收益；可选基差。

CLI 入口：按品种（及可选合约）→ ResearchEnhancerIngestor → commit。
``--include-basis`` 时额外按合约同步基差；manifest key 为 ``product:`` / ``contract:`` 前缀。
真实拉取逻辑在 ``app.services.rqdata_ingest.ingestors.ResearchEnhancerIngestor``。
"""

from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_contracts, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import ResearchEnhancerIngestor


def main() -> None:
    parser = base_parser("Sync RQData warehouse stocks, roll yield, and basis")
    parser.run_parser.add_argument("--include-basis", action="store_true")  # type: ignore[attr-defined]
    args = parser.parse_args()
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        contracts = selected_contracts(session, args.contracts, args.products, all_products=args.all_products) if args.include_basis else []
        client = None if args.dry_run else rq_client()
        keys = [f"product:{product}" for product in products] + [f"contract:{contract}" for contract in contracts]

        def run_key(key: str):
            kind, value = key.split(":", 1)
            result = ResearchEnhancerIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[value] if kind == "product" else [],
                contracts=[value] if kind == "contract" else [],
                start_date=args.start_date,
                end_date=args.end_date,
                include_basis=args.include_basis,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_research_enhancers", keys, run_key)


if __name__ == "__main__":
    main()
