"""Таблица магазинов акции фонда → нормализованные магазины и слоты."""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

import pandas as pd

from .schedule import parse_schedule

COLS = {"city": "Город", "address": "Адрес", "chain": "ТС", "schedule": "Дата проведения"}


def store_id(address: str) -> str:
    """Стабильный ID магазина по нормализованному адресу."""
    norm = re.sub(r"\s+", " ", address.lower()).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


def region_of(address: str) -> str:
    """Регион из адреса фонда: «655017, Хакасия респ., Абакан г., …» → «Хакасия респ.»."""
    parts = [p.strip() for p in address.split(",")]
    if parts and re.fullmatch(r"\d{6}", parts[0]):
        parts = parts[1:]
    return parts[0] if parts else ""


def load_table(path: str | Path, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Прочитать CSV фонда. Возвращает (магазины, слоты)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in COLS.values() if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"В таблице нет колонок: {', '.join(missing)}")

    stores, slots = [], []
    for r in rows:
        address = r[COLS["address"]].strip()
        sid = store_id(address)
        parsed = parse_schedule(r[COLS["schedule"]])
        stores.append({
            "store_id": sid,
            "city": r[COLS["city"]].strip(),
            "region": region_of(address),
            "address": address,
            "chain": r[COLS["chain"]].strip(),
            "schedule_raw": r[COLS["schedule"]].strip(),
            "schedule_ok": bool(parsed),
            "time_assumed": any(s.time_assumed for s in parsed),
        })
        for s in parsed:
            slots.append({
                "store_id": sid,
                "date": f"{year:04d}-{s.month:02d}-{s.day:02d}",
                "start": s.start,
                "end": s.end,
                "time_assumed": s.time_assumed,
            })
    st = pd.DataFrame(stores).drop_duplicates("store_id")
    city_size = st.groupby("city")["store_id"].transform("count")
    st["city_stores"] = city_size  # число магазинов акции в городе — грубая замена размера города
    return st.reset_index(drop=True), pd.DataFrame(slots)
