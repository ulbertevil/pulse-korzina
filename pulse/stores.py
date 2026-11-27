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


_REGION_TAIL = re.compile(r"(край|обл\.?|область|респ\.?|республика|АО|округ)$", re.I)
_PLACE_TAIL = re.compile(r"\s(г|с|п|пгт|рп|сп|д|ст-ца|сл|х|аул|тер|кп|дп|нп|снт)\.?$", re.I)


def locality_of(city: str, address: str) -> str:
    """Населённый пункт для листа и бюджета смен.

    В колонке «Город» у части строк записан регион («Краснодарский край», «Нижегородская обл.»).
    Тогда пункт берётся из адреса: «…, Кущевский р-н, Кущевская ст-ца, …» → «Кущевская ст-ца».
    Колонку «Город» модель использует как есть (признак city_stores), её не трогаем.
    """
    city = city.strip()
    if not _REGION_TAIL.search(city):
        return city
    parts = [p.strip() for p in address.split(",")]
    for p in parts[1:]:
        if re.search(r"р-н|район|\bм\.?о\.?$|\bг\.?о\.?$|округ", p, re.I) or _REGION_TAIL.search(p):
            continue
        if _PLACE_TAIL.search(p):
            return p
    return city


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
            "locality": locality_of(r[COLS["city"]], address),
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
    # «Нижний Новгород г.» из адреса и «Нижний Новгород г» из колонки — один пункт: берём написание из колонки
    norm = lambda x: re.sub(r"[.\s]+", " ", x.lower()).strip()  # noqa: E731
    spelled = {norm(c): c for c in st["city"][::-1]}
    st["locality"] = [spelled.get(norm(x), x) for x in st["locality"]]
    city_size = st.groupby("city")["store_id"].transform("count")
    st["city_stores"] = city_size  # число магазинов акции в городе — грубая замена размера города
    return st.reset_index(drop=True), pd.DataFrame(slots)
