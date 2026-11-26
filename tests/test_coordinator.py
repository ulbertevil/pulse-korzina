"""Лист координатора: те же слоты и люди, что в расстановке, тара не меньше ожидаемого."""
import pandas as pd
import pytest

from pulse import site_export


def toy():
    alloc = pd.DataFrame({
        "store_id": ["a", "a", "b"], "date": ["2026-12-11", "2026-12-10", "2026-12-10"],
        "start": [12, 16, 15], "end": [18, 20, 19], "city": ["X г.", "X г.", "X г."], "chain": ["Пятёрочка"] * 3,
        "address": ["400000, Обл., X г., Ленина ул., Дом 1", "400000, Обл., X г., Ленина ул., Дом 1",
                    "400000, Обл., X г., Мира ул., Дом 2"],
        "v_current": [2, 1, 0], "v_opt": [1, 2, 0], "kg_current": [30.0, 20.0, 10.0], "kg_opt": [28.0, 25.0, 10.0]})
    per_store = pd.DataFrame({"store_id": ["a", "b"], "pred_kg": [50.0, 10.0], "hi80": [90.0, 18.0]})
    return alloc, per_store


def test_rows_keep_people_and_sort_by_day_and_hour():
    alloc, per_store = toy()
    c = site_export.coordinator(alloc, per_store)
    rows = [dict(zip(c["fields"], r)) for r in c["rows"]]
    assert c["synthetic"] is True
    assert sum(r["v_opt"] for r in rows) == alloc["v_opt"].sum()
    assert sum(r["v_current"] for r in rows) == alloc["v_current"].sum()
    assert [(r["date"], r["start"]) for r in rows] == sorted((r["date"], r["start"]) for r in rows)
    assert rows[0]["address"] == "Мира ул., 2"


def test_container_bound_scales_with_store_interval():
    alloc, per_store = toy()
    rows = [dict(zip(site_export.COORD_FIELDS, r)) for r in site_export.coordinator(alloc, per_store)["rows"]]
    for r in rows:
        assert r["hi80"] >= r["kg_opt"]
        assert r["hi80"] / r["kg_opt"] == pytest.approx(1.8, rel=0.01)
