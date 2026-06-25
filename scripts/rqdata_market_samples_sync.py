from rqdata_sync_common import DEFAULT_MARKET_SAMPLE_START, PROJECT_ROOT, base_parser, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import MarketSampleIngestor


def main() -> None:
    parser = base_parser("Sync limited RQData market samples for cross-provider validation")
    parser.run_parser.set_defaults(start_date=DEFAULT_MARKET_SAMPLE_START)  # type: ignore[attr-defined]
    default_frequencies = ["1m", "5m", "15m", "30m", "60m"]
    parser.run_parser.add_argument("--frequency", action="append", dest="frequencies")  # type: ignore[attr-defined]
    args = parser.parse_args()
    frequencies = args.frequencies or default_frequencies
    client = None if args.dry_run else rq_client()
    with SessionLocal() as session:
        products = selected_products(session, args.products, all_products=args.all_products)
        keys = [f"{product}:{frequency}" for product in products for frequency in frequencies]

        def run_key(key: str):
            product, frequency = key.split(":", 1)
            result = MarketSampleIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=args.start_date,
                end_date=args.end_date,
                frequencies=[frequency],
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_market_samples", keys, run_key)


if __name__ == "__main__":
    main()
