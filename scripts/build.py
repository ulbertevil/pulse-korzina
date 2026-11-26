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

from pulse import allocate, backtest, experiment, features, forecast, site_export, synth  # noqa: E402
from pulse.models import GLMEB  # noqa: E402
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
    model = GLMEB().fit(agg)
    per_store, total = forecast.forecast(agg, plan_agg, sd, model=model)
    per_store.to_csv(rep / "forecast_2026-12_stores.csv", index=False)
    total["sets"] = forecast.kg_to_people(total["pred_kg"])["sets"]
    total["backtest"] = summ.round(4).reset_index().to_dict(orient="records")
    total["synthetic"] = True
    (rep / "forecast_2026-12.json").write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"прогноз 10–11.12: {total['pred_kg']/1000:.1f} т "
          f"(95%: {total['lo95_kg']/1000:.1f}–{total['hi95_kg']/1000:.1f} т), ≈{total['sets']:.0f} наборов")

    # Расстановка волонтёров на ту же акцию: те же люди, что в ноябре, по городам и дням
    b = allocate.vol_coefs(model.coef())
    zero = plan_agg.assign(**{f"v{k}": 0.0 for k in features.VOL_LEVELS})
    pred0 = pd.Series(model.predict(zero), index=plan_agg["store_id"].to_numpy())
    slots_dec = allocate.slot_table(plan, pred0, allocate.hour_weights(hourly, b), stores)
    current = plan.groupby(["store_id", "date"])["volunteers"].first()
    budget = (slots_dec.assign(v=current.reindex(pd.MultiIndex.from_frame(slots_dec[["store_id", "date"]])).to_numpy())
              .groupby(["city", "date"])["v"].sum())
    alloc, alloc_sum = allocate.compare(slots_dec, budget, current, b)
    alloc.to_csv(rep / "allocation_2026-12_slots.csv", index=False)
    allocate.city_summary(alloc).to_csv(rep / "allocation_2026-12_cities.csv")
    alloc_sum["synthetic"] = True
    (rep / "allocation_2026-12.json").write_text(json.dumps(alloc_sum, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    print(f"расстановка: {alloc_sum['shifts']} смен; оптимально +{alloc_sum['uplift_opt_vs_current']:.1%} "
          f"к «как в ноябре», +{alloc_sum['uplift_opt_vs_uniform']:.1%} к «поровну»; "
          f"кг на смену {alloc_sum['kg_per_shift_current']:.1f} → {alloc_sum['kg_per_shift_opt']:.1f}")

    # A/B: дисперсию и мощность оцениваем на последней акции (факт против прогноза «вслепую»)
    last = preds[preds["action_id"] == preds["action_id"].max()].merge(
        stores[["store_id", "chain", "city"]], on="store_id").reset_index(drop=True)
    des = experiment.design(last)
    des["check_aa"] = experiment.simulate(last, 0.0, n_sims=200)
    des["check_power_at_mde"] = experiment.simulate(last, des["mde"]["cuped_strata"], n_sims=200)
    des["calibrated_on"] = str(last["action_id"].iloc[0])
    des["synthetic"] = True
    (rep / "experiment_design.json").write_text(json.dumps(des, ensure_ascii=False, indent=2), encoding="utf-8")
    # Список «тест / контроль» на 10–11 декабря: страты по прогнозу сбора
    dec = per_store.rename(columns={"pred_kg": "pred"}).reset_index(drop=True)
    st = experiment.strata(dec, "pred")
    dec.assign(stratum=st, group=experiment.assign(dec, st))[
        ["store_id", "city", "region", "chain", "pred", "stratum", "group"]
    ].to_csv(rep / "experiment_2026-12_assignment.csv", index=False)
    # Данные для сайта
    hw = allocate.hour_weights(hourly, b)
    pred_cur = pd.Series(per_store["pred_kg"].to_numpy(), index=per_store["store_id"].to_numpy())
    hourly_plan = allocate.hourly_split(plan, pred_cur, hw, b)
    site = site_export.build(rep, stores, hourly_plan, total, alloc, alloc_sum, allocate.city_summary(alloc),
                             res, summ, preds, des, ROOT / "data/facts.csv")
    site_export.write(ROOT / "site/data", site, {
        "experiment_2026-12_assignment.csv": rep / "experiment_2026-12_assignment.csv",
        "allocation_2026-12_slots.csv": rep / "allocation_2026-12_slots.csv",
        "allocation_2026-12_cities.csv": rep / "allocation_2026-12_cities.csv",
        "forecast_2026-12_stores.csv": rep / "forecast_2026-12_stores.csv",
        "facts.csv": ROOT / "data/facts.csv",
    })
    print(f"A/B: MDE {des['mde']['raw']:.1%} → {des['mde']['cuped_strata']:.1%} с CUPED и стратами; "
          f"A/A ложных срабатываний {des['check_aa']['reject_rate']:.0%}, "
          f"мощность на MDE {des['check_power_at_mde']['reject_rate']:.0%}")


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    main()
