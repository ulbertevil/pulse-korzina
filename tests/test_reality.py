"""Проверка на реальности: сверка с публичными цифрами, устойчивость расстановки, стресс-тест."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pulse import features, reality, synth
from pulse.stores import load_table

ROOT = Path(__file__).resolve().parents[1]
B = np.array([0.38, 0.14, 0.07])


@pytest.fixture(scope="module")
def table():
    return load_table(ROOT / "data/raw/stores-2026-11.csv", 2026)


def test_every_public_check_has_a_sourced_fact():
    facts = reality.load_facts(ROOT / "data/facts.csv")
    for c in reality.PUBLIC_CHECKS:
        assert c["fact"] in facts and facts[c["fact"]]["source_url"].startswith("http")


def test_calibration_anchor_is_matched_and_flagged(table):
    stores, slots = table
    truth = synth.calibrate(stores, slots)
    hourly, _, _ = synth.generate(stores, slots, truth)
    cmp = reality.compare_public(features.aggregate(hourly, stores), reality.load_facts(ROOT / "data/facts.csv"))
    anchor = cmp[cmp["in_sample"]]
    assert len(anchor) == 1 and anchor["ratio"].iloc[0] == pytest.approx(1, rel=0.01)
    assert (cmp["stores"] > 0).all()
    # честно: по городам синтетика промахивается заметно, и мы это показываем
    assert reality.ratio_spread(cmp) > 1.5


def slots_budget():
    s = pd.DataFrame({"store_id": list("abcdef"), "date": ["2026-12-10"] * 6, "city": list("XXXXYY"),
                      "hours": [4] * 6, "base_kg": [120.0, 80.0, 40.0, 10.0, 60.0, 30.0]})
    idx = pd.MultiIndex.from_frame(s[["store_id", "date"]])
    current = pd.Series([0, 1, 1, 2, 1, 1], index=idx)  # «как сейчас»: людей ставят не туда
    budget = pd.Series({("X", "2026-12-10"): 4, ("Y", "2026-12-10"): 2})
    return s, budget, current


def test_allocation_never_loses_whatever_the_true_effect():
    s, budget, current = slots_budget()
    r = reality.volunteer_robustness(s, budget, current, B, scales=(0, 0.25, 0.5, 1, 2, 4))
    assert r.loc[r.scale == 0, "uplift_vs_current"].iloc[0] == pytest.approx(0)
    assert (r["uplift_vs_current"] >= -1e-12).all() and (r["uplift_vs_uniform"] >= -1e-12).all()
    assert r.loc[r.scale == 1, "regret"].iloc[0] == pytest.approx(0, abs=1e-12)
    assert (r["regret"] >= -1e-12).all()
    # в пределах «вдвое меньше — вдвое больше» потеря к идеальной расстановке мала;
    # при эффекте ×4 она растёт — это ограничение, оно описано на сайте
    assert (r.loc[r.scale <= 2, "regret"] < 0.05).all()
    assert r["uplift_vs_current"].is_monotonic_increasing


def test_model_beats_naive_when_stores_differ_more(table):
    stores, slots = table
    st = reality.stress_heterogeneity(stores, slots, scenarios=((1.0, 1.3),))
    assert st["gain_vs_naive"].iloc[0] > 0.1
