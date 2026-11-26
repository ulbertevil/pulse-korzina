"""Генератор СИНТЕТИЧЕСКИХ сборов «магазин × день × час».

Реальное в нём только «скелет»: список магазинов, города, регионы, сети и
часы проведения из таблицы фонда за ноябрь 2026. Килограммы, волонтёры и
участие магазинов в прошлых акциях выдуманы, но откалиброваны так, чтобы
средний сбор на магазин в весенней акции совпадал с публичной цифрой фонда
(119 870 кг в 1 650 магазинах ≈ 72,6 кг на магазин, см. data/facts.csv).

Все параметры «истины» сохраняются в truth.json, чтобы тесты могли проверять,
восстанавливает ли модель то, что в данные заложено.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 20261126
ANCHOR_KG_PER_STORE_SPRING = 119870 / 1650  # data/facts.csv: kd_spring_total_kg / kd_spring_stores


@dataclass(frozen=True)
class Action:
    action_id: str
    thursday: date  # четверг недели акции; дни магазина сдвигаются от него
    season: str


# Прошлые акции — синтетический календарь; ноябрь 2026 — реальные даты из таблицы фонда.
ACTIONS: tuple[Action, ...] = (
    Action("2025-03", date(2025, 3, 13), "spring"),
    Action("2025-06", date(2025, 6, 19), "summer"),
    Action("2025-09", date(2025, 9, 18), "autumn"),
    Action("2025-11", date(2025, 11, 20), "november"),
    Action("2026-03", date(2026, 3, 19), "spring"),
    Action("2026-06", date(2026, 6, 18), "summer"),
    Action("2026-09", date(2026, 9, 17), "autumn"),
    Action("2026-11", date(2026, 11, 19), "november"),
)
NOV_2026_THURSDAY = date(2026, 11, 19)


@dataclass
class Truth:
    """Параметры, заложенные в синтетику. Это допущения, а не измерения."""
    seed: int = SEED
    season: dict = field(default_factory=lambda: {
        "spring": 1.0, "summer": 0.8, "autumn": 0.9, "november": 1.15, "december": 1.3})
    growth_per_year: float = 1.10        # цель фонда +10% в год (goal_plus10)
    weekday: dict = field(default_factory=lambda: {3: 0.85, 4: 1.0, 5: 1.15, 6: 1.05})  # чт..вс
    hour_profile: dict = field(default_factory=lambda: {
        12: 0.8, 13: 0.8, 14: 0.9, 15: 1.0, 16: 1.05, 17: 1.3, 18: 1.3, 19: 1.1, 20: 0.7, 21: 0.6})
    chain: dict = field(default_factory=lambda: {"Пятёрочка": 1.0, "Перекрёсток": 1.25})
    sigma_store: float = 0.5             # разброс магазинов (лог-шкала)
    sigma_region: float = 0.3            # разброс регионов
    sigma_action_shock: float = 0.2      # общий шок магазина в акции
    sigma_network_shock: float = 0.08    # общий шок всей акции (погода, новости)
    hour_gamma_shape: float = 2.0        # шум внутри часа
    vol_beta: float = 0.9                # максимум прироста от волонтёров (+90%)
    vol_tau: float = 1.2                 # насыщение: m(v) = 1 + beta·(1 − e^(−v/tau))
    p_participate: float = 0.85          # участие магазина в прошлой акции
    p_volunteer_store: float = 0.6       # доля магазинов, куда обычно ставят волонтёров
    scale: float = 1.0                   # подбирается калибровкой

    def vol_mult(self, v):
        return 1 + self.vol_beta * (1 - np.exp(-np.asarray(v, float) / self.vol_tau))


def _years_since_start(d: date) -> float:
    return (d - ACTIONS[0].thursday).days / 365.25


def _hours(start: float, end: float) -> list[int]:
    return list(range(int(np.floor(start)), int(np.ceil(end))))


def expand_slots(slots: pd.DataFrame, action: Action) -> pd.DataFrame:
    """Перенести ноябрьское расписание магазина на даты другой акции (сохраняя день недели)."""
    s = slots.copy()
    offset = (pd.to_datetime(s["date"]).dt.date.map(lambda d: (d - NOV_2026_THURSDAY).days))
    s["date"] = offset.map(lambda o: (action.thursday + timedelta(days=int(o))).isoformat())
    rows = []
    for r in s.itertuples(index=False):
        for h in _hours(r.start, r.end):
            rows.append((r.store_id, r.date, h))
    return pd.DataFrame(rows, columns=["store_id", "date", "hour"])


def generate(stores: pd.DataFrame, slots: pd.DataFrame, truth: Truth | None = None,
             actions: tuple[Action, ...] = ACTIONS) -> tuple[pd.DataFrame, Truth, dict]:
    """Сгенерировать сборы по часам. Возвращает (таблица, истина, эффекты магазинов)."""
    truth = truth or Truth()
    rng = np.random.default_rng(truth.seed)

    regions = sorted(stores["region"].unique())
    region_eff = dict(zip(regions, rng.normal(0, truth.sigma_region, len(regions))))
    store_eff = rng.normal(0, truth.sigma_store, len(stores))
    log_level = {
        sid: e + region_eff[reg] + np.log(truth.chain.get(ch, 1.0))
        for sid, e, reg, ch in zip(stores["store_id"], store_eff, stores["region"], stores["chain"])
    }
    vol_store = dict(zip(stores["store_id"], rng.random(len(stores)) < truth.p_volunteer_store))
    # магазин присоединяется к акциям не сразу: «холодный старт» для части магазинов
    first_action = dict(zip(stores["store_id"],
                            rng.choice(len(actions), len(stores), p=_join_probs(len(actions)))))

    frames = []
    for ai, act in enumerate(actions):
        grid = expand_slots(slots, act)
        is_last = ai == len(actions) - 1
        part = {sid: (is_last or (ai >= first_action[sid] and rng.random() < truth.p_participate))
                for sid in stores["store_id"]}
        grid = grid[grid["store_id"].map(part)]
        sid_u = grid["store_id"].unique()
        shock = dict(zip(sid_u, rng.normal(0, truth.sigma_action_shock, len(sid_u))))
        net_shock = rng.normal(0, truth.sigma_network_shock)
        # волонтёры: 0–3 человека в час там, где их обычно ставят
        has_vol = grid["store_id"].map(vol_store).to_numpy()
        vol = np.where(has_vol, rng.choice([1, 2, 2, 3], len(grid)), rng.choice([0, 0, 0, 1], len(grid)))
        wd = pd.to_datetime(grid["date"]).dt.day_of_week.map(truth.weekday).fillna(1.0).to_numpy()
        hp = grid["hour"].map(truth.hour_profile).fillna(0.8).to_numpy()
        mu = (truth.scale
              * np.exp(grid["store_id"].map(log_level).to_numpy() + grid["store_id"].map(shock).to_numpy()
                       + net_shock)
              * truth.season[act.season] * truth.growth_per_year ** _years_since_start(act.thursday)
              * wd * hp * truth.vol_mult(vol))
        kg = rng.gamma(truth.hour_gamma_shape, mu / truth.hour_gamma_shape)
        frames.append(pd.DataFrame({
            "action_id": act.action_id, "store_id": grid["store_id"].to_numpy(),
            "date": grid["date"].to_numpy(), "hour": grid["hour"].to_numpy(),
            "volunteers": vol, "kg": np.round(kg, 2),
        }))
    df = pd.concat(frames, ignore_index=True)
    return df, truth, log_level


def _join_probs(n: int) -> np.ndarray:
    p = np.full(n, 0.04)
    p[0] = 1 - 0.04 * (n - 1)
    return p


def calibrate(stores: pd.DataFrame, slots: pd.DataFrame, truth: Truth | None = None) -> Truth:
    """Подобрать масштаб так, чтобы весна-2025 дала ≈72,6 кг на магазин (публичный якорь)."""
    truth = truth or Truth()
    df, _, _ = generate(stores, slots, truth)
    first = df[df["action_id"] == ACTIONS[0].action_id]
    per_store = first.groupby("store_id")["kg"].sum().mean()
    truth.scale = truth.scale * ANCHOR_KG_PER_STORE_SPRING / per_store
    return truth


def truth_json(truth: Truth) -> str:
    d = asdict(truth)
    d["weekday"] = {str(k): v for k, v in d["weekday"].items()}
    d["hour_profile"] = {str(k): v for k, v in d["hour_profile"].items()}
    d["note"] = "СИНТЕТИКА: параметры придуманы и откалиброваны по одной публичной цифре."
    return json.dumps(d, ensure_ascii=False, indent=2)
