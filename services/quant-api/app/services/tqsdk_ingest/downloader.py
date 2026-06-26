from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

def download_1m_csv(
    *,
    api: Any,
    source_symbol: str,
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
        symbol_list=source_symbol,
        dur_sec=60,
        start_dt=start,
        end_dt=end,
        csv_file_name=str(output_path),
    )
    while not task.is_finished():
        api.wait_update()
    return output_path


def download_main_1m_csv(**kwargs) -> Path:
    spec = kwargs.pop("spec")
    return download_1m_csv(source_symbol=spec.download_symbol, **kwargs)


def close_api(api: Any) -> None:
    with closing(api):
        pass
