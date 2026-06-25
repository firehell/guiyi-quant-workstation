from datetime import date

from rqdata_sync_common import PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import ContractUniverseIngestor


def year_chunks(products: list[str], start_date, end_date) -> list[str]:
    keys = []
    for product in products:
        for year in range(start_date.year, end_date.year + 1):
            chunk_start = max(start_date, start_date.replace(year=year, month=1, day=1))
            chunk_end = min(end_date, end_date.replace(year=year, month=12, day=31))
            if chunk_start <= chunk_end:
                keys.append(f"{product}:{chunk_start.isoformat()}:{chunk_end.isoformat()}")
    return keys


def main() -> None:
    parser = base_parser("Sync RQData daily listed futures contracts")
    args = parser.parse_args()
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()
        keys = year_chunks(products, args.start_date, args.end_date)

        def run_key(key: str):
            product, chunk_start, chunk_end = key.split(":", 2)
            result = ContractUniverseIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=date.fromisoformat(chunk_start),
                end_date=date.fromisoformat(chunk_end),
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_contract_universe", keys, run_key)


if __name__ == "__main__":
    main()
