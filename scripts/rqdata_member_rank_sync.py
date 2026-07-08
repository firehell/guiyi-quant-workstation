from datetime import date

from rqdata_sync_common import PROJECT_ROOT, base_parser, products_from_file, rq_client, run_with_manifest, selected_products

from app.db.session import SessionLocal
from app.services.rqdata_ingest.ingestors import MemberRankIngestor

VALID_RANK_BY = frozenset({"volume", "long", "short"})


def year_chunk_keys(products: list[str], rank_by_values: list[str], start_date: date, end_date: date) -> list[str]:
    keys: list[str] = []
    for product in products:
        for rank_by in rank_by_values:
            for year in range(start_date.year, end_date.year + 1):
                chunk_start = max(start_date, date(year, 1, 1))
                chunk_end = min(end_date, date(year, 12, 31))
                if chunk_start <= chunk_end:
                    keys.append(f"{product}:{rank_by}:{year}")
    return keys


def main() -> None:
    parser = base_parser("Sync RQData futures member ranks by product")
    parser.run_parser.add_argument("--products-file", type=str)  # type: ignore[attr-defined]
    parser.run_parser.add_argument("--rank-by", action="append", dest="rank_by")  # type: ignore[attr-defined]
    args = parser.parse_args()
    rank_by_values = args.rank_by or ["volume"]
    invalid = [item for item in rank_by_values if item not in VALID_RANK_BY]
    if invalid:
        raise SystemExit(f"invalid rank_by values: {invalid}; allowed: {sorted(VALID_RANK_BY)}")

    with SessionLocal() as session:
        if args.products_file:
            products = products_from_file(args.products_file)
        else:
            products = selected_products(session, args.products, all_products=args.all_products)
        client = None if args.dry_run else rq_client()
        keys = year_chunk_keys(products, rank_by_values, args.start_date, args.end_date)

        def run_key(key: str) -> str:
            product, rank_by, year_str = key.split(":", 2)
            year = int(year_str)
            chunk_start = max(args.start_date, date(year, 1, 1))
            chunk_end = min(args.end_date, date(year, 12, 31))
            result = MemberRankIngestor(session=session, client=client, project_root=PROJECT_ROOT).run(
                products=[product],
                start_date=chunk_start,
                end_date=chunk_end,
                rank_by=rank_by,
            )
            session.commit()
            return f"rows={result.rows} files={result.files}"

        run_with_manifest(args, "rqdata_member_ranks", keys, run_key)


if __name__ == "__main__":
    main()
