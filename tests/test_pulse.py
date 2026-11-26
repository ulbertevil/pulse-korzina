import csv
from pathlib import Path

import numpy as np
import pytest

from pulse import backtest, features, synth
from pulse.models import GLMEB, Naive, fit_poisson
from pulse.schedule import parse_schedule
from pulse.stores import load_table, region_of

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/stores-2026-11.csv"


# --- расписание ------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("19, 20 ноября 15-19.00", [(19, 15, 19), (20, 15, 19)]),
    ("20 ноября с 16.00 до 20.00;\n21 ноября с 12.00 до 18.00", [(20, 16, 20), (21, 12, 18)]),
    ("20 ноября 15-19.00,  \n21 ноября 12-16.00", [(20, 15, 19), (21, 12, 16)]),
    ("19-21 ноября, 15-19.00", [(19, 15, 19), (20, 15, 19), (21, 15, 19)]),
    ("20 ноября 15.30-19.00", [(20, 15.5, 19)]),
    ("20-21 ноября 15-19.00\n22 ноября", [(20, 15, 19), (21, 15, 19), (22, 15, 19)]),
])
def test_parse_schedule_formats(raw, expected):
    got = [(s.day, s.start, s.end) for s in parse_schedule(raw)]
    assert got == expected
    assert not any(s.time_assumed for s in parse_schedule(raw))


def test_parse_schedule_without_time_is_flagged():
    slots = parse_schedule("20, 21 ноября")
    assert [s.day for s in slots] == [20, 21]
    assert all(s.time_assumed for s in slots)


def test_parse_schedule_garbage():
    assert parse_schedule("уточняется") == []


def test_region_of():
    assert region_of("655017, Хакасия респ., Абакан г., Ленина пр-кт, Дом 56") == "Хакасия респ."


# --- реальная таблица фонда ------------------------------------------------

@pytest.fixture(scope="module")
def table():
    return load_table(RAW, 2026)


def test_fund_table_parses_fully(table):
    stores, slots = table
    assert len(stores) == 1740  # 1741 строка, один адрес повторяется
    assert stores["schedule_ok"].all()
    assert set(slots["date"]) <= {"2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"}
    assert ((slots["end"] - slots["start"]) > 0).all()
    assert set(stores["chain"]) == {"Пятёрочка", "Перекрёсток"}


# --- синтетика -------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic(table):
    stores, slots = table
    truth = synth.calibrate(stores, slots)
    hourly, truth, _ = synth.generate(stores, slots, truth)
    return stores, hourly, truth, features.aggregate(hourly, stores)


def test_synthetic_is_deterministic(table, synthetic):
    stores, slots = table
    again, _, _ = synth.generate(stores, slots, synthetic[2])
    assert again["kg"].sum() == pytest.approx(synthetic[1]["kg"].sum())


def test_synthetic_calibrated_to_public_anchor(synthetic):
    _, hourly, _, _ = synthetic
    first = hourly[hourly["action_id"] == synth.ACTIONS[0].action_id]
    per_store = first.groupby("store_id")["kg"].sum().mean()
    assert per_store == pytest.approx(119870 / 1650, rel=1e-4)  # kg округлены до 0,01


def test_synthetic_has_no_negative_kg(synthetic):
    assert (synthetic[1]["kg"] >= 0).all()


# --- модели ----------------------------------------------------------------

def test_fit_poisson_recovers_coefficients():
    rng = np.random.default_rng(0)
    X = np.column_stack([np.ones(5000), rng.normal(size=5000)])
    y = rng.poisson(np.exp(X @ np.array([1.0, 0.5])))
    assert fit_poisson(X, y.astype(float)) == pytest.approx([1.0, 0.5], abs=0.05)


def test_glm_learns_volunteer_and_chain_effects(synthetic):
    _, _, truth, agg = synthetic
    coef = GLMEB().fit(agg).coef()
    assert coef["vol_ge1"] > 0.2            # волонтёры повышают сбор
    assert coef["vol_ge1"] > coef["vol_ge3"]  # отдача убывает
    assert coef["chain_perekrestok"] == pytest.approx(np.log(truth.chain["Перекрёсток"]), abs=0.15)
    assert coef["season_summer"] < 0 < coef["season_november"]


def test_glm_beats_naive_in_backtest(synthetic):
    res, _ = backtest.run(synthetic[3])
    s = backtest.summary(res)
    assert s.loc["glm_eb", "wape"] < 0.85 * s.loc["naive", "wape"]
    glm = res[res["model"] == "glm_eb"]
    assert glm["cover80"].mean() == pytest.approx(0.8, abs=0.1)
    assert glm["cover95"].mean() == pytest.approx(0.95, abs=0.06)


def test_cold_start_store_gets_prediction(synthetic):
    _, _, _, agg = synthetic
    train = agg[agg["action_id"] < "2026-11"]
    test = agg[agg["action_id"] == "2026-11"]
    new = test[~test["store_id"].isin(train["store_id"])]
    assert len(new) > 0
    for m in (Naive().fit(train), GLMEB().fit(train)):
        p = m.predict(new)
        assert np.isfinite(p).all() and (p > 0).all()


# --- факты -----------------------------------------------------------------

def test_facts_csv_is_valid():
    with open(ROOT / "data/facts.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    assert all(len(r) == len(header) for r in body)
    ids = [r[0] for r in body]
    assert len(ids) == len(set(ids))
    status = {"primary", "secondary", "fund_statement", "unverified", "estimate"}
    for r in body:
        rec = dict(zip(header, r))
        assert rec["status"] in status, rec["id"]
        assert rec["source_url"].startswith("https://"), rec["id"]
