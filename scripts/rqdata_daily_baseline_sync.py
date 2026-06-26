from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_contracts

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import DailyBaselineIngestor


def main() -> None:
    parser = base_parser("Sync RQData futures exchange daily baseline")
    args = parser.parse_args()
    with SessionLocal() as session:
        contracts = selected_contracts(session, args.contracts, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()

        def run_contract(contract: str):
            result = DailyBaselineIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                contracts=[contract],
                start_date=args.start_date,
                end_date=args.end_date,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_daily_baseline", contracts, run_contract)


if __name__ == "__main__":
    main()

