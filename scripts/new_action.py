"""Подключить таблицу магазинов новой акции: скачать, проверить, записать data/next_action.json.

Так фонд обновляет сайт к новой акции без программиста: на GitHub во вкладке Actions
запускается «Новая акция», туда вставляется ссылка на Google-таблицу — этот скрипт
скачивает её, разбирает расписание и пишет отчёт о проверке, после чего сайт пересобирается.

Запуск вручную:
    python scripts/new_action.py --url "https://docs.google.com/spreadsheets/d/<id>/edit#gid=0" --dry-run
    python scripts/new_action.py --file таблица.csv --year 2026

Защита: принимаются только ссылки на Google-таблицы; акция, которая уже прошла, не подключается;
файл истории не перезаписывается; в репозиторий сохраняются только четыре колонки, которые нужны
сайту (город, адрес, сеть, дата проведения), — остальное содержимое таблицы никуда не уходит.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pulse.stores import COLS, load_table  # noqa: E402

CONFIG = ROOT / "data/next_action.json"
HISTORY = ROOT / "data/raw/stores-2026-11.csv"  # таблица, на которой построена история; не трогаем
MIN_PARSED_SHARE = 0.9  # если расписание разобрано хуже — таблица, скорее всего, другого формата
MAX_SPAN_DAYS = 7  # акция идёт 2–4 дня; разброс больше недели — почти наверняка ошибка разбора дат
SHEET_RE = re.compile(r"^https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+")


class Refused(Exception):
    """Таблицу подключать нельзя; текст — для отчёта фонду."""


def export_url(url: str) -> str:
    """Ссылка на Google-таблицу (любая: /edit, /view, с #gid=) → ссылка на выгрузку CSV."""
    url = url.strip()
    if not SHEET_RE.match(url):
        raise Refused("Нужна ссылка на Google-таблицу вида https://docs.google.com/spreadsheets/d/…")
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    gid = re.search(r"[#&?]gid=(\d+)", url)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv" + (f"&gid={gid.group(1)}" if gid else "")


def guess_year(path: Path, today: date) -> int:
    """В таблице фонда даты без года («19, 20 ноября»). Берём ближайший год, в котором акция ещё впереди или идёт."""
    _, slots = load_table(path, today.year)
    if slots.empty:
        return today.year
    last = max(date.fromisoformat(d) for d in slots["date"])
    return today.year if (today - last).days <= 31 else today.year + 1


def known_ids() -> set[str]:
    if not HISTORY.exists():
        return set()
    st, _ = load_table(HISTORY, 2000)
    return set(st["store_id"])


def check(path: Path, year: int, today: date | None = None) -> dict:
    stores, slots = load_table(path, year)
    dates = sorted(slots["date"].unique().tolist()) if len(slots) else []
    bad = stores[~stores["schedule_ok"]]
    by_date = slots.groupby("date")["store_id"].nunique().to_dict() if len(slots) else {}
    problems = []
    if not dates:
        problems.append("в таблице не нашлось ни одной даты акции")
    elif (span := (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days) > MAX_SPAN_DAYS:
        problems.append(f"даты акции растянуты на {span + 1} дней ({dates[0]} … {dates[-1]}) — похоже на ошибку в записи дат")
    if today and dates and date.fromisoformat(dates[-1]) < today:
        problems.append(f"акция уже прошла (последний день {dates[-1]}); для неё нужен не прогноз, а план-факт")
    share = float(stores["schedule_ok"].mean()) if len(stores) else 0.0
    if share < MIN_PARSED_SHARE:
        problems.append(f"расписание разобрано только у {share:.0%} магазинов, нужно не меньше {MIN_PARSED_SHARE:.0%}")
    return {
        "action_id": dates[0][:7] if dates else None,
        "dates": dates,
        "by_date": {d: int(n) for d, n in by_date.items()},
        "stores": int(len(stores)),
        "known": int(stores["store_id"].isin(known_ids()).sum()),
        "slots": int(len(slots)),
        "cities": int(stores["city"].nunique()),
        "parsed_share": share,
        "time_assumed": int(stores["time_assumed"].sum()),
        "unparsed": bad[["city", "address", "schedule_raw"]].head(30).to_dict(orient="records"),
        "problems": problems,
    }


def slim_csv(path: Path) -> bytes:
    """Только четыре нужные колонки, UTF-8 с BOM — в публичный репозиторий не уходит остальная таблица."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLS.values())
    w.writerows([r[c] for c in COLS.values()] for r in rows)
    return out.getvalue().encode("utf-8-sig")


def summary_md(rep: dict, source: str, dry_run: bool = False) -> str:
    ok = not rep["problems"]
    head = "Проверка пройдена (пробный запуск, ничего не изменено)" if ok and dry_run else "Таблица подключена" if ok else "Таблица не подключена"
    lines = [f"## {'✅' if ok else '❌'} {head}", "", f"- Источник: {source}"]
    if rep["dates"]:
        lines.append("- Акция: " + ", ".join(f"{d} — {rep['by_date'].get(d, 0)} магазинов" for d in rep["dates"]))
    else:
        lines.append("- Акция: даты не найдены")
    lines += [
        f"- Магазинов: {rep['stores']} (из них были в прошлой акции: {rep['known']}), городов: {rep['cities']}, "
        f"смен магазинов: {rep['slots']}",
        f"- Расписание разобрано у {rep['parsed_share']:.1%} магазинов"
        + (f"; у {rep['time_assumed']} часы не указаны — взяли 15:00–19:00" if rep["time_assumed"] else ""),
    ]
    if rep["problems"]:
        lines += ["", "**Почему не подключили:**", ""] + [f"- {p}" for p in rep["problems"]]
    if rep["unparsed"]:
        lines += ["", "Не разобрано (проверьте запись даты и времени):", "",
                  "| Город | Адрес | Как записано |", "|---|---|---|"]
        lines += [f"| {r['city']} | {r['address']} | {r['schedule_raw']} |".replace("\n", " ") for r in rep["unparsed"]]
    if not ok:
        lines += ["", "Сайт не изменён."]
    return "\n".join(lines) + "\n"


def refused_md(reason: str, source: str) -> str:
    return f"## ❌ Таблица не подключена\n\n- Источник: {source}\n- {reason}\n\nСайт не изменён.\n"


def report(md: str) -> None:
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="ссылка на Google-таблицу")
    src.add_argument("--file", help="локальный CSV")
    ap.add_argument("--year", type=int, help="год акции (по умолчанию — ближайший)")
    ap.add_argument("--dry-run", action="store_true", help="только проверить и показать отчёт, ничего не записывать")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today(), help=argparse.SUPPRESS)  # для тестов
    ap.add_argument("--config", default=str(CONFIG))
    a = ap.parse_args(argv)
    source = a.url or a.file

    tmp = ROOT / "data/raw/_download.csv"
    try:
        if a.url:
            req = urllib.request.Request(export_url(a.url), headers={"User-Agent": "pulse-korzina"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
            except OSError as e:
                raise Refused(f"не удалось скачать таблицу ({e}); проверьте, что доступ открыт «всем, у кого есть ссылка»")
            if body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
                raise Refused("вместо таблицы пришла веб-страница — скорее всего, нет доступа по ссылке")
            tmp.write_bytes(body)
            path = tmp
        else:
            path = Path(a.file)
        year = a.year or guess_year(path, a.today)
        rep = check(path, year, a.today)
    except Refused as e:
        report(refused_md(str(e), source))
        tmp.unlink(missing_ok=True)
        return 1
    except (ValueError, KeyError, UnicodeDecodeError) as e:
        report(refused_md(f"таблицу не удалось прочитать: {e}", source))
        tmp.unlink(missing_ok=True)
        return 1

    final = ROOT / f"data/raw/stores-{rep['action_id']}.csv"
    if not rep["problems"] and final.resolve() == HISTORY.resolve():
        rep["problems"].append(f"файл {final.relative_to(ROOT)} — история модели, перезаписывать его нельзя")
    report(summary_md(rep, source, a.dry_run))
    if rep["problems"] or a.dry_run:
        tmp.unlink(missing_ok=True)
        return 1 if rep["problems"] else 0

    final.write_bytes(slim_csv(path))
    tmp.unlink(missing_ok=True)
    cfg = {"action_id": rep["action_id"], "dates": rep["dates"], "year": year,
           "table": str(final.relative_to(ROOT)), "source_url": source,
           "note": "Таблица магазинов акции; подключена scripts/new_action.py"}
    Path(a.config).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
