"""Подключить таблицу магазинов новой акции: скачать, проверить, записать data/next_action.json.

Так фонд обновляет сайт к новой акции без программиста: на GitHub во вкладке Actions
запускается «Новая акция», туда вставляется ссылка на Google-таблицу — этот скрипт
скачивает её, разбирает расписание и пишет отчёт о проверке, после чего сайт пересобирается.

Запуск вручную:
    python scripts/new_action.py --url "https://docs.google.com/spreadsheets/d/<id>/edit#gid=0"
    python scripts/new_action.py --file data/raw/stores-2026-11.csv --year 2026
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pulse.stores import load_table  # noqa: E402

CONFIG = ROOT / "data/next_action.json"
MIN_PARSED_SHARE = 0.9  # если расписание разобрано хуже — таблица, скорее всего, другого формата


def export_url(url: str) -> str:
    """Ссылка на Google-таблицу (любая: /edit, /view, с #gid=) → ссылка на выгрузку CSV."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        return url  # уже прямая ссылка на CSV
    gid = re.search(r"[#&?]gid=(\d+)", url)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv" + (f"&gid={gid.group(1)}" if gid else "")


def guess_year(path: Path, today: date) -> int:
    """В таблице фонда даты без года («19, 20 ноября»). Берём ближайший год, в котором акция ещё впереди или идёт."""
    _, slots = load_table(path, today.year)
    if slots.empty:
        return today.year
    last = max(date.fromisoformat(d) for d in slots["date"])
    return today.year if (today - last).days <= 31 else today.year + 1


def check(path: Path, year: int) -> dict:
    stores, slots = load_table(path, year)
    dates = sorted(slots["date"].unique().tolist()) if len(slots) else []
    bad = stores[~stores["schedule_ok"]]
    return {
        "action_id": dates[0][:7] if dates else None,
        "dates": dates,
        "stores": int(len(stores)),
        "slots": int(len(slots)),
        "cities": int(stores["city"].nunique()),
        "parsed_share": float(stores["schedule_ok"].mean()) if len(stores) else 0.0,
        "time_assumed": int(stores["time_assumed"].sum()),
        "unparsed": bad[["city", "address", "schedule_raw"]].head(30).to_dict(orient="records"),
    }


def summary_md(rep: dict, source: str) -> str:
    ok = rep["parsed_share"] >= MIN_PARSED_SHARE and rep["dates"]
    lines = [
        f"## {'✅ Таблица подключена' if ok else '❌ Таблица не подключена'}",
        "",
        f"- Источник: {source}",
        f"- Акция: {', '.join(rep['dates']) or 'даты не найдены'}",
        f"- Магазинов: {rep['stores']}, городов: {rep['cities']}, смен магазинов: {rep['slots']}",
        f"- Расписание разобрано у {rep['parsed_share']:.1%} магазинов"
        + (f"; у {rep['time_assumed']} часы не указаны — взяли 4 часа" if rep["time_assumed"] else ""),
    ]
    if rep["unparsed"]:
        lines += ["", "Не разобрано (проверьте запись даты и времени):", "",
                  "| Город | Адрес | Как записано |", "|---|---|---|"]
        lines += [f"| {r['city']} | {r['address']} | {r['schedule_raw']} |" for r in rep["unparsed"]]
    if not ok:
        lines += ["", f"Нужно, чтобы разбиралось не меньше {MIN_PARSED_SHARE:.0%} строк. Сайт не изменён."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="ссылка на Google-таблицу или CSV")
    src.add_argument("--file", help="локальный CSV")
    ap.add_argument("--year", type=int, help="год акции (по умолчанию — ближайший)")
    ap.add_argument("--config", default=str(CONFIG))
    a = ap.parse_args(argv)

    if a.url:
        tmp = ROOT / "data/raw/_download.csv"
        req = urllib.request.Request(export_url(a.url), headers={"User-Agent": "pulse-korzina"})
        with urllib.request.urlopen(req, timeout=60) as r:
            tmp.write_bytes(r.read())
        path, source = tmp, a.url
    else:
        path, source = Path(a.file), a.file

    year = a.year or guess_year(path, date.today())
    rep = check(path, year)
    md = summary_md(rep, source)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    if rep["parsed_share"] < MIN_PARSED_SHARE or not rep["dates"]:
        return 1

    final = ROOT / f"data/raw/stores-{rep['action_id']}.csv"
    if path.resolve() != final.resolve():
        final.write_bytes(path.read_bytes())
    if a.url:
        path.unlink(missing_ok=True)
    cfg = {"action_id": rep["action_id"], "dates": rep["dates"], "year": year,
           "table": str(final.relative_to(ROOT)), "source_url": source,
           "note": "Таблица магазинов акции; подключена scripts/new_action.py"}
    Path(a.config).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
