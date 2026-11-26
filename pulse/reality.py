"""Проверка на реальности: где синтетика сходится с публичными цифрами, а где нет.

Три проверки:
1. compare_public — синтетика против опубликованных сборов по сети и городам (data/facts.csv).
2. volunteer_robustness — что будет с расстановкой, если эффект волонтёра в жизни
   меньше, чем оценила модель (вплоть до нуля) или больше.
3. stress_heterogeneity — справится ли модель, если магазины и регионы в жизни
   различаются сильнее, чем в синтетике (а публичные цифры говорят, что так и есть).
"""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import allocate, backtest, features, synth
from .models import GLMEB, Naive

# Публичная цифра → как посчитать то же самое на синтетике.
# cities — префиксы названий городов в таблице фонда; actions — акции синтетики, ближайшие по смыслу;
# per_store — сравнивать средний сбор на магазин (иначе — сумму по городу за эти акции).
PUBLIC_CHECKS = [
    dict(fact="kd_spring_total_kg", label="Вся сеть, весенняя акция", cities=None, actions=["2025-03"], per_store=True,
         real_per_store=119870 / 1650, in_sample=True,
         caveat="По этой цифре синтетика откалибрована — совпадение по построению, не проверка."),
    dict(fact="marathon_2024_kg_pyat", label="Москва и Петербург, марафон 2024", cities=["Москва г", "Санкт-Петербург г"],
         actions=["2025-11"], per_store=True, real_per_store=54000 / 1609,
         caveat="Декабрь 2024 вне истории синтетики; сравниваем с ноябрём 2025, на магазин."),
    dict(fact="city_h1_2025_msk", label="Москва, I полугодие 2025", cities=["Москва г"], actions=["2025-03", "2025-06"],
         per_store=False, caveat="В полугодие могли входить и другие сборы фонда, не только две акции."),
    dict(fact="city_h1_2025_spb", label="Петербург, I полугодие 2025", cities=["Санкт-Петербург г"],
         actions=["2025-03", "2025-06"], per_store=False,
         caveat="В полугодие могли входить и другие сборы фонда, не только две акции."),
    dict(fact="partner_tver_2026_02", label="Тверь, 7 магазинов, февраль 2026", cities=["Тверь г"], actions=["2026-03"],
         per_store=True, real_per_store=1554 / 7,
         caveat="Акция партнёра в феврале; сравниваем с мартом 2026, на магазин."),
    dict(fact="partner_ulyanovsk_2026_11", label="Ульяновск, ноябрь 2026", cities=["Ульяновск г"], actions=["2026-11"],
         per_store=False, caveat="Цифра одного партнёра; сколько магазинов он покрывал, неизвестно."),
]


def load_facts(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def compare_public(store_actions: pd.DataFrame, facts: dict[str, dict]) -> pd.DataFrame:
    """Таблица «публичная цифра против синтетики» с отношением синтетика / реальность."""
    rows = []
    for c in PUBLIC_CHECKS:
        f = facts[c["fact"]]
        sa = store_actions[store_actions["action_id"].isin(c["actions"])]
        if c["cities"]:
            sa = sa[sa["city"].str.startswith(tuple(c["cities"]))]
        if c["per_store"]:
            real, syn, unit = c.get("real_per_store", float(f["value"])), sa["kg"].mean(), "кг на магазин"
        else:
            real, syn, unit = float(f["value"]), sa["kg"].sum(), "кг"
        rows.append(dict(fact=c["fact"], label=c["label"], unit=unit, real=real, synthetic=syn, ratio=syn / real,
                         stores=int(sa["store_id"].nunique()), in_sample=c.get("in_sample", False),
                         caveat=c["caveat"], source_url=f["source_url"], status=f["status"]))
    return pd.DataFrame(rows)


def ratio_spread(cmp: pd.DataFrame) -> float:
    """Типичный промах синтетики по городам: exp(RMS лог-отношения) по проверкам вне калибровки."""
    out = cmp[~cmp["in_sample"]]
    return float(np.exp(np.sqrt(np.mean(np.log(out["ratio"]) ** 2))))


def volunteer_robustness(slots: pd.DataFrame, budget: pd.Series, current: pd.Series, b: np.ndarray,
                         scales=(0.0, 0.5, 1.0, 2.0)) -> pd.DataFrame:
    """Расстановка рассчитана при эффекте b. Что она даст, если реальный эффект — b × scale?

    Прогноз при нынешней расстановке в каждом сценарии тот же (он привязан к публичной цифре фонда),
    сбор без волонтёров пересчитывается под сценарий.

    Для каждого сценария: прирост к «как сейчас» и к «поровну», и сколько теряем
    по сравнению с расстановкой, которую выбрали бы, зная настоящий эффект.
    """
    opt = allocate.optimize(slots, budget, b)
    uni = allocate.uniform(slots, budget)
    idx = pd.MultiIndex.from_frame(slots[["store_id", "date"]])
    v_cur = current.reindex(idx, fill_value=0).to_numpy()
    rows = []
    for s in scales:
        bs = b * s
        # уровень сбора привязан к публичной цифре фонда: при нынешней расстановке прогноз тот же,
        # меняется только доля, которую дают волонтёры
        sl = slots.assign(base_kg=slots["base_kg"] * allocate.multiplier(v_cur, b) / allocate.multiplier(v_cur, bs))
        kg = {name: allocate.expected_kg(sl, v, bs).sum() for name, v in
              (("opt", opt), ("current", current), ("uniform", uni), ("oracle", allocate.optimize(sl, budget, bs)))}
        rows.append(dict(scale=s, kg_opt=kg["opt"], kg_current=kg["current"], kg_uniform=kg["uniform"],
                         kg_oracle=kg["oracle"],
                         uplift_vs_current=kg["opt"] / kg["current"] - 1,
                         uplift_vs_uniform=kg["opt"] / kg["uniform"] - 1,
                         regret=1 - kg["opt"] / kg["oracle"]))
    return pd.DataFrame(rows)


def stress_heterogeneity(stores: pd.DataFrame, slots: pd.DataFrame,
                         scenarios=((0.5, 0.3), (0.8, 0.8), (1.0, 1.3))) -> pd.DataFrame:
    """Сгенерировать синтетику с бóльшим разбросом магазинов и регионов и прогнать бэктест."""
    rows = []
    for sig_store, sig_region in scenarios:
        truth = synth.calibrate(stores, slots, replace(synth.Truth(), sigma_store=sig_store, sigma_region=sig_region))
        hourly, _, _ = synth.generate(stores, slots, truth)
        agg = features.aggregate(hourly, stores)
        res, _ = backtest.run(agg, models=(Naive, GLMEB))
        summ = backtest.summary(res)
        rows.append(dict(sigma_store=sig_store, sigma_region=sig_region,
                         wape_glm=float(summ.loc["glm_eb", "wape"]), wape_naive=float(summ.loc["naive", "wape"]),
                         net_err_glm=float(summ.loc["glm_eb", "network_ape"]),
                         net_err_naive=float(summ.loc["naive", "network_ape"])))
    out = pd.DataFrame(rows)
    out["gain_vs_naive"] = 1 - out["wape_glm"] / out["wape_naive"]
    return out
