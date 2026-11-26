"""Выгрузка фонда «магазин × дата × кг» → строки «магазин × акция» для модели.

Это эталонная реализация того, что делает сайт в браузере (site/model.js);
тест tests/test_js_parity.py сверяет их результаты.

Формат выгрузки (CSV, одна строка — магазин в один день акции):
    магазин            — ID или адрес магазина (обязательно)
    дата               — 2026-11-20 или 20.11.2026 (обязательно)
    кг                 — сколько собрано (обязательно)
    начало, конец      — часы работы точки, например 16 и 20 (по умолчанию 4 часа)
    волонтёров_в_час   — сколько волонтёров стояло в среднем (необязательно)
    город, регион, сеть — необязательно
Дни, между которыми больше 7 дней, относятся к разным акциям.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import SEASON_OF_MONTH, VOL_LEVELS
from .site_export import short_address

ACTION_GAP_DAYS = 7
DEFAULT_HOURS = 4.0


def detect_actions(dates: pd.Series) -> pd.Series:
    """Дата → ID акции (первая дата акции). Новая акция — после перерыва больше 7 дней."""
    u = sorted(pd.to_datetime(dates).dt.normalize().unique())
    ids, cur, prev = {}, None, None
    for d in u:
        if prev is None or (d - prev).days > ACTION_GAP_DAYS:
            cur = d.strftime("%Y-%m-%d")
        ids[d] = cur
        prev = d
    return pd.to_datetime(dates).dt.normalize().map(ids)


def aggregate_export(df: pd.DataFrame) -> pd.DataFrame:
    """Нормализованная выгрузка (колонки store, date, kg, [start, end, volunteers, city, region, chain])."""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    hours = (d["end"] - d["start"]) if {"start", "end"} <= set(d) else pd.Series(np.nan, index=d.index)
    d["hours"] = hours.where(hours > 0).fillna(DEFAULT_HOURS).astype(float)
    vol = d["volunteers"] if "volunteers" in d else pd.Series(0.0, index=d.index)
    d["vol"] = np.floor(vol.fillna(0).astype(float) + 0.5)  # как Math.round в JS
    for k in VOL_LEVELS:
        d[f"v{k}h"] = (d["vol"] >= k) * d["hours"]
    d["wd"] = d["date"].dt.day_of_week
    for wd, name in ((3, "thu"), (5, "sat"), (6, "sun")):
        d[f"{name}h"] = (d["wd"] == wd) * d["hours"]
    for c in ("city", "region", "chain"):
        if c not in d:
            d[c] = ""
        d[c] = d[c].fillna("").astype(str)
    d["region"] = np.where(d["region"] == "", np.where(d["city"] == "", "все", d["city"]), d["region"])
    d["action_id"] = detect_actions(d["date"])

    g = d.groupby(["action_id", "store"]).agg(
        kg=("kg", "sum"), hours=("hours", "sum"), first_date=("date", "min"),
        city=("city", "first"), region=("region", "first"), chain=("chain", "first"),
        **{f"v{k}h": (f"v{k}h", "sum") for k in VOL_LEVELS},
        thuh=("thuh", "sum"), sath=("sath", "sum"), sunh=("sunh", "sum"),
    ).reset_index().rename(columns={"store": "store_id"})
    for k in VOL_LEVELS:
        g[f"v{k}"] = g[f"v{k}h"] / g["hours"]
    for name in ("thu", "sat", "sun"):
        g[f"share_{name}"] = g[f"{name}h"] / g["hours"]
    city_stores = d.groupby("city")["store"].nunique()
    g["city_stores"] = g["city"].map(city_stores).fillna(1).astype(float)
    g["season"] = g["first_date"].dt.month.map(SEASON_OF_MONTH)
    start = g["first_date"].min()
    g["t_years"] = (g["first_date"] - start).dt.days / 365.25
    helper = [f"v{k}h" for k in VOL_LEVELS] + ["thuh", "sath", "sunh"]
    return g.drop(columns=helper)


def next_plan(agg: pd.DataFrame, next_date: str) -> pd.DataFrame:
    """План следующей акции: магазины последней акции с их часами и волонтёрами; сезон и тренд — по дате."""
    last = agg[agg["action_id"] == agg["action_id"].max()].copy()
    t = pd.Timestamp(next_date)
    last["action_id"] = next_date
    last["first_date"] = t
    last["season"] = SEASON_OF_MONTH[t.month]
    last["t_years"] = (t - agg["first_date"].min()).days / 365.25
    return last


def store_labels(stores: pd.DataFrame) -> pd.Series:
    """store_id → «Город, улица, дом»; если в одном доме два магазина — добавляем начало ID."""
    lab = stores["city"] + ", " + stores["address"].map(short_address)
    dup = lab.duplicated(keep=False)
    lab[dup] = lab[dup] + " · " + stores.loc[dup, "store_id"].str[:4]
    return pd.Series(lab.to_numpy(), index=stores["store_id"].to_numpy())


def demo_export(hourly: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """Синтетика в формате выгрузки: строка на магазин и день."""
    g = hourly.groupby(["store_id", "date"]).agg(
        start=("hour", "min"), end=("hour", "max"), volunteers=("volunteers", "mean"), kg=("kg", "sum")).reset_index()
    g["end"] += 1
    g = g.merge(stores[["store_id", "city", "region", "chain"]], on="store_id")
    g["store_id"] = g["store_id"].map(store_labels(stores))
    g["volunteers"] = g["volunteers"].round(2)
    g["kg"] = g["kg"].round(2)
    return g.rename(columns={"store_id": "магазин", "city": "город", "region": "регион", "chain": "сеть",
                             "date": "дата", "start": "начало", "end": "конец",
                             "volunteers": "волонтёров_в_час", "kg": "кг"})[
        ["магазин", "город", "регион", "сеть", "дата", "начало", "конец", "волонтёров_в_час", "кг"]]


RU = {"магазин": "store", "город": "city", "регион": "region", "сеть": "chain", "дата": "date",
      "начало": "start", "конец": "end", "волонтёров_в_час": "volunteers", "кг": "kg"}
