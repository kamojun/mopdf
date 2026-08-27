"""仮のアプリアイコンを生成する。

本アイコンが用意できたら assets/icon.png を差し替えて再実行すればよい。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICONSET = ASSETS / "icon.iconset"

BG_COLOR = (43, 108, 176)  # 落ち着いた青
FG_COLOR = (255, 255, 255)

ICONSET_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def render_base_icon(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = int(size * 0.08)
    radius = int(size * 0.22)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=BG_COLOR,
    )

    text = "mo"
    font_size = int(size * 0.42)
    font = None
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ):
        if Path(candidate).exists():
            try:
                font = ImageFont.truetype(candidate, font_size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pos = ((size - text_w) / 2 - bbox[0], (size - text_h) / 2 - bbox[1])
    draw.text(pos, text, fill=FG_COLOR, font=font)

    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    base = render_base_icon(1024)
    base.save(ASSETS / "icon.png")

    if sys.platform != "darwin":
        print("macOS以外では.icns変換をスキップしました（icon.pngのみ生成）")
        return

    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()

    for size in ICONSET_SIZES:
        base.resize((size, size), Image.LANCZOS).save(
            ICONSET / f"icon_{size}x{size}.png"
        )
        if size <= 512:
            base.resize((size * 2, size * 2), Image.LANCZOS).save(
                ICONSET / f"icon_{size}x{size}@2x.png"
            )

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ASSETS / "icon.icns")],
        check=True,
    )
    shutil.rmtree(ICONSET)
    print(f"generated {ASSETS / 'icon.png'} and {ASSETS / 'icon.icns'}")


if __name__ == "__main__":
    main()
