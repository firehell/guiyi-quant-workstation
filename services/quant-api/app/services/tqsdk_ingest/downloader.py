from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from app.services.tqsdk_ingest.products import ProductSpec


def download_main_1m_csv(
    *,
    api: Any,
    spec: ProductSpec,
    start: date,
    end: date,
    output_path: Path,
    downloader_cls: type | None = None,
) -> Path:
    if downloader_cls is None:
        from tqsdk.tools import DataDownloader

        downloader_cls = DataDownloader
    output_path.parent.mkdir(parents=True, exist_ok=True)
    task = downloader_cls(
        api,
        symbol_list=spec.download_symbol,
        dur_sec=60,
        start_dt=start,
        end_dt=end,
        csv_file_name=str(output_path),
    )
    while not task.is_finished():
        api.wait_update()
    return output_path


def close_api(api: Any) -> None:
    with closing(api):
        pass
