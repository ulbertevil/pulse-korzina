"""Картинка-превью для ссылки (Telegram, VK, Slack): site/og.png, 1200×630.

Цифры берутся из site/data/dashboard.json, рисует headless Chrome.
Запуск после scripts/build.py: python scripts/og_image.py
"""
from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
          "декабря"]


def nf(x: float, d: int = 0) -> str:
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def dates_label(ds: list[str]) -> str:
    a, b = ds[0], ds[-1]
    if a[:7] == b[:7]:
        return f"{int(a[8:])}–{int(b[8:])} {MONTHS[int(a[5:7]) - 1]}" if a != b else f"{int(a[8:])} {MONTHS[int(a[5:7]) - 1]}"
    return f"{int(a[8:])} {MONTHS[int(a[5:7]) - 1]} – {int(b[8:])} {MONTHS[int(b[5:7]) - 1]}"


def page(d: dict) -> str:
    k, m = d["kpi"], d["meta"]
    sets = round((k["kg_opt"] - k["kg_current"]) / 6 / 10) * 10
    stats = [
        (f"{nf(k['pred_kg'] / 1000, 0)} т", f"прогноз сбора на {dates_label(m['dates'])}"),
        (f"+{nf(sets)}", "наборов теми же волонтёрами, если поставить их, где нужнее"),
        (f"{nf(m['cities'])}", "городов: лист координатора — магазины, часы, сколько людей"),
    ]
    cards = "".join(f'<div class="stat"><b>{html.escape(v)}</b><span>{html.escape(t)}</span></div>' for v, t in stats)
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><style>
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ width: 1200px; height: 630px; }}
body {{ font-family: "Noto Sans", "Liberation Sans", sans-serif; background: #f9f9f7; color: #0b0b0b;
  padding: 64px 72px; display: flex; flex-direction: column; justify-content: space-between; }}
.top {{ display: flex; align-items: center; gap: 18px; color: #52514b; font-size: 26px; }}
.logo {{ width: 56px; height: 56px; }}
h1 {{ font-size: 76px; line-height: 1.05; letter-spacing: -1.5px; margin-top: 26px; }}
.lede {{ font-size: 30px; color: #3b3a36; margin-top: 18px; max-width: 980px; line-height: 1.3; }}
.stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }}
.stat {{ border-left: 4px solid #2a78d6; padding: 4px 0 4px 18px; }}
.stat b {{ display: block; font-size: 46px; line-height: 1.1; }}
.stat span {{ display: block; font-size: 21px; color: #52514b; line-height: 1.3; margin-top: 6px; }}
.foot {{ font-size: 19px; color: #6f6e67; }}
</style><body>
<div>
  <div class="top"><svg class="logo" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#2a78d6"/>
    <path d="M5 18h6l3-8 4 13 3-7h6" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    Фонд X5 «Выручаем» · акция «Корзина доброты»</div>
  <h1>Пульс «Корзины доброты»</h1>
  <p class="lede">Сколько соберём, куда поставить волонтёров и как проверить новую идею экспериментом</p>
</div>
<div class="stats">{cards}</div>
<p class="foot">Демо: магазины и часы — из таблицы фонда, килограммы — синтетика.</p>
</body></html>"""


def main() -> int:
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        print("нужен Chrome или Chromium", file=sys.stderr)
        return 1
    d = json.loads((ROOT / "site/data/dashboard.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "og.html"
        src.write_text(page(d), encoding="utf-8")
        out = ROOT / "site/og.png"
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--window-size=1200,630", f"--screenshot={out}", src.as_uri()],
                       check=True, capture_output=True, timeout=120)
    print(f"готово: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
