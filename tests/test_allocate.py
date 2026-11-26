import itertools

import numpy as np
import pandas as pd
import pytest

from pulse import allocate

B = np.array([0.38, 0.14, 0.07])


def toy_slots():
    return pd.DataFrame({
        "store_id": ["a", "b", "c", "d"],
        "date": ["2026-12-10"] * 4,
        "city": ["X", "X", "X", "Y"],
        "hours": [4, 4, 4, 4],
        "base_kg": [100.0, 60.0, 20.0, 50.0],
    })


def brute_force(slots, budget, b):
    """Перебор всех расстановок — эталон для маленькой задачи."""
    best = None
    for v in itertools.product(range(allocate.MAX_PER_SLOT + 1), repeat=len(slots)):
        v = np.array(v)
        ok = all(v[(slots["city"] == c).to_numpy()].sum() <= n for (c, _), n in budget.items())
        if ok:
            kg = (slots["base_kg"].to_numpy() * allocate.multiplier(v, b)).sum()
            best = kg if best is None or kg > best else best
    return best


@pytest.mark.parametrize("nx, ny", [(0, 0), (1, 0), (3, 1), (5, 2), (9, 3), (20, 5)])
def test_greedy_matches_brute_force(nx, ny):
    s = toy_slots()
    budget = pd.Series({("X", "2026-12-10"): nx, ("Y", "2026-12-10"): ny})
    v = allocate.optimize(s, budget, B)
    got = allocate.expected_kg(s, v, B).sum()
    assert got == pytest.approx(brute_force(s, budget, B))


def test_budget_respected_and_capped():
    s = toy_slots()
    budget = pd.Series({("X", "2026-12-10"): 100, ("Y", "2026-12-10"): 1})
    v = allocate.optimize(s, budget, B)
    assert v.max() <= allocate.MAX_PER_SLOT
    assert v.loc[("d", "2026-12-10")] == 1


def test_strong_store_gets_people_first():
    s = toy_slots()
    v = allocate.optimize(s, pd.Series({("X", "2026-12-10"): 1}), B)
    assert v.loc[("a", "2026-12-10")] == 1 and v.sum() == 1


def test_zero_effect_means_zero_gain():
    s = toy_slots()
    b0 = allocate.vol_coefs({"vol_ge1": 0.4}, effect_scale=0.0)
    budget = pd.Series({("X", "2026-12-10"): 3})
    _, summ = allocate.compare(s, budget, pd.Series(dtype=int), b0)
    assert summ["kg"]["opt"] == pytest.approx(summ["kg"]["none"])


def test_negative_coefficients_are_clipped():
    assert (allocate.vol_coefs({"vol_ge1": 0.3, "vol_ge2": -0.1, "vol_ge3": 0.05}) >= 0).all()


def test_optimal_not_worse_than_uniform_or_current():
    s = toy_slots()
    budget = pd.Series({("X", "2026-12-10"): 4, ("Y", "2026-12-10"): 1})
    current = pd.Series([2, 0, 2, 1], index=pd.MultiIndex.from_frame(s[["store_id", "date"]]))
    _, summ = allocate.compare(s, budget, current, B)
    assert summ["kg"]["opt"] >= summ["kg"]["uniform"] - 1e-9
    assert summ["kg"]["opt"] >= summ["kg"]["current"] - 1e-9


@pytest.mark.parametrize("nx, ny, extra", [(0, 0, 3), (2, 1, 1), (3, 1, 4), (5, 0, 6), (9, 3, 2)])
def test_extra_shifts_match_brute_force(nx, ny, extra):
    """Первые N «дополнительных смен» = лучший результат, если люди города остаются в городе, а N новых — где угодно."""
    s = toy_slots()
    n = {"X": nx, "Y": ny}
    budget = pd.Series({("X", "2026-12-10"): nx, ("Y", "2026-12-10"): ny})
    s["v_opt"] = allocate.optimize(s, budget, B).to_numpy()
    start = allocate.expected_kg(s, s.set_index(["store_id", "date"])["v_opt"], B).sum()
    steps = allocate.extra_steps(s, B)
    got = start + steps["gain_kg"].head(extra).sum()
    best = 0.0
    for v in itertools.product(range(allocate.MAX_PER_SLOT + 1), repeat=len(s)):
        v = np.array(v)
        over = sum(max(0, v[(s["city"] == c).to_numpy()].sum() - k) for c, k in n.items())
        if over <= extra:
            best = max(best, (s["base_kg"].to_numpy() * allocate.multiplier(v, B)).sum())
    assert got == pytest.approx(best)


def test_shifts_for_target():
    s = toy_slots().assign(v_opt=0)
    steps = allocate.extra_steps(s, B)
    start = s["base_kg"].sum()
    assert allocate.shifts_for_target(steps, start, start - 1) == 0
    assert allocate.shifts_for_target(steps, start, start + steps["gain_kg"].iloc[0]) == 1
    assert allocate.shifts_for_target(steps, start, start + steps["gain_kg"].iloc[:2].sum() + 0.01) == 3
    assert allocate.shifts_for_target(steps, start, start + steps["gain_kg"].sum() + 1) is None
    assert (steps["gain_alt_kg"] < steps["gain_kg"]).all()
