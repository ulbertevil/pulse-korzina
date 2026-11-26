"""Прогноз на 10–11 декабря зафиксирован до акции: файл не меняется, сборка его воспроизводит."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
FROZEN = json.loads((ROOT / "forecasts/2026-12-10.json").read_text(encoding="utf-8"))
CSV = ROOT / FROZEN["stores_csv"]


def test_frozen_file_is_unchanged():
    assert hashlib.sha256(CSV.read_bytes()).hexdigest() == FROZEN["stores_csv_sha256"]


def test_frozen_numbers_match_store_file():
    s = pd.read_csv(CSV, dtype={"store_id": str})
    assert len(s) == FROZEN["stores"]
    assert s["pred_kg"].sum() == pytest.approx(FROZEN["pred_kg"], abs=1)


def test_build_reproduces_frozen_forecast():
    """Пока не подключена новая таблица, сборка даёт тот же прогноз байт в байт."""
    nxt = json.loads((ROOT / "data/next_action.json").read_text(encoding="utf-8"))
    built = ROOT / f"reports/forecast_{FROZEN['action_id']}_stores.csv"
    if nxt.get("table") or nxt.get("action_id") != FROZEN["action_id"]:
        pytest.skip("подключена другая акция — сравнивать не с чем")
    if not built.exists():
        pytest.skip("нет сборки: python scripts/build.py")
    assert built.read_bytes() == CSV.read_bytes()
