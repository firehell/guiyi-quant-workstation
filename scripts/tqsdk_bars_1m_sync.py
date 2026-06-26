"""Deprecated entrypoint: use scripts/tqsdk_main_1m_sync.py instead.

Historical progress for the old bars manifest lives in data/manifests/tqsdk_bars_1m.csv
(2026-06-26 trial run). New downloads must use data/manifests/tqsdk_main_1m_manifest.csv.
"""

from tqsdk_main_1m_sync import main


if __name__ == "__main__":
    print("note: tqsdk_bars_1m_sync.py delegates to tqsdk_main_1m_sync.py; "
          "progress is tracked in data/manifests/tqsdk_main_1m_manifest.csv")
    main()
