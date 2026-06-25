from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import MainMappingIngestor


def main() -> None:
    parser = base_parser("Sync RQData dominant and secondary futures mappings")
    parser.run_parser.add_argument("--ranks", nargs="+", type=int, default=[1, 2])  # type: ignore[attr-defined]
    args = parser.parse_args()
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()

        def run_product(product: str):
            result = MainMappingIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=args.start_date,
                end_date=args.end_date,
                ranks=args.ranks,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_main_mapping", products, run_product)


if __name__ == "__main__":
    main()

