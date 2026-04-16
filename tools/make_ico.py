from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


DEFAULT_SIZES: tuple[tuple[int, int], ...] = ((16, 16), (32, 32), (48, 48), (256, 256))


def build_ico(source_png: Path, output_ico: Path, sizes: tuple[tuple[int, int], ...]) -> None:
    img = Image.open(source_png).convert("RGBA")
    output_ico.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_ico, format="ICO", sizes=list(sizes))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert source PNG into a multi-size Windows .ico (16/32/48/256).")
    parser.add_argument("source", nargs="?", default="source.png", help="Path to source PNG (recommended 512x512).")
    parser.add_argument("output", nargs="?", default="assets/icon.ico", help="Output ICO path.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()

    if not source.exists():
        raise FileNotFoundError(f"Missing source image: {source}")

    build_ico(source, output, DEFAULT_SIZES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

