"""Скриншоты главных разделов и GIF-обзор для заявки: docs/screens/.

Сайт должен быть доступен по адресу BASE (по умолчанию — локальный сервер):
    python -m http.server 8765 --directory site &
    python scripts/screens.py [--base http://127.0.0.1:8765/]
Рисует headless Chrome; разделы снимаются по ссылкам ?shot=<раздел> (на странице остаётся только он).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/screens"

SHOTS = [  # файл, параметры ссылки, ширина окна, подпись в GIF, с какой высоты (px) начинать кадр GIF
    ("1-forecast", "shot=next", 1280, "Сколько соберём: прогноз по сети и по каждому магазину", 400),
    ("2-city", f"shot=city&city={quote('Казань')}", 1280, "Лист координатора города: магазины, часы, сколько людей", 150),
    ("3-upload", "shot=upload&demo=1", 1280, "Выгрузка фонда считается прямо в браузере", 150),
    ("4-reality", "shot=reality", 1280, "Проверка на реальности: где синтетике можно верить", 40),
    ("5-ab", "shot=ab", 1280, "Калькулятор эксперимента: хватит ли магазинов", 40),
    ("6-city-mobile", f"shot=city&city={quote('Калуга')}", 390, "С телефона", 0),
]


def chrome() -> str:
    c = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not c:
        sys.exit("нужен Chrome или Chromium")
    return c


def trim(path: Path, pad: int = 24) -> None:
    """Обрезать пустой фон снизу."""
    im = Image.open(path).convert("RGB")
    bg = im.getpixel((im.width - 2, im.height - 2))
    px = im.load()
    bottom = im.height - 1
    while bottom > 0 and all(px[x, bottom] == bg for x in range(0, im.width, 7)):
        bottom -= 1
    im.crop((0, 0, im.width, min(im.height, bottom + pad))).save(path, optimize=True)


def shoot(base: str, query: str, width: int, out: Path) -> None:
    scale = 2 if width < 600 else 1
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}",
                        f"--force-device-scale-factor={scale}", f"--window-size={width},3200",
                        "--virtual-time-budget=15000", f"--screenshot={out}", f"{base}?{query}"],
                       check=True, capture_output=True, timeout=180)
    trim(out)


def font(size: int):
    for p in ("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def gif(frames: list[tuple[Path, str, int]], out: Path, w: int = 960, h: int = 640, bar: int = 56) -> None:
    f = font(24)
    imgs = []
    for path, caption, y0 in frames:
        im = Image.open(path).convert("RGB")
        im = im.crop((0, y0, im.width, im.height))
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        im = im.crop((0, 0, w, h - bar))
        frame = Image.new("RGB", (w, h), (42, 120, 214))
        frame.paste(im, (0, bar))
        ImageDraw.Draw(frame).text((24, bar // 2), caption, font=f, fill="white", anchor="lm")
        imgs.append(frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=3200, loop=0, optimize=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765/")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    for name, query, width, caption, y0 in SHOTS:
        p = OUT / f"{name}.png"
        shoot(a.base, query, width, p)
        print(f"{p.relative_to(ROOT)}: {Image.open(p).size}")
        done.append((p, caption, y0))
    gif([d for d in done if "mobile" not in d[0].name], OUT / "walkthrough.gif")
    print(f"{(OUT / 'walkthrough.gif').relative_to(ROOT)}: {(OUT / 'walkthrough.gif').stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
