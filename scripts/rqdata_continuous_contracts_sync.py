from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import ContinuousContractIngestor


DEFAULT_CONTINUOUS_TYPES = ["front_month", "next_month"]


def main() -> None:
    parser = base_parser("Sync RQData front/next month continuous futures maps")
    parser.run_parser.add_argument("--continuous-type", action="append", dest="continuous_types")  # type: ignore[attr-defined]
    args = parser.parse_args()
    continuous_types = args.continuous_types or DEFAULT_CONTINUOUS_TYPES
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()

        def run_product(product: str):
            result = ContinuousContractIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=args.start_date,
                end_date=args.end_date,
                continuous_types=continuous_types,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_continuous_contracts", products, run_product)


if __name__ == "__main__":
    main()
