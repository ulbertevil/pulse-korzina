"""Сайт считает в браузере (site/model.js) то же, что Python. Проверяем на демо-выгрузке."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pulse import backtest, synth, upload
from pulse.models import GLMEB, Naive
from pulse.stores import load_table

ROOT = Path(__file__).resolve().parents[1]
NEXT = "2026-12-10"

if os.environ.get("CI") and shutil.which("node") is None:
    raise RuntimeError("в CI нужен Node.js — без него проверка JS-порта модели молча пропустилась бы")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    stores, slots = load_table(ROOT / "data/raw/stores-2026-11.csv", 2026)
    truth = synth.calibrate(stores, slots)
    hourly, _, _ = synth.generate(stores, slots, truth)
    path = tmp_path_factory.mktemp("demo") / "export.csv"
    upload.demo_export(hourly, stores).to_csv(path, index=False)
    js = json.loads(subprocess.run(["node", str(ROOT / "tests/js_parity.cjs"), str(path), NEXT],
                                   capture_output=True, text=True, check=True).stdout)
    agg = upload.aggregate_export(pd.read_csv(path, dtype={"магазин": str}).rename(columns=upload.RU))
    return js, agg


def test_reader_uses_every_row(demo):
    js, _ = demo
    assert js["report"]["missing"] == [] and js["report"]["skipped"] == 0
    assert js["report"]["used"] == js["report"]["rows"]


def test_plan_fact_matches_python(demo):
    js, agg = demo
    last = agg["action_id"].max()
    assert js["lastAction"] == last
    prev, cur = agg[agg["action_id"] < last], agg[agg["action_id"] == last]
    py = pd.Series(GLMEB().fit(prev).predict(cur), index=cur["store_id"].to_numpy())
    jsp = pd.Series(js["planFact"])
    assert set(jsp.index) == set(py.index)
    np.testing.assert_allclose(jsp[py.index].to_numpy(), py.to_numpy(), rtol=1e-5)


def test_forecast_and_coefficients_match_python(demo):
    js, agg = demo
    m = GLMEB().fit(agg)
    assert js["kappa"] == m.kappa_
    total = m.predict(upload.next_plan(agg, NEXT)).sum()
    assert js["forecast"] == pytest.approx(total, rel=1e-5)
    py = m.coef()
    for name in ("log_hours", "vol_ge1", "chain_perekrestok", "season_november"):
        assert js["coef"][name] == pytest.approx(py[name], abs=1e-3)


def test_backtest_matches_python(demo):
    js, agg = demo
    res, _ = backtest.run(agg, models=(Naive, GLMEB))
    for step in js["steps"]:
        r = res[res["target"] == step["target"]].set_index("model")
        assert step["wape_glm"] == pytest.approx(r.loc["glm_eb", "wape"], rel=1e-5)
        assert step["wape_naive"] == pytest.approx(r.loc["naive", "wape"], rel=1e-5)
