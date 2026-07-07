from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.jm_v2_register import register_jm_v2_quality  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register JM v2 parquet quality metadata in DB and manifest.")
    parser.add_argument("--summary-path", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with SessionLocal() as session:
        result = register_jm_v2_quality(session=session, summary_path=args.summary_path, manifest_path=args.manifest_path)
        session.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
