#!/usr/bin/env python3
"""Post-compose thumbnail overlay text on Flow-generated base image (Layer 2)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/impact.ttf",
                "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
        )
    else:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _normalize_overlay_text(text: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9'\s]", "", text.upper()).strip()
    words = cleaned.split()
    if not words:
        return []
    if len(words) <= 4:
        return words
    return words[:4]


def compose_thumbnail(
    base_path: Path,
    overlay_text: str,
    dest: Path | None = None,
    *,
    accent_color: tuple[int, int, int] = (220, 38, 38),
    text_color: tuple[int, int, int] = (255, 255, 255),
    stroke_color: tuple[int, int, int] = (0, 0, 0),
) -> Path:
    """Burn 2-4 word overlay on left third; last word red accent."""
    dest = dest or base_path
    words = _normalize_overlay_text(overlay_text)
    if not words:
        raise ValueError("thumbnail_text is empty after normalization")

    img = Image.open(base_path).convert("RGBA")
    width, height = img.size
    draw = ImageDraw.Draw(img)

    # Dark scrim on left third for readability
    scrim = Image.new("RGBA", (width // 3 + 40, height), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    for x in range(scrim.width):
        alpha = int(140 * (1 - x / scrim.width))
        scrim_draw.line([(x, 0), (x, height)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, scrim)
    draw = ImageDraw.Draw(img)

    font_size = max(48, height // 8)
    font = _load_font(font_size, bold=True)
    stroke = max(3, font_size // 18)

    # Stack words vertically in left zone
    x_pad = int(width * 0.04)
    y_start = int(height * 0.22)
    line_gap = int(font_size * 0.15)

    y = y_start
    for i, word in enumerate(words):
        color = accent_color if i == len(words) - 1 else text_color
        bbox = draw.textbbox((0, 0), word, font=font, stroke_width=stroke)
        text_h = bbox[3] - bbox[1]
        draw.text(
            (x_pad, y),
            word,
            font=font,
            fill=color,
            stroke_width=stroke,
            stroke_fill=stroke_color,
        )
        y += text_h + line_gap

    out = img.convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, format="PNG", optimize=True)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose thumbnail text overlay")
    parser.add_argument("--base", type=Path, required=True, help="Base thumbnail PNG from VPS")
    parser.add_argument("--text", required=True, help="2-4 word overlay (from hook package)")
    parser.add_argument("--output", type=Path, default=None, help="Output path (default: overwrite base)")
    args = parser.parse_args()

    out = compose_thumbnail(args.base, args.text, args.output or args.base)
    print(f"Wrote composed thumbnail -> {out}")


if __name__ == "__main__":
    main()
