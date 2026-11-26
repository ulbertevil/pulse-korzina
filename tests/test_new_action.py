"""Подключение таблицы новой акции без программиста (scripts/new_action.py)."""
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("new_action", ROOT / "scripts/new_action.py")
na = importlib.util.module_from_spec(spec)
spec.loader.exec_module(na)
TABLE = ROOT / "data/raw/stores-2026-11.csv"


@pytest.mark.parametrize("url, want", [
    ("https://docs.google.com/spreadsheets/d/AbC_1-x/edit#gid=0", "https://docs.google.com/spreadsheets/d/AbC_1-x/export?format=csv&gid=0"),
    ("https://docs.google.com/spreadsheets/d/AbC/edit?usp=sharing", "https://docs.google.com/spreadsheets/d/AbC/export?format=csv"),
    ("https://example.org/table.csv", "https://example.org/table.csv"),
])
def test_any_sheet_link_becomes_csv_export(url, want):
    assert na.export_url(url) == want


def test_year_is_the_nearest_action():
    assert na.guess_year(TABLE, date(2026, 11, 26)) == 2026   # акция идёт или недавно прошла
    assert na.guess_year(TABLE, date(2026, 12, 30)) == 2027   # ноябрь уже далеко позади — значит, следующий


def test_good_table_writes_config(tmp_path):
    cfg = tmp_path / "next.json"
    assert na.main(["--file", str(TABLE), "--year", "2026", "--config", str(cfg)]) == 0
    c = json.loads(cfg.read_text(encoding="utf-8"))
    assert c["action_id"] == "2026-11" and c["dates"][0] == "2026-11-19" and c["table"] == "data/raw/stores-2026-11.csv"


def test_unreadable_table_is_rejected_and_nothing_changes(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Город,Адрес,ТС,Дата проведения\nКазань г,\"Казань г., Ленина ул., 1\",Пятёрочка,уточняется\n",
                   encoding="utf-8")
    cfg = tmp_path / "next.json"
    assert na.main(["--file", str(bad), "--year", "2027", "--config", str(cfg)]) == 1
    assert not cfg.exists()
