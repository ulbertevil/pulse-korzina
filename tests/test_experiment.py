import math

import numpy as np
import pandas as pd
import pytest

from pulse import experiment as ex


@pytest.fixture(scope="module")
def stores():
    """Магазины с ковариатой (прогноз) и метрикой, коррелированной с ней (ρ ≈ 0,8)."""
    rng = np.random.default_rng(7)
    n = 1200
    pred = rng.lognormal(4, 0.6, n)
    kg = pred * rng.lognormal(0, 0.35, n)
    return pd.DataFrame({"store_id": [f"s{i}" for i in range(n)], "pred": pred, "kg": kg,
                         "chain": rng.choice(["Пятёрочка", "Перекрёсток"], n, p=[0.9, 0.1])})


def test_norm_ppf_matches_table():
    for p, v in ex.Z.items():
        assert ex._norm_ppf(p) == pytest.approx(v, abs=1e-3)


def test_mde_and_sample_size_are_inverse():
    sd, mean = 40.0, 90.0
    n = ex.sample_size(sd, mean, 0.10)
    assert ex.mde(sd, mean, n // 2, n - n // 2) == pytest.approx(0.10, rel=0.01)


def test_cuped_reduces_variance(stores):
    sd = ex.residual_sd(stores, stratum=ex.strata(stores))
    assert sd["sd_cuped"] < sd["sd_raw"]
    assert sd["sd_cuped"] == pytest.approx(sd["sd_raw"] * math.sqrt(1 - sd["rho"] ** 2), rel=0.01)


def test_assignment_is_balanced_within_strata(stores):
    st = ex.strata(stores)
    g = ex.assign(stores, st, share_test=0.5, seed=3)
    share = (g == "test").groupby(st).mean()
    assert share.between(0.35, 0.65).all()
    assert abs((g == "test").mean() - 0.5) < 0.03
    assert g.equals(ex.assign(stores, st, share_test=0.5, seed=3))  # воспроизводимо по сиду


def test_analyze_recovers_known_effect(stores):
    st = ex.strata(stores)
    g = ex.assign(stores, st, seed=5)
    d = stores.assign(group=g, kg=np.where(g == "test", stores["kg"] * 1.2, stores["kg"]))
    r = ex.analyze(d, stratum=st)
    assert r["effect_rel"] == pytest.approx(0.2, abs=0.05)
    assert r["ci_rel"][0] < 0.2 < r["ci_rel"][1]
    assert r["significant"]


def test_aa_false_positive_rate_close_to_alpha(stores):
    r = ex.simulate(stores, effect=0.0, n_sims=150, seed=11)
    assert r["reject_rate"] <= 0.10


def test_power_at_mde_close_to_target(stores):
    m = ex.design(stores)["mde"]["cuped_strata"]
    r = ex.simulate(stores, effect=m, n_sims=150, seed=21)
    assert 0.65 <= r["reject_rate"] <= 0.95
