"""Расстановка волонтёров: куда поставить людей, чтобы собрать больше.

Единица ресурса — «смена»: один волонтёр на весь слот магазина в этот день
(обычно 4 часа). Бюджет смен задаётся на город и день акции.

Прирост от k-го волонтёра в слоте берётся из модели GLMEB: на уровне часа
сбор умножается на exp(b1·[v≥1] + b2·[v≥2] + b3·[v≥3]). Пока b1 > b2 > b3 > 0,
каждый следующий волонтёр в том же слоте даёт меньше предыдущего. Поэтому
выбрать N кандидатов «слот × k-й волонтёр» с наибольшим приростом — точное
решение задачи при бюджете N смен (задача сепарабельная и вогнутая).

ВАЖНО: эффект волонтёра в модели оценён по наблюдениям, а не по эксперименту.
На реальных данных он может быть завышен, если сильных волонтёров ставят в
сильные магазины. Поэтому есть параметр effect_scale (сценарий) и модуль
дизайна эксперимента, который этот эффект измерит.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import VOL_LEVELS

MAX_PER_SLOT = VOL_LEVELS[-1]  # дальше 3 человек модель не видела данных


def vol_coefs(coef: dict, effect_scale: float = 1.0) -> np.ndarray:
    """Коэффициенты b1..b3 (лог-шкала), отрицательные обнуляются, умножаются на сценарий."""
    b = np.array([max(coef.get(f"vol_ge{k}", 0.0), 0.0) for k in VOL_LEVELS]) * effect_scale
    return b


def multiplier(v, b: np.ndarray) -> np.ndarray:
    """Множитель сбора при v волонтёрах: exp(b1 + … + b_v)."""
    cum = np.concatenate([[0.0], np.cumsum(b)])
    return np.exp(cum[np.clip(np.asarray(v, int), 0, len(b))])


def hour_weights(hourly: pd.DataFrame, b: np.ndarray) -> pd.Series:
    """Относительный сбор по (день недели, час), очищенный от эффекта волонтёров."""
    h = hourly.copy()
    h["wd"] = pd.to_datetime(h["date"]).dt.day_of_week
    h["kg0"] = h["kg"] / multiplier(h["volunteers"], b)
    w = h.groupby(["wd", "hour"])["kg0"].mean()
    return w / w.mean()


def hourly_split(plan: pd.DataFrame, pred: pd.Series, weights: pd.Series, b: np.ndarray | None = None) -> pd.DataFrame:
    """Разложить прогноз магазина на акцию по его часам.

    Доля часа ∝ weights(день недели, час) × множитель волонтёров этого часа (если b задан).
    """
    p = plan.copy()
    p["wd"] = pd.to_datetime(p["date"]).dt.day_of_week
    p["w"] = [weights.get((wd, h), np.nan) for wd, h in zip(p["wd"], p["hour"])]
    p["w"] = p["w"].fillna(weights.mean())
    if b is not None and "volunteers" in p:
        p["w"] = p["w"] * multiplier(p["volunteers"], b)
    p["share"] = p["w"] / p.groupby("store_id")["w"].transform("sum")
    p["kg"] = p["share"] * p["store_id"].map(pred)
    return p


def slot_table(plan: pd.DataFrame, pred0: pd.Series, weights: pd.Series, stores: pd.DataFrame) -> pd.DataFrame:
    """Прогноз без волонтёров по слотам «магазин × день».

    pred0 — прогноз магазина на всю акцию при v=0 (Series по store_id);
    он раскладывается по часам пропорционально weights.
    """
    p = hourly_split(plan[["store_id", "date", "hour"]], pred0, weights).rename(columns={"kg": "base_kg"})
    s = p.groupby(["store_id", "date"]).agg(hours=("hour", "count"), start=("hour", "min"),
                                           end=("hour", "max"), base_kg=("base_kg", "sum")).reset_index()
    s["end"] += 1
    s["day_index"] = s.groupby("store_id")["date"].rank(method="dense").astype(int)
    return s.merge(stores[["store_id", "city", "region", "chain", "address"]], on="store_id", how="left")


def gains(slots: pd.DataFrame, b: np.ndarray) -> pd.DataFrame:
    """Кандидаты «слот × k-й волонтёр» и их прирост кг."""
    rows = []
    m = multiplier(np.arange(len(b) + 1), b)
    for k in range(1, len(b) + 1):
        g = slots[["store_id", "date", "city", "hours", "base_kg"]].copy()
        g["k"] = k
        g["gain_kg"] = g["base_kg"] * (m[k] - m[k - 1])
        rows.append(g)
    return pd.concat(rows, ignore_index=True)


def optimize(slots: pd.DataFrame, budget: pd.Series, b: np.ndarray) -> pd.Series:
    """Оптимальное число волонтёров на слот при бюджете смен на (город, дату).

    budget — Series с индексом (city, date). Возвращает Series по (store_id, date).
    """
    cand = gains(slots, b)
    cand = cand[cand["gain_kg"] > 0].sort_values(["city", "date", "gain_kg", "k"],
                                                 ascending=[True, True, False, True])
    cand["rank"] = cand.groupby(["city", "date"]).cumcount()
    cand["budget"] = [budget.get((c, d), 0) for c, d in zip(cand["city"], cand["date"])]
    chosen = cand[cand["rank"] < cand["budget"]]
    v = chosen.groupby(["store_id", "date"]).size()
    idx = pd.MultiIndex.from_frame(slots[["store_id", "date"]])
    return v.reindex(idx, fill_value=0).astype(int)


def uniform(slots: pd.DataFrame, budget: pd.Series) -> pd.Series:
    """Сравнение: те же люди, разложенные поровну по слотам города (по кругу)."""
    out = []
    for (city, date), g in slots.groupby(["city", "date"]):
        n, k = int(budget.get((city, date), 0)), len(g)
        base, extra = divmod(min(n, k * MAX_PER_SLOT), k)
        v = np.full(k, base) + (np.arange(k) < extra)
        out.append(pd.Series(v, index=pd.MultiIndex.from_frame(g[["store_id", "date"]])))
    idx = pd.MultiIndex.from_frame(slots[["store_id", "date"]])
    return pd.concat(out).reindex(idx, fill_value=0).astype(int)


def expected_kg(slots: pd.DataFrame, v: pd.Series, b: np.ndarray) -> np.ndarray:
    idx = pd.MultiIndex.from_frame(slots[["store_id", "date"]])
    return slots["base_kg"].to_numpy() * multiplier(v.reindex(idx, fill_value=0).to_numpy(), b)


def compare(slots: pd.DataFrame, budget: pd.Series, current: pd.Series, b: np.ndarray) -> tuple[pd.DataFrame, dict]:
    """Сравнить «оптимально», «как сейчас», «поровну» и «без волонтёров» при тех же людях."""
    opt = optimize(slots, budget, b)
    uni = uniform(slots, budget)
    s = slots.copy()
    s["v_current"] = current.reindex(pd.MultiIndex.from_frame(s[["store_id", "date"]]), fill_value=0).to_numpy()
    s["v_opt"] = opt.to_numpy()
    s["kg_none"] = s["base_kg"]
    s["kg_current"] = expected_kg(s, current, b)
    s["kg_uniform"] = expected_kg(s, uni, b)
    s["kg_opt"] = expected_kg(s, opt, b)
    s["gain_first_per_vol_hour"] = s["base_kg"] * (np.exp(b[0]) - 1) / s["hours"]
    tot = {k: float(s[f"kg_{k}"].sum()) for k in ("none", "current", "uniform", "opt")}
    shifts = int(budget.sum())
    summary = {
        "shifts": shifts,
        "shifts_used_opt": int(s["v_opt"].sum()),
        "kg": tot,
        "uplift_opt_vs_current": tot["opt"] / tot["current"] - 1,
        "uplift_opt_vs_uniform": tot["opt"] / tot["uniform"] - 1,
        "kg_per_shift_opt": (tot["opt"] - tot["none"]) / max(shifts, 1),
        "kg_per_shift_current": (tot["current"] - tot["none"]) / max(shifts, 1),
        "vol_coef": b.round(4).tolist(),
    }
    return s, summary


def extra_steps(s: pd.DataFrame, b: np.ndarray, alt_scale: float = 0.5) -> pd.DataFrame:
    """Дополнительные смены сверх рекомендованной расстановки — в порядке убывания прироста.

    s — таблица из compare (base_kg, v_opt). Кандидаты — «слот × k-й волонтёр» для k > v_opt.
    Внутри слота приросты убывают по k, а рекомендованная расстановка в каждом (город, день) —
    это лучшие кандидаты при её бюджете. Поэтому первые N строк — точный максимум прироста
    при N новых сменах по всей сети. gain_alt_kg — прирост тех же смен, если эффект волонтёра
    в alt_scale раз от оценённого (осторожный сценарий). Если в s есть base_alt_kg — сбор без волонтёров
    в этом сценарии, — прирост считается от него.
    """
    m = multiplier(np.arange(len(b) + 1), b)
    ma = multiplier(np.arange(len(b) + 1), b * alt_scale)
    s = s if "base_alt_kg" in s else s.assign(base_alt_kg=s["base_kg"])
    rows = []
    for k in range(1, len(b) + 1):
        g = s.loc[s["v_opt"] < k, ["store_id", "date", "city", "base_kg", "base_alt_kg"]].copy()
        g["k"] = k
        g["gain_kg"] = g["base_kg"] * (m[k] - m[k - 1])
        g["gain_alt_kg"] = g["base_alt_kg"] * (ma[k] - ma[k - 1])
        rows.append(g)
    c = pd.concat(rows, ignore_index=True)
    c = c[c["gain_kg"] > 0]
    return c.sort_values(["gain_kg", "k"], ascending=[False, True], kind="stable").reset_index(drop=True)


def shifts_for_target(steps: pd.DataFrame, start_kg: float, target_kg: float) -> int | None:
    """Сколько новых смен нужно, чтобы ожидаемый сбор дошёл до цели; None — недостижимо."""
    if target_kg <= start_kg:
        return 0
    cum = start_kg + steps["gain_kg"].cumsum().to_numpy()
    i = int(np.searchsorted(cum, target_kg))
    return i + 1 if i < len(cum) else None


def city_summary(s: pd.DataFrame) -> pd.DataFrame:
    g = s.groupby("city").agg(stores=("store_id", "nunique"), shifts=("v_opt", "sum"),
                              kg_current=("kg_current", "sum"), kg_opt=("kg_opt", "sum"))
    g["uplift"] = g["kg_opt"] / g["kg_current"] - 1
    return g.sort_values("kg_opt", ascending=False)
