"""Разбор колонки «Дата проведения» из таблицы фонда.

В ноябрьской таблице 2026 года 11 форматов записи, например:
    "19, 20 ноября 15-19.00"
    "20 ноября с 16.00 до 20.00;\n21 ноября с 12.00 до 18.00"
    "19-21 ноября, 15-19.00"
Результат — список слотов (день, час начала, час конца). Если у части
записи нет времени, берётся время соседней части; если времени нет совсем,
ставится окно по умолчанию и слот помечается флагом `time_assumed`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
DEFAULT_WINDOW = (15.0, 19.0)  # самое частое окно в таблице, используется как допущение

_MONTH_RE = "|".join(MONTHS)
_SEP = r"(?:\s*[-–—,]\s*|\s+и\s+)"
_DAYS_RE = re.compile(rf"(?<![\d.:])(?P<days>\d{{1,2}}(?:{_SEP}\d{{1,2}})*)\s*(?P<month>{_MONTH_RE})")
_RANGE_RE = re.compile(r"\d{1,2}\s*[-–—]\s*\d{1,2}")
_TIME_RE = re.compile(
    r"(?:с\s*)?(?P<h1>\d{1,2})(?:[.:](?P<m1>\d{2}))?\s*(?:-|–|—|до)\s*(?P<h2>\d{1,2})(?:[.:](?P<m2>\d{2}))?"
)


@dataclass(frozen=True)
class Slot:
    month: int
    day: int
    start: float  # часы, 15.5 = 15:30
    end: float
    time_assumed: bool = False

    @property
    def hours(self) -> float:
        return self.end - self.start


def _expand_days(text: str) -> list[int]:
    days: list[int] = []
    for part in re.split(r"\s*,\s*|\s+и\s+", text.strip()):
        if re.search(r"[-–—]", part):
            a, b = (int(x) for x in re.split(r"\s*[-–—]\s*", part))
            days.extend(range(a, b + 1))
        elif part:
            days.append(int(part))
    return days


def _parse_time(text: str) -> tuple[float, float] | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    start = int(m["h1"]) + int(m["m1"] or 0) / 60
    end = int(m["h2"]) + int(m["m2"] or 0) / 60
    if not (0 <= start < end <= 24):
        return None
    return start, end


def parse_schedule(raw: str) -> list[Slot]:
    """Вернуть слоты акции. Пустой список — если дату разобрать не удалось."""
    text = raw.replace(" ", " ")
    matches = list(_DAYS_RE.finditer(text))
    if not matches:
        return []
    # «20 ноября 15-19, 21 ноября 12-16»: регулярка захватывает «15-19, 21» как дни второй части.
    # Если сразу после месяца идёт диапазон, а за ним через запятую ещё дни — диапазон это время предыдущей части.
    spans = []  # (начало дней, конец совпадения, текст дней, месяц)
    for i, m in enumerate(matches):
        start, days = m.start("days"), m["days"]
        if i and not text[matches[i - 1].end():start].strip(" ,"):
            cut = re.search(r"\s*,\s*|\s+и\s+", days)
            if cut and _RANGE_RE.fullmatch(days[:cut.start()]):
                start = m.start("days") + cut.end()
                days = days[cut.end():]
        spans.append((start, m.end(), days, MONTHS[m["month"]]))
    parts: list[tuple[list[int], int, tuple[float, float] | None]] = []
    for i, (_, end, days, month) in enumerate(spans):
        tail_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        parts.append((_expand_days(days), month, _parse_time(text[end:tail_end])))

    known = [t for _, _, t in parts if t]
    slots: list[Slot] = []
    for idx, (days, month, window) in enumerate(parts):
        assumed = False
        if window is None:
            # время соседней части: сначала предыдущей, потом следующей
            prev = next((parts[j][2] for j in range(idx - 1, -1, -1) if parts[j][2]), None)
            nxt = next((parts[j][2] for j in range(idx + 1, len(parts)) if parts[j][2]), None)
            window = prev or nxt
            if window is None:
                window, assumed = DEFAULT_WINDOW, True
        for d in days:
            slots.append(Slot(month, d, window[0], window[1], assumed or not known))
    return sorted(set(slots), key=lambda s: (s.month, s.day, s.start))
