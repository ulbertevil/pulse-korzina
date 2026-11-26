"""Собрать данные, синтетику, бэктест и прогноз на акцию 10–11 декабря 2026.

Запуск: python scripts/build.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pulse import backtest, features, forecast, synth  # noqa: E402
from pulse.stores import load_table  # noqa: E402

RAW = ROOT / "data/raw/stores-2026-11.csv"
NEXT_DATES = ["2026-12-10", "2026-12-11"]  # facts.csv: kd_next_action


def main() -> None:
    proc, syn, rep = ROOT / "data/processed", ROOT / "data/synthetic", ROOT / "reports"
    for d in (proc, syn, rep):
        d.mkdir(parents=True, exist_ok=True)

    stores, slots = load_table(RAW, 2026)
    stores.to_csv(proc / "stores.csv", index=False)
    slots.to_csv(proc / "slots-2026-11.csv", index=False)
    print(f"магазинов: {len(stores)}, слотов: {len(slots)}")

    truth = synth.calibrate(stores, slots)
    hourly, truth, _ = synth.generate(stores, slots, truth)
    hourly.to_csv(syn / "collections_hourly.csv", index=False)
    (syn / "truth.json").write_text(synth.truth_json(truth), encoding="utf-8")
    agg = features.aggregate(hourly, stores)
    agg.to_csv(syn / "store_actions.csv", index=False)
    print(f"синтетика: {len(hourly)} строк по часам, {len(agg)} строк «магазин × акция»")

    res, preds = backtest.run(agg)
    summ = backtest.summary(res)
    res.to_csv(rep / "backtest_steps.csv", index=False)
    preds.to_csv(rep / "backtest_store_preds.csv", index=False)
    print(summ.round(3).to_string())

    # План декабря: часы как в ноябре, волонтёры — средние по магазину в ноябре (сценарий «как в ноябре»)
    nov = hourly[hourly["action_id"] == "2026-11"]
    vol = nov.groupby("store_id")["volunteers"].mean()
    plan = forecast.plan_from_slots(slots, NEXT_DATES, "2026-12", volunteers=vol)
    plan_agg = features.aggregate(plan, stores)
    sd = forecast.network_log_sd(res)
    per_store, total = forecast.forecast(agg, plan_agg, sd)
    per_store.to_csv(rep / "forecast_2026-12_stores.csv", index=False)
    total["sets"] = forecast.kg_to_people(total["pred_kg"])["sets"]
    total["backtest"] = summ.round(4).reset_index().to_dict(orient="records")
    total["synthetic"] = True
    (rep / "forecast_2026-12.json").write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"прогноз 10–11.12: {total['pred_kg']/1000:.1f} т "
          f"(95%: {total['lo95_kg']/1000:.1f}–{total['hi95_kg']/1000:.1f} т), ≈{total['sets']:.0f} наборов")


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    main()
