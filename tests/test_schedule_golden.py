"""Эталон разбора расписания: все 13 записей ноябрьской таблицы фонда и форматы, которых в ней ещё не было.

Если в таблице появится новая запись, тест test_every_table_format_is_in_golden упадёт —
надо посмотреть глазами, как она разбирается, и добавить её сюда.
"""
import csv
from pathlib import Path

import pytest

from pulse.schedule import parse_schedule

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/stores-2026-11.csv"

E, L, M = (15, 19), (12, 16), (12, 20)  # частые окна: вечер будней, день выходного, длинный день

TABLE = {  # запись в таблице фонда → (день, начало, конец)
    "20 ноября с 16.00 до 20.00;\n21 ноября с 12.00 до 18.00": [(20, 16, 20), (21, 12, 18)],
    "19, 20 ноября 15-19.00": [(19, *E), (20, *E)],
    "20 ноября 15-19.00 \n21 ноября 12-16.00": [(20, *E), (21, *L)],
    "20 ноября 15-19.00, \n21 ноября 12-16.00": [(20, *E), (21, *L)],
    "20 ноября 15-19.00": [(20, *E)],
    "19, 20 ноября 15-19.00\n21 ноября 12-16.00": [(19, *E), (20, *E), (21, *L)],
    "20-22 ноября, 12-20.00": [(20, *M), (21, *M), (22, *M)],
    "19 ноября 15-19.00": [(19, *E)],
    "21 ноября 12-16.00": [(21, *L)],
    "20 ноября 12.00-16.00": [(20, *L)],
    "19-20 ноября 15-19.00\n21 ноября": [(19, *E), (20, *E), (21, *E)],
}
NO_TIME = {"20-21 ноября": [20, 21], "20, 21 ноября": [20, 21]}  # времени нет — окно по умолчанию с пометкой

NEW = {  # форматы, которых в ноябрьской таблице нет, но которые легко написать
    "20 ноября 15-19, 21 ноября 12-16": [(11, 20, *E), (11, 21, *L)],
    "20 ноября 15-19 и 21 ноября 12-16": [(11, 20, *E), (11, 21, *L)],
    "10 и 11 декабря 15-19.00": [(12, 10, *E), (12, 11, *E)],
    "10 и 11 декабря, 15:00-19:00": [(12, 10, *E), (12, 11, *E)],
    "20 ноября 15-19.00, 21-22 ноября 12-16": [(11, 20, *E), (11, 21, *L), (11, 22, *L)],
    "30 ноября 15-19, 1 декабря 12-16": [(11, 30, *E), (12, 1, *L)],
    "10 декабря с 15.30 до 19.30": [(12, 10, 15.5, 19.5)],
    "10–11 декабря 15–19": [(12, 10, *E), (12, 11, *E)],
}


@pytest.mark.parametrize("raw", list(TABLE))
def test_table_formats(raw):
    slots = parse_schedule(raw)
    assert [(s.day, s.start, s.end) for s in slots] == TABLE[raw]
    assert all(s.month == 11 and not s.time_assumed for s in slots)


@pytest.mark.parametrize("raw", list(NO_TIME))
def test_table_formats_without_time(raw):
    slots = parse_schedule(raw)
    assert [s.day for s in slots] == NO_TIME[raw]
    assert all(s.time_assumed for s in slots)


@pytest.mark.parametrize("raw", list(NEW))
def test_new_formats(raw):
    slots = parse_schedule(raw)
    assert [(s.month, s.day, s.start, s.end) for s in slots] == NEW[raw]
    assert not any(s.time_assumed for s in slots)


def test_every_table_format_is_in_golden():
    with RAW.open(encoding="utf-8") as f:
        seen = {r["Дата проведения"] for r in csv.DictReader(f)}
    assert seen == set(TABLE) | set(NO_TIME)
