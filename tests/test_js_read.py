"""Чтение выгрузки в браузере (site/model.js → readExport) на файлах, какие даёт русский Excel."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("CI") and shutil.which("node") is None:
    raise RuntimeError("в CI нужен Node.js")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")

JS = """
const M = require(process.argv[1]);
let s = ""; process.stdin.on("data", (c) => (s += c)).on("end", () => {
  const { records, report } = M.readExport(s);
  console.log(JSON.stringify({ report, records: records.map((r) => ({ ...r, date: new Date(r.date).toISOString().slice(0, 10) })) }));
});
"""


def read(text: str) -> dict:
    out = subprocess.run(["node", "-e", JS, str(ROOT / "site/model.js")], input=text, capture_output=True,
                         text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def test_excel_semicolon_and_decimal_comma():
    r = read("﻿Магазин;Дата;Собрано, кг;Город\r\nA1;10.12.2026;48,5;Казань г\r\nA2;10.12.2026;1 204,0;Казань г\r\n")
    assert r["report"]["delim"] == ";" and r["report"]["used"] == 2
    assert [x["kg"] for x in r["records"]] == [48.5, 1204.0]
    assert r["records"][0]["date"] == "2026-12-10" and r["records"][0]["city"] == "Казань г"


def test_hours_written_as_clock_time():
    r = read("магазин,дата,кг,начало,конец\nA1,2026-12-10,30,16:00,20:00\nA2,2026-12-10,30,15:30,19:00\n")
    assert [x["hours"] for x in r["records"]] == [4, 3.5]


def test_impossible_dates_are_skipped_with_reason():
    r = read("магазин,дата,кг\nA1,12/31/2026,30\nA2,31.02.2026,30\nA3,2026-13-01,30\nA4,01.12.2026,30\n")
    assert r["report"]["used"] == 1 and r["records"][0]["store"] == "A4"
    assert r["report"]["reasons"] == {"дата не распознана": 3}


def test_missing_columns_are_reported():
    r = read("магазин;вес\nA1;30\n")
    assert r["report"]["missing"] == ["date"]  # «вес» — синоним кг
    assert r["records"] == []


def test_bad_numbers_and_empty_store_are_skipped():
    r = read("магазин,дата,кг\n,2026-12-10,30\nA2,2026-12-10,нет\nA3,2026-12-10,-5\nA4,2026-12-10,7\n")
    assert r["report"]["used"] == 1
    assert r["report"]["reasons"] == {"нет магазина": 1, "кг не число": 2}
