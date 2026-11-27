"""Подключение таблицы новой акции без программиста (scripts/new_action.py)."""
import csv
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
])
def test_any_sheet_link_becomes_csv_export(url, want):
    assert na.export_url(url) == want


@pytest.mark.parametrize("url", ["https://example.org/table.csv", "http://docs.google.com/spreadsheets/d/AbC",
                                 "https://docs.google.com.evil.org/spreadsheets/d/AbC", "file:///etc/passwd"])
def test_only_google_sheets_links_are_accepted(url, tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with pytest.raises(na.Refused):
        na.export_url(url)
    cfg = tmp_path / "next.json"
    assert na.main(["--url", url, "--config", str(cfg)]) == 1
    assert not cfg.exists()


def test_year_is_the_nearest_action():
    assert na.guess_year(TABLE, date(2026, 11, 26)) == 2026   # акция идёт или недавно прошла
    assert na.guess_year(TABLE, date(2026, 12, 30)) == 2027   # ноябрь уже далеко позади — значит, следующий


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Папка вместо репозитория: скрипт пишет таблицу в <sandbox>/data/raw, а не в настоящий data/raw."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    (tmp_path / "data/raw").mkdir(parents=True)
    monkeypatch.setattr(na, "ROOT", tmp_path)
    return tmp_path


def december_table(tmp_path) -> Path:
    """Ноябрьская таблица, перенесённая на декабрь, с лишней колонкой, которую нельзя публиковать."""
    with TABLE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    p = tmp_path / "dec.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, [*rows[0], "Телефон координатора"])
        w.writeheader()
        w.writerows({**r, "Дата проведения": r["Дата проведения"].replace("ноября", "декабря"),
                     "Телефон координатора": "+7 900 000-00-00"} for r in rows)
    return p


def test_good_table_writes_config_and_only_needed_columns(sandbox):
    cfg = sandbox / "next.json"
    src = december_table(sandbox)
    assert na.main(["--file", str(src), "--year", "2026", "--today", "2026-12-01", "--config", str(cfg)]) == 0
    c = json.loads(cfg.read_text(encoding="utf-8"))
    assert c["action_id"] == "2026-12" and c["dates"][0] == "2026-12-19" and c["table"] == "data/raw/stores-2026-12.csv"
    saved = (sandbox / c["table"]).read_text(encoding="utf-8-sig")
    assert saved.splitlines()[0] == "Город,Адрес,ТС,Дата проведения"
    assert "Телефон" not in saved and "+7 900" not in saved


def test_dry_run_changes_nothing(sandbox):
    cfg = sandbox / "next.json"
    src = december_table(sandbox)
    assert na.main(["--file", str(src), "--year", "2026", "--today", "2026-12-01", "--config", str(cfg), "--dry-run"]) == 0
    assert not cfg.exists() and not list((sandbox / "data/raw").iterdir())


def test_past_action_is_rejected(sandbox, capsys):
    cfg = sandbox / "next.json"
    src = december_table(sandbox)
    assert na.main(["--file", str(src), "--year", "2026", "--today", "2026-12-25", "--config", str(cfg)]) == 1
    assert not cfg.exists() and "уже прошла" in capsys.readouterr().out


def test_history_file_is_never_overwritten(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    before = TABLE.read_bytes()
    cfg = tmp_path / "next.json"
    assert na.main(["--file", str(TABLE), "--year", "2026", "--today", "2026-11-01", "--config", str(cfg)]) == 1
    assert TABLE.read_bytes() == before and not cfg.exists()
    assert "история модели" in capsys.readouterr().out


def test_dates_spread_over_weeks_are_rejected(sandbox, capsys):
    bad = sandbox / "spread.csv"
    bad.write_text("Город,Адрес,ТС,Дата проведения\n"
                   "Казань г,\"Казань г., Ленина ул., 1\",Пятёрочка,1 декабря 15-19\n"
                   "Казань г,\"Казань г., Ленина ул., 2\",Пятёрочка,20 декабря 15-19\n", encoding="utf-8")
    cfg = sandbox / "next.json"
    assert na.main(["--file", str(bad), "--year", "2026", "--today", "2026-11-25", "--config", str(cfg)]) == 1
    assert "растянуты" in capsys.readouterr().out


def test_unreadable_table_is_rejected_and_nothing_changes(sandbox):
    bad = sandbox / "bad.csv"
    bad.write_text("Город,Адрес,ТС,Дата проведения\nКазань г,\"Казань г., Ленина ул., 1\",Пятёрочка,уточняется\n",
                   encoding="utf-8")
    cfg = sandbox / "next.json"
    assert na.main(["--file", str(bad), "--year", "2027", "--config", str(cfg)]) == 1
    assert not cfg.exists()


def test_table_without_needed_columns_gets_a_plain_message(sandbox, capsys):
    bad = sandbox / "cols.csv"
    bad.write_text("Город,Магазин\nКазань г,1\n", encoding="utf-8")
    assert na.main(["--file", str(bad), "--config", str(sandbox / "next.json")]) == 1
    assert "нет колонок" in capsys.readouterr().out
