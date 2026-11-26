"""Собрать данные, синтетику, бэктест, прогноз и расстановку на следующую акцию.

Какая акция следующая — в data/next_action.json (обновляет scripts/new_action.py).
Запуск: python scripts/build.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pulse import allocate, backtest, experiment, features, forecast, reality, site_export, synth, upload  # noqa: E402
from pulse.models import GLMEB  # noqa: E402
from pulse.stores import load_table  # noqa: E402

RAW = ROOT / "data/raw/stores-2026-11.csv"  # история: магазины и часы ноябрьской акции
NEXT = json.loads((ROOT / "data/next_action.json").read_text(encoding="utf-8"))
A = NEXT["action_id"]


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

    # План следующей акции; волонтёры — средние по магазину в ноябре (сценарий «как в прошлый раз»)
    nov = hourly[hourly["action_id"] == "2026-11"]
    vol = nov.groupby("store_id")["volunteers"].mean()
    if NEXT.get("table"):  # фонд подключил таблицу новой акции: её магазины, даты и часы
        plan_stores, next_slots = load_table(ROOT / NEXT["table"], NEXT["year"])
        plan = forecast.plan_from_own_slots(next_slots, A, volunteers=forecast.fill_volunteers(vol, plan_stores))
    else:  # таблицы ещё нет: магазины и часы ноября переносятся на даты из конфига
        plan_stores = stores
        plan = forecast.plan_from_slots(slots, NEXT["dates"], A, volunteers=vol)
    known = stores[~stores["store_id"].isin(plan_stores["store_id"])]
    stores_all = pd.concat([known, plan_stores], ignore_index=True)  # для плана — свойства из новой таблицы
    print(f"следующая акция {A}: {plan['store_id'].nunique()} магазинов, даты {', '.join(sorted(plan['date'].unique()))}")
    plan_agg = features.aggregate(plan, plan_stores)
    sd = forecast.network_log_sd(res)
    model = GLMEB().fit(agg)
    per_store, total = forecast.forecast(agg, plan_agg, sd, model=model)
    per_store.to_csv(rep / f"forecast_{A}_stores.csv", index=False)
    total["sets"] = forecast.kg_to_people(total["pred_kg"])["sets"]
    total["backtest"] = summ.round(4).reset_index().to_dict(orient="records")
    total["synthetic"] = True
    (rep / f"forecast_{A}.json").write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"прогноз {A}: {total['pred_kg']/1000:.1f} т "
          f"(95%: {total['lo95_kg']/1000:.1f}–{total['hi95_kg']/1000:.1f} т), ≈{total['sets']:.0f} наборов")

    # Расстановка волонтёров на ту же акцию: те же люди, что в ноябре, по городам и дням
    b = allocate.vol_coefs(model.coef())
    zero = plan_agg.assign(**{f"v{k}": 0.0 for k in features.VOL_LEVELS})
    pred0 = pd.Series(model.predict(zero), index=plan_agg["store_id"].to_numpy())
    slots_dec = allocate.slot_table(plan, pred0, allocate.hour_weights(hourly, b), plan_stores)
    current = plan.groupby(["store_id", "date"])["volunteers"].first()
    budget = (slots_dec.assign(v=current.reindex(pd.MultiIndex.from_frame(slots_dec[["store_id", "date"]])).to_numpy())
              .groupby(["city", "date"])["v"].sum())
    alloc, alloc_sum = allocate.compare(slots_dec, budget, current, b)
    alloc.to_csv(rep / f"allocation_{A}_slots.csv", index=False)
    allocate.city_summary(alloc).to_csv(rep / f"allocation_{A}_cities.csv")
    alloc_sum["synthetic"] = True
    (rep / f"allocation_{A}.json").write_text(json.dumps(alloc_sum, ensure_ascii=False, indent=2),
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
    # Список «тест / контроль» на следующую акцию: страты по прогнозу сбора
    dec = per_store.rename(columns={"pred_kg": "pred"}).reset_index(drop=True)
    st = experiment.strata(dec, "pred")
    dec.assign(stratum=st, group=experiment.assign(dec, st))[
        ["store_id", "city", "region", "chain", "pred", "stratum", "group"]
    ].to_csv(rep / f"experiment_{A}_assignment.csv", index=False)
    # Данные для сайта
    hw = allocate.hour_weights(hourly, b)
    pred_cur = pd.Series(per_store["pred_kg"].to_numpy(), index=per_store["store_id"].to_numpy())
    hourly_plan = allocate.hourly_split(plan, pred_cur, hw, b)
    site = site_export.build(rep, stores_all, hourly_plan, total, alloc, alloc_sum, allocate.city_summary(alloc),
                             res, summ, preds, des, ROOT / "data/facts.csv")
    site["meta"].update({"regions": int(plan_stores["region"].nunique()), "cities": int(plan_stores["city"].nunique()),
                         "table_connected": bool(NEXT.get("table")), "next_source": NEXT.get("source_url")})
    if NEXT.get("table") and "docs.google.com" in NEXT.get("source_url", ""):
        site["meta"]["source_table"] = NEXT["source_url"]
    # Проверка на реальности
    cmp = reality.compare_public(agg, reality.load_facts(ROOT / "data/facts.csv"))
    robust = reality.volunteer_robustness(slots_dec, budget, current, b)
    stress = reality.stress_heterogeneity(stores, slots)
    real = {"public": cmp.round(4).to_dict(orient="records"), "spread": round(reality.ratio_spread(cmp), 3),
            "volunteers": robust.round(5).to_dict(orient="records"),
            "stress": stress.round(4).to_dict(orient="records")}
    (rep / "reality.json").write_text(json.dumps(real, ensure_ascii=False, indent=2), encoding="utf-8")
    site["reality"] = real
    coord = site_export.coordinator(alloc, per_store, b, sd)
    gl = coord["goal"]
    need = allocate.shifts_for_target(allocate.extra_steps(alloc, b), gl["kg_opt"], 160_000)
    print(f"цель: максимум {(gl['kg_opt'] + sum(x[1] for x in gl['steps']) / 10) / 1000:.1f} т при 3 людях на точке; "
          f"для 160 т в среднем нужно ещё {need} смен")
    coord.update({"action": A, "dates": sorted(plan["date"].unique().tolist())})
    (ROOT / "site/data").mkdir(parents=True, exist_ok=True)
    (ROOT / "site/data/coordinator.json").write_text(json.dumps(coord, ensure_ascii=False, separators=(",", ":")),
                                                     encoding="utf-8")
    site_export.write(ROOT / "site/data", site, {
        "experiment_assignment.csv": rep / f"experiment_{A}_assignment.csv",
        "allocation_slots.csv": rep / f"allocation_{A}_slots.csv",
        "allocation_cities.csv": rep / f"allocation_{A}_cities.csv",
        "forecast_stores.csv": rep / f"forecast_{A}_stores.csv",
        "facts.csv": ROOT / "data/facts.csv",
    })
    # Демо-выгрузка для кнопки «Попробовать» на сайте: та же синтетика в формате выгрузки фонда
    upload.demo_export(hourly, stores).to_csv(ROOT / "site/data/demo_export.csv", index=False)
    print(f"реальность: синтетика по городам промахивается в {real['spread']:.1f} раза; при нулевом эффекте "
          f"волонтёров расстановка не хуже ноябрьской: {robust.loc[robust.scale == 0, 'uplift_vs_current'].iloc[0]:+.1%}; "
          f"при разбросе регионов ×3,7 модель лучше наивной на {stress['gain_vs_naive'].iloc[-1]:.0%}")
    print(f"A/B: MDE {des['mde']['raw']:.1%} → {des['mde']['cuped_strata']:.1%} с CUPED и стратами; "
          f"A/A ложных срабатываний {des['check_aa']['reject_rate']:.0%}, "
          f"мощность на MDE {des['check_power_at_mde']['reject_rate']:.0%}")


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    main()
