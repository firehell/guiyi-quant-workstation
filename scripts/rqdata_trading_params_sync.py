"""同步 RQData 期货交易参数（按合约）。

CLI 入口：选合约 → TradingParameterIngestor → commit。
真实拉取逻辑在 ``app.services.rqdata_ingest.ingestors.TradingParameterIngestor``。
支持 dry-run 与 ``data/manifests/rqdata_trading_parameters.csv`` 断点续跑。
"""

from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_contracts

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import TradingParameterIngestor


def main() -> None:
    parser = base_parser("Sync RQData futures trading parameters")
    args = parser.parse_args()
    with SessionLocal() as session:
        contracts = selected_contracts(session, args.contracts, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()

        def run_contract(contract: str):
            result = TradingParameterIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                contracts=[contract],
                start_date=args.start_date,
                end_date=args.end_date,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_trading_parameters", contracts, run_contract)


if __name__ == "__main__":
    main()
