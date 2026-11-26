"""Агрегация «магазин × день × час» → «магазин × акция» и признаки модели."""
from __future__ import annotations

import numpy as np
import pandas as pd

SEASON_OF_MONTH = {3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer",
                   9: "autumn", 10: "autumn", 11: "november", 12: "november", 1: "november", 2: "spring"}
# Декабрьских акций в истории нет, поэтому декабрь моделируется как «ноябрьский» сезон — допущение.
SEASONS = ("spring", "summer", "autumn", "november")
VOL_LEVELS = (1, 2, 3)
START = pd.Timestamp("2025-03-13")


def aggregate(hourly: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """Свернуть часы в строку на магазин и акцию. kg может отсутствовать (план будущей акции)."""
    h = hourly.copy()
    d = pd.to_datetime(h["date"])
    h["wd"] = d.dt.day_of_week
    for lv in VOL_LEVELS:
        h[f"v{lv}"] = (h["volunteers"] >= lv).astype(float)
    agg = {"hour": "count", "date": "min", "volunteers": "sum",
           **{f"v{lv}": "mean" for lv in VOL_LEVELS}}
    if "kg" in h:
        agg["kg"] = "sum"
    g = h.groupby(["action_id", "store_id"]).agg(agg).rename(
        columns={"hour": "hours", "date": "first_date", "volunteers": "vol_hours"})
    wd_share = (h.groupby(["action_id", "store_id"])["wd"]
                .value_counts(normalize=True).unstack(fill_value=0.0))
    for wd, name in ((3, "thu"), (5, "sat"), (6, "sun")):
        g[f"share_{name}"] = wd_share[wd] if wd in wd_share else 0.0
    g = g.reset_index().merge(stores[["store_id", "region", "chain", "city", "city_stores"]],
                              on="store_id", how="left")
    fd = pd.to_datetime(g["first_date"])
    g["season"] = fd.dt.month.map(SEASON_OF_MONTH)
    g["t_years"] = (fd - START).dt.days / 365.25
    return g


def design(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Матрица признаков для лог-линейной модели."""
    cols, names = [np.ones(len(df))], ["const"]
    for s in SEASONS[1:]:
        cols.append((df["season"] == s).astype(float).to_numpy()); names.append(f"season_{s}")
    cols.append(df["t_years"].to_numpy(float)); names.append("t_years")
    cols.append(np.log(df["hours"].to_numpy(float))); names.append("log_hours")
    for c in ("share_thu", "share_sat", "share_sun"):
        cols.append(df[c].to_numpy(float)); names.append(c)
    for lv in VOL_LEVELS:
        cols.append(df[f"v{lv}"].to_numpy(float)); names.append(f"vol_ge{lv}")
    cols.append((df["chain"] == "Перекрёсток").astype(float).to_numpy()); names.append("chain_perekrestok")
    cols.append(np.log(df["city_stores"].to_numpy(float))); names.append("log_city_stores")
    return np.column_stack(cols), names
