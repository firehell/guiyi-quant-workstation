#!/usr/bin/env python3
"""Render the Newow replication manual Markdown as a fixed-page A4 PDF."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


PAGE_W, PAGE_H = A4
MARGIN_X = 48
BODY_TOP = PAGE_H - 142
BODY_BOTTOM = 48

INK = HexColor("#17203A")
MUTED = HexColor("#5D6478")
PURPLE = HexColor("#5A35D6")
PURPLE_DARK = HexColor("#24145E")
PURPLE_LIGHT = HexColor("#EEE9FF")
TEAL = HexColor("#11A7A3")
TEAL_LIGHT = HexColor("#E5F8F6")
YELLOW = HexColor("#F5C842")
BLUE = HexColor("#4E76E8")
ORANGE = HexColor("#F28C4B")
RED = HexColor("#D94A63")
PAPER = HexColor("#F7F7FB")
GRID = HexColor("#D8DAE5")


FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")
FONT_SHA256 = "f8fa4a63e2cf500e98e64d4c73260daaba049306cf85dec9e3729bc285b7d645"


def register_fonts() -> tuple[str, str]:
    if not FONT_PATH.is_file():
        raise RuntimeError(f"required locked font is missing: {FONT_PATH}")
    actual_sha256 = hashlib.sha256(FONT_PATH.read_bytes()).hexdigest()
    if actual_sha256 != FONT_SHA256:
        raise RuntimeError(
            f"locked font hash mismatch: expected {FONT_SHA256}, got {actual_sha256}"
        )
    pdfmetrics.registerFont(TTFont("ManualCN", str(FONT_PATH)))
    return "ManualCN", "ManualCN"


FONT, FONT_BOLD = register_fonts()


def clean_inline(text: str) -> str:
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    return text.replace("`", "")


def text_width(text: str, size: float, font: str = FONT) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def wrap_text(text: str, width: float, size: float, font: str = FONT) -> list[str]:
    text = clean_inline(text.strip())
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if current and text_width(trial, size, font) > width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def draw_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    size: float = 10.2,
    leading: float = 15.0,
    color=INK,
    font: str = FONT,
    prefix: str = "",
) -> float:
    lines = wrap_text(prefix + text, width, size, font)
    c.setFont(font, size)
    c.setFillColor(color)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def parse_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [clean_inline(cell.strip()) for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def draw_table(c: canvas.Canvas, rows: list[list[str]], x: float, y: float, width: float) -> float:
    if not rows:
        return y
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    weights = []
    for col in range(columns):
        max_len = max(len(row[col]) for row in normalized)
        weights.append(max(1.0, min(max_len, 24) / 8.0))
    total = sum(weights)
    widths = [width * weight / total for weight in weights]
    font_size = 7.3 if columns >= 5 else 8.2
    leading = font_size + 3.0
    row_heights: list[float] = []
    wrapped_rows: list[list[list[str]]] = []
    for row in normalized:
        wrapped = [wrap_text(cell, widths[i] - 10, font_size, FONT) or [""] for i, cell in enumerate(row)]
        wrapped_rows.append(wrapped)
        row_heights.append(max(21.0, max(len(cell) for cell in wrapped) * leading + 8))
    for row_index, (row, height) in enumerate(zip(wrapped_rows, row_heights, strict=True)):
        y -= height
        c.setFillColor(PURPLE if row_index == 0 else (white if row_index % 2 else PAPER))
        c.roundRect(x, y, width, height, 3 if row_index in (0, len(rows) - 1) else 0, fill=1, stroke=0)
        cell_x = x
        for col, cell_lines in enumerate(row):
            if col:
                c.setStrokeColor(GRID)
                c.line(cell_x, y, cell_x, y + height)
            c.setFont(FONT, font_size)
            c.setFillColor(white if row_index == 0 else INK)
            line_y = y + height - leading
            for cell_line in cell_lines:
                c.drawString(cell_x + 5, line_y, cell_line)
                line_y -= leading
            cell_x += widths[col]
    return y - 8


def draw_code(c: canvas.Canvas, lines: list[str], x: float, y: float, width: float) -> float:
    leading = 14
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(wrap_text(line, width - 24, 8.7, FONT) or [""])
    height = max(38, 18 + len(wrapped) * leading)
    y -= height
    c.setFillColor(PURPLE_DARK)
    c.roundRect(x, y, width, height, 8, fill=1, stroke=0)
    c.setFillColor(HexColor("#F0EDFF"))
    c.setFont(FONT, 8.7)
    line_y = y + height - 20
    for line in wrapped:
        c.drawString(x + 12, line_y, line)
        line_y -= leading
    return y - 8


def draw_image(c: canvas.Canvas, image_path: Path, x: float, y: float, width: float, max_height: float) -> float:
    with PILImage.open(image_path) as image:
        iw, ih = image.size
    scale = min(width / iw, max_height / ih)
    draw_w, draw_h = iw * scale, ih * scale
    y -= draw_h
    c.setFillColor(white)
    c.setStrokeColor(GRID)
    c.roundRect(x - 5, y - 5, width + 10, draw_h + 10, 8, fill=1, stroke=1)
    c.drawImage(ImageReader(str(image_path)), x + (width - draw_w) / 2, y, draw_w, draw_h, mask="auto")
    return y - 10


def draw_header_motif(c: canvas.Canvas, title: str, index: int) -> None:
    x0 = PAGE_W - 168
    y0 = PAGE_H - 119
    c.saveState()
    c.setLineWidth(2)
    if "趋势" in title:
        c.setStrokeColor(YELLOW)
        c.line(x0, y0 + 12, x0 + 115, y0 + 42)
        c.setStrokeColor(BLUE)
        c.line(x0, y0 + 38, x0 + 115, y0 + 9)
    elif "震荡" in title or "目标价" in title:
        c.setStrokeColor(TEAL)
        c.rect(x0, y0 + 8, 115, 38, fill=0, stroke=1)
        c.setStrokeColor(ORANGE)
        c.line(x0, y0 + 27, x0 + 115, y0 + 27)
    elif "主升浪" in title or "J 风险" in title:
        c.setStrokeColor(YELLOW)
        c.bezier(x0, y0 + 8, x0 + 35, y0 + 15, x0 + 58, y0 + 52, x0 + 115, y0 + 44)
        c.setStrokeColor(BLUE)
        c.bezier(x0, y0 + 14, x0 + 45, y0 + 20, x0 + 68, y0 + 43, x0 + 115, y0 + 36)
    elif "期货" in title or "SC2302" in title:
        colors = (PURPLE, TEAL, ORANGE)
        for row, color in enumerate(colors):
            c.setFillColor(color)
            c.roundRect(x0 + row * 9, y0 + 8 + row * 14, 92 - row * 8, 8, 4, fill=1, stroke=0)
    elif "OOS" in title:
        for row in range(3):
            for col in range(3):
                c.setFillColor((PURPLE, TEAL, ORANGE)[(row + col) % 3])
                c.roundRect(x0 + col * 29, y0 + 8 + row * 15, 22, 9, 3, fill=1, stroke=0)
    else:
        c.setStrokeColor(Color(1, 1, 1, alpha=0.45))
        c.circle(x0 + 28, y0 + 28, 20, fill=0, stroke=1)
        c.circle(x0 + 70, y0 + 28, 14, fill=0, stroke=1)
        c.circle(x0 + 101, y0 + 28, 8, fill=0, stroke=1)
    c.restoreState()


def draw_cover(c: canvas.Canvas, block: str) -> None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    heading = clean_inline(next(line for line in lines if line.startswith("#")).lstrip("# "))
    title = heading.split("｜", 1)[-1]
    title_lines = [title[:4], title[4:]] if len(title) > 4 else [title]
    version = next(line.removeprefix("版本：") for line in lines if line.startswith("版本："))
    positioning = next(line.removeprefix("定位：") for line in lines if line.startswith("定位："))
    boundary = next(line.removeprefix("边界：") for line in lines if line.startswith("边界："))
    c.setFillColor(PURPLE_DARK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(PURPLE)
    c.circle(PAGE_W - 45, PAGE_H - 70, 125, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.circle(PAGE_W - 85, 95, 72, fill=1, stroke=0)
    c.setFillColor(Color(1, 1, 1, alpha=0.08))
    for i in range(7):
        c.roundRect(48 + i * 21, 135 + i * 28, 190, 10, 5, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.roundRect(48, PAGE_H - 105, 116, 22, 11, fill=1, stroke=0)
    c.setFillColor(PURPLE_DARK)
    c.setFont(FONT_BOLD, 9)
    c.drawCentredString(106, PAGE_H - 98, "GUIYI QUANT RESEARCH")
    c.setFillColor(white)
    c.setFont(FONT_BOLD, 30)
    for offset, line in enumerate(title_lines):
        c.drawString(48, PAGE_H - 220 - offset * 40, line)
    c.setFillColor(HexColor("#CDC3FF"))
    c.setFont(FONT, 14)
    c.drawString(49, PAGE_H - 294, "从股票页面一致性到期货因果验证")
    c.setFillColor(white)
    c.setFont(FONT, 10)
    details = [
        version,
        positioning,
        "A4 visual edition",
    ]
    y = 174
    for line in details:
        c.drawString(48, y, line)
        y -= 20
    c.setFillColor(HexColor("#BEB5DD"))
    c.setFont(FONT, 8.5)
    c.drawString(48, 55, f"{boundary} · page-parity ≠ causal-research")


def draw_page(c: canvas.Canvas, block: str, index: int, total: int, source_dir: Path) -> None:
    lines = block.strip().splitlines()
    title_line = next((line for line in lines if line.startswith("#")), f"第 {index} 页")
    title = clean_inline(title_line.lstrip("# "))
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(PURPLE)
    c.rect(0, PAGE_H - 126, PAGE_W, 126, fill=1, stroke=0)
    c.setFillColor(Color(1, 1, 1, alpha=0.10))
    c.circle(22, PAGE_H - 18, 92, fill=1, stroke=0)
    c.setFillColor(YELLOW)
    c.setFont(FONT_BOLD, 9)
    c.drawString(MARGIN_X, PAGE_H - 38, f"NEWOW REPLICATION  ·  {index:02d}")
    c.setFillColor(white)
    c.setFont(FONT_BOLD, 20 if len(title) < 24 else 16)
    c.drawString(MARGIN_X, PAGE_H - 81, title)
    draw_header_motif(c, title, index)

    body_lines = [line for line in lines if line != title_line]
    y = BODY_TOP
    x = MARGIN_X
    width = PAGE_W - 2 * MARGIN_X
    i = 0
    paragraph: list[str] = []

    def flush_paragraph(y_value: float) -> float:
        if not paragraph:
            return y_value
        value = " ".join(item.strip() for item in paragraph)
        paragraph.clear()
        return draw_wrapped(c, value, x, y_value, width, size=9.7, leading=14.5) - 6

    while i < len(body_lines):
        line = body_lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            y = flush_paragraph(y)
            i += 1
            continue
        image_match = re.fullmatch(r"!\[([^]]*)]\(([^)]+)\)", stripped)
        if image_match:
            y = flush_paragraph(y)
            image_path = (source_dir / image_match.group(2)).resolve()
            available = max(100, y - BODY_BOTTOM - 28)
            y = draw_image(c, image_path, x, y, width, min(available, 390))
            i += 1
            continue
        if stripped.startswith("|"):
            y = flush_paragraph(y)
            table_lines = []
            while i < len(body_lines) and body_lines[i].strip().startswith("|"):
                table_lines.append(body_lines[i].strip())
                i += 1
            y = draw_table(c, parse_table(table_lines), x, y, width)
            continue
        if stripped.startswith("```"):
            y = flush_paragraph(y)
            code_lines = []
            i += 1
            while i < len(body_lines) and not body_lines[i].strip().startswith("```"):
                code_lines.append(body_lines[i].rstrip())
                i += 1
            i += 1
            y = draw_code(c, code_lines, x, y, width)
            continue
        if stripped.startswith(">"):
            y = flush_paragraph(y)
            quote = stripped.lstrip("> ")
            quote_lines = wrap_text(quote, width - 28, 8.8, FONT)
            height = 20 + len(quote_lines) * 13
            y -= height
            c.setFillColor(PURPLE_LIGHT)
            c.roundRect(x, y, width, height, 7, fill=1, stroke=0)
            c.setFillColor(PURPLE)
            c.rect(x, y, 5, height, fill=1, stroke=0)
            c.setFont(FONT, 8.8)
            c.setFillColor(INK)
            qy = y + height - 17
            for qline in quote_lines:
                c.drawString(x + 15, qy, qline)
                qy -= 13
            y -= 7
            i += 1
            continue
        bullet = re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped)
        if bullet:
            y = flush_paragraph(y)
            marker = "•" if bullet.group(1) in {"-", "*"} else bullet.group(1)
            y = draw_wrapped(c, bullet.group(2), x + 14, y, width - 14, size=9.4, leading=14, prefix=f"{marker} ") - 3
            i += 1
            continue
        paragraph.append(stripped)
        i += 1
    y = flush_paragraph(y)

    if y < BODY_BOTTOM - 2:
        raise RuntimeError(f"page {index} overflowed by {BODY_BOTTOM - y:.1f} pt: {title}")

    c.setStrokeColor(GRID)
    c.line(MARGIN_X, 35, PAGE_W - MARGIN_X, 35)
    c.setFillColor(MUTED)
    c.setFont(FONT, 7.5)
    c.drawString(MARGIN_X, 22, "归一量化 · 研究观察 · 非交易建议")
    c.drawRightString(PAGE_W - MARGIN_X, 22, f"{index:02d} / {total:02d}")


def add_gallery(c: canvas.Canvas, source_dir: Path) -> None:
    paths = [
        source_dir / "screenshots/000001-SH-week-trend.png",
        source_dir / "screenshots/600036-SH-day-trend.png",
        source_dir / "screenshots/601233-SH-60min-trend.png",
    ]
    thumb_w = 155
    y = 54
    for idx, path in enumerate(paths):
        with PILImage.open(path) as image:
            iw, ih = image.size
        scale = min(thumb_w / iw, 88 / ih)
        w, h = iw * scale, ih * scale
        x = 48 + idx * 166 + (thumb_w - w) / 2
        c.setFillColor(white)
        c.setStrokeColor(GRID)
        c.roundRect(45 + idx * 166, y - 4, thumb_w + 6, 96, 5, fill=1, stroke=1)
        c.drawImage(ImageReader(str(path)), x, y + (88 - h) / 2, w, h, mask="auto")


def build(source: Path, output: Path) -> int:
    blocks = [block.strip() for block in source.read_text(encoding="utf-8").split("<!-- PDF_PAGE -->")]
    if not 35 <= len(blocks) <= 45:
        raise RuntimeError(f"expected 35-45 pages, got {len(blocks)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=A4, pageCompression=1, invariant=1)
    heading = clean_inline(next(line for line in blocks[0].splitlines() if line.startswith("#")).lstrip("# "))
    c.setTitle(heading)
    c.setAuthor("归一量化")
    c.setSubject("Newow v3.2.82 public-evidence replication and futures migration")
    source_dir = source.parent
    for index, block in enumerate(blocks):
        if index == 0:
            draw_cover(c, block)
        else:
            draw_page(c, block, index, len(blocks) - 1, source_dir)
            if index == 4:
                add_gallery(c, source_dir)
        c.showPage()
    c.save()
    return len(blocks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = build(args.source.resolve(), args.output.resolve())
    print(f"created {args.output.resolve()} ({count} pages)")


if __name__ == "__main__":
    main()
