"""Repository-level hygiene contracts for the converged develop baseline."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEWOW_DOSSIER = ROOT / "docs/research/newow-v3.2.82"
NEWOW_REPLICATION_MANUAL = NEWOW_DOSSIER / "REPLICATION_MANUAL.md"
NEWOW_REPLICATION_BUILDER = ROOT / "scripts/docs/build_newow_replication_manual.py"
DISTRIBUTION_STATUS_LINE = "DISTRIBUTION_STATUS = DISTRIBUTION_APPROVED_BY_OWNER"
SCREENSHOT_POLICY_LINE = "NEWOW_SCREENSHOT_POLICY = RETAIN"

# Owner approval is bound to these exact repository paths and file contents.
# The manifest paths preserve the layout of the complete local evidence package;
# the two context screenshots were copied into a context/ subdirectory here.
APPROVED_SCREENSHOTS: dict[str, tuple[str, str]] = {
    "docs/research/newow-v3.2.82/screenshots/000001-SH-60min-trend.png": (
        "screenshots/000001-SH-60min-trend.png",
        "167d4aaa6d9824c81edc42d4cf55fcf52b2ad14f358f7fc219ce0e0a46f92c89",
    ),
    "docs/research/newow-v3.2.82/screenshots/000001-SH-day-trend.png": (
        "screenshots/000001-SH-day-trend.png",
        "7b62da013c15a7638cc9aed0565587923027cd2546118d20b27803d45f8dad18",
    ),
    "docs/research/newow-v3.2.82/screenshots/000001-SH-week-trend.png": (
        "screenshots/000001-SH-week-trend.png",
        "cab8420267fb2c64bac3ebc9c12bb3d2c352cb9052597d35b207c159ee1ea4ab",
    ),
    "docs/research/newow-v3.2.82/screenshots/000651-SZ-60min-trend.png": (
        "screenshots/000651-SZ-60min-trend.png",
        "1266e0a7320894c11ac72c8a9aadbd176966fe6ef64cf24c6778cbfe69d83191",
    ),
    "docs/research/newow-v3.2.82/screenshots/000651-SZ-day-trend.png": (
        "screenshots/000651-SZ-day-trend.png",
        "1aa5167cd0976d3220f6a993a05e717c3cffc8f8d34d7f3148ed0baf1de2b272",
    ),
    "docs/research/newow-v3.2.82/screenshots/000651-SZ-week-trend.png": (
        "screenshots/000651-SZ-week-trend.png",
        "46606c29696a7c015d4a79dbacda4b04e6f5e4ea560a161d320e6de65978fb04",
    ),
    "docs/research/newow-v3.2.82/screenshots/002594-SZ-60min-trend.png": (
        "screenshots/002594-SZ-60min-trend.png",
        "2dd5bcd429a2ecbcf665b932967121d53e92c944801d5847c2e59f63465e2aad",
    ),
    "docs/research/newow-v3.2.82/screenshots/002594-SZ-day-trend.png": (
        "screenshots/002594-SZ-day-trend.png",
        "b6a00eb3165c6e6a921ee8ea7be9594274cd5427595a79fcd694d9b2ab57ca88",
    ),
    "docs/research/newow-v3.2.82/screenshots/002594-SZ-week-trend.png": (
        "screenshots/002594-SZ-week-trend.png",
        "4e7a0ee935f37e13f34c9c4d57c97c31ea10c2c932716aef7ae43d4072dcf578",
    ),
    "docs/research/newow-v3.2.82/screenshots/300750-SZ-60min-trend.png": (
        "screenshots/300750-SZ-60min-trend.png",
        "13f9b1a6b8f9e599a70761850c560562dd76add214f73a843cb5aa2618d08543",
    ),
    "docs/research/newow-v3.2.82/screenshots/300750-SZ-day-trend.png": (
        "screenshots/300750-SZ-day-trend.png",
        "43024f5e9f55885a53ae29a40927dea3aac79aa3f228cb682061fe44152ae074",
    ),
    "docs/research/newow-v3.2.82/screenshots/300750-SZ-week-trend.png": (
        "screenshots/300750-SZ-week-trend.png",
        "f55573ede695a21015e56708a2948c0b5f2d292e9a5d8852176abe8ca69c40aa",
    ),
    "docs/research/newow-v3.2.82/screenshots/399001-SZ-60min-trend.png": (
        "screenshots/399001-SZ-60min-trend.png",
        "3d65bf2b2356909cb905ca2995a6cb61e6c85d6a80eac5f6cc0f8e7f3625bcb4",
    ),
    "docs/research/newow-v3.2.82/screenshots/399001-SZ-day-trend.png": (
        "screenshots/399001-SZ-day-trend.png",
        "665c7005074ef21d1cbe1311556ca744d9868f25227019a7db66771f01c201d3",
    ),
    "docs/research/newow-v3.2.82/screenshots/399001-SZ-week-trend.png": (
        "screenshots/399001-SZ-week-trend.png",
        "5a7443770dbed8c053568c3988cbddb4979717328559c73a535241954cc85ccc",
    ),
    "docs/research/newow-v3.2.82/screenshots/399006-SZ-60min-trend.png": (
        "screenshots/399006-SZ-60min-trend.png",
        "ad17a09c69297db5f0c47adabdcbb29cd053d99e1884d0027a8d1dd737824a68",
    ),
    "docs/research/newow-v3.2.82/screenshots/399006-SZ-day-trend.png": (
        "screenshots/399006-SZ-day-trend.png",
        "7f13e20ab02c54e00a689b6c9d83f5ba750771be84ce190eb20ed79481261668",
    ),
    "docs/research/newow-v3.2.82/screenshots/399006-SZ-week-trend.png": (
        "screenshots/399006-SZ-week-trend.png",
        "99dcacfc4aae00278ae6b63f84a44f1784d6de73244405adbc9219857d593e8c",
    ),
    "docs/research/newow-v3.2.82/screenshots/600036-SH-60min-trend.png": (
        "screenshots/600036-SH-60min-trend.png",
        "4be404908f9615f6aa4a04324b4fb698aa91aea6dac013ee9dbc1a75c7603c65",
    ),
    "docs/research/newow-v3.2.82/screenshots/600036-SH-day-trend.png": (
        "screenshots/600036-SH-day-trend.png",
        "1ba20b7aff1077caaa99d0528553fc7d87050a960fd69b49ea681b2cc3f7c44d",
    ),
    "docs/research/newow-v3.2.82/screenshots/600036-SH-week-trend.png": (
        "screenshots/600036-SH-week-trend.png",
        "5252b31078e4b856af37ff269c870d2c8c56486265de0e34ef144fc6371873d3",
    ),
    "docs/research/newow-v3.2.82/screenshots/600519-SH-60min-trend.png": (
        "screenshots/600519-SH-60min-trend.png",
        "03881f7991c30184e90ef1851fdbd9be9f1758135cc0de767e3e87c547dfe5e5",
    ),
    "docs/research/newow-v3.2.82/screenshots/600519-SH-day-trend.png": (
        "screenshots/600519-SH-day-trend.png",
        "c208a44ae8078cb4662d8f81af3cbeea1e406a7010f03cc5c86c026b3cb94f80",
    ),
    "docs/research/newow-v3.2.82/screenshots/600519-SH-week-trend.png": (
        "screenshots/600519-SH-week-trend.png",
        "19bebe25d1759d022efb0752694455414a01c49b1a4e4fb2d709e98aa441841c",
    ),
    "docs/research/newow-v3.2.82/screenshots/601233-SH-60min-trend.png": (
        "screenshots/601233-SH-60min-trend.png",
        "c50999d62801887ae3aadc02a919ae4054dd70a1f52f9fa7f369b60aeca51ab6",
    ),
    "docs/research/newow-v3.2.82/screenshots/601233-SH-day-trend.png": (
        "screenshots/601233-SH-day-trend.png",
        "0ecf9fe628b85ce6ef4b32810127851446a1b48dff4ee55faebb097a0490d05d",
    ),
    "docs/research/newow-v3.2.82/screenshots/601233-SH-week-trend.png": (
        "screenshots/601233-SH-week-trend.png",
        "72b704bd9669af93c0b1b9f9d2d3483dac050ea872efbfc4c3bfba5ec2cb973f",
    ),
    "docs/research/newow-v3.2.82/screenshots/context/home-anonymous.png": (
        "home-anonymous.png",
        "8347b3b259e436945641a66dcef4a41f2b6159993a9c0bb8ad62880e83c4e33e",
    ),
    "docs/research/newow-v3.2.82/screenshots/context/stock-601233-trend-day.png": (
        "stock-601233-trend-day.png",
        "2d720e079bba1038de6931424ec058e8900ba9b50c5faa9b8020472dfb5a31d5",
    ),
}


def _tracked_paths(pathspec: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", pathspec],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def _assert_owner_distribution_contract(readme: str) -> None:
    lines = set(readme.splitlines())
    assert DISTRIBUTION_STATUS_LINE in lines
    assert SCREENSHOT_POLICY_LINE in lines
    assert "不构成法律意见" in readme


def _assert_approved_screenshot_inventory(
    tracked_paths: tuple[str, ...],
    manifest_sha256_by_path: Mapping[str, str],
    actual_sha256_by_path: Mapping[str, str],
) -> None:
    assert len(APPROVED_SCREENSHOTS) == 29
    assert set(tracked_paths) == set(APPROVED_SCREENSHOTS)

    for tracked_path, (manifest_path, approved_sha256) in APPROVED_SCREENSHOTS.items():
        assert manifest_sha256_by_path[manifest_path] == approved_sha256
        assert actual_sha256_by_path[tracked_path] == approved_sha256


def test_local_browser_capture_directory_is_not_tracked_and_is_ignored() -> None:
    assert _tracked_paths(".playwright-cli/**") == ()

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".playwright-cli/probe.json"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def test_noncanonical_superpowers_documents_are_not_tracked() -> None:
    assert _tracked_paths("docs/superpowers/**") == ()


def test_newow_screenshot_distribution_owner_decision_is_explicit() -> None:
    readme = (NEWOW_DOSSIER / "README.md").read_text(encoding="utf-8")
    _assert_owner_distribution_contract(readme)

    screenshots = _tracked_paths("docs/research/newow-v3.2.82/screenshots/**")
    manifest = json.loads(
        (NEWOW_DOSSIER / "evidence/full-local-evidence-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["schema_version"] == "newow-evidence-manifest-v2"
    manifest_sha256_by_path = {
        item["relative_path"]: item["sha256"] for item in manifest["files"]
    }
    actual_sha256_by_path = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in screenshots
    }
    _assert_approved_screenshot_inventory(
        screenshots,
        manifest_sha256_by_path,
        actual_sha256_by_path,
    )


def test_newow_replication_manual_uses_the_approved_screenshot_scope() -> None:
    manual = NEWOW_REPLICATION_MANUAL.read_text(encoding="utf-8")
    lines = set(manual.splitlines())

    assert DISTRIBUTION_STATUS_LINE in lines
    assert SCREENSHOT_POLICY_LINE in lines
    assert "docs/research/newow-v3.2.82/screenshots/**" in manual
    assert "原始 HTML、JavaScript、接口响应、逐 Bar 股票数据" in manual
    assert "RQData / Canonical 原始材料" in manual
    assert "仍应由仓库所有者确认授权" not in manual


def test_newow_replication_builder_uses_one_fail_closed_cjk_font() -> None:
    builder = NEWOW_REPLICATION_BUILDER.read_text(encoding="utf-8")

    assert 'FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")' in builder
    assert (
        'FONT_SHA256 = "f8fa4a63e2cf500e98e64d4c73260daaba049306cf85dec9e3729bc285b7d645"'
        in builder
    )
    assert "hashlib.sha256(FONT_PATH.read_bytes()).hexdigest()" in builder
    assert "if actual_sha256 != FONT_SHA256:" in builder
    assert 'TTFont("ManualCN", str(FONT_PATH))' in builder
    assert "candidates" not in builder
    assert '"Helvetica"' not in builder
