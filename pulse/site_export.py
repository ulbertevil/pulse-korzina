"""Сборка компактного JSON для статического дашборда (site/data/dashboard.json)."""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PORTIONS = [  # data/facts.csv: set_weight_kg; kd_rkk_year_kg / kd_rkk_year_sets (70 т ≈ 17 500 наборов)
    {"id": "sets", "label": "наборов по 6 кг", "kg": 6.0, "fact": "set_weight_kg"},
    {"id": "sets4", "label": "наборов по 4 кг (как в отчёте РКК)", "kg": 4.0, "fact": "kd_rkk_year_sets"},
]


def short_address(addr: str) -> str:
    """«655017, Хакасия респ., Абакан г., Ленина пр-кт, Дом 56, помещение 146Н» → «Ленина пр-кт, 56»."""
    parts = [p.strip() for p in str(addr).split(",")]
    parts = [p for p in parts if not re.fullmatch(r"\d{6}", p)]
    street_i = next((i for i, p in enumerate(parts)
                     if re.search(r"(ул|пр-кт|пер|ш|б-р|пл|наб|мкр|проезд|туп|линия|аллея|кв-л)\.?$", p)), None)
    if street_i is None:
        return ", ".join(parts[-2:])
    out = [parts[street_i]]
    if street_i + 1 < len(parts):
        out.append(re.sub(r"^(дом|д\.)\s*", "", parts[street_i + 1], flags=re.I))
    return ", ".join(out)


def _r(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def build(rep: Path, stores: pd.DataFrame, hourly_plan: pd.DataFrame, total: dict, alloc: pd.DataFrame,
          alloc_sum: dict, cities: pd.DataFrame, res: pd.DataFrame, summ: pd.DataFrame,
          preds: pd.DataFrame, des: dict, facts_path: Path) -> dict:
    addr = stores.set_index("store_id")["address"].map(short_address)
    city = stores.set_index("store_id")["city"]
    sd = total["net_log_sd"]

    # почасовая кривая по сети
    h = hourly_plan.groupby(["date", "hour"])["kg"].sum().reset_index()
    hourly = [{"date": r.date, "hour": int(r.hour), "kg": _r(r.kg),
               "lo80": _r(r.kg * np.exp(-1.2816 * sd)), "hi80": _r(r.kg * np.exp(1.2816 * sd))}
              for r in h.itertuples()]

    glm = res[res["model"] == "glm_eb"]
    steps = []
    for r in glm.itertuples():
        naive = res[(res["model"] == "naive") & (res["target"] == r.target)]
        naive_pred = float(r.net_true * (1 + naive["bias"].iloc[0]))
        steps.append({"action": r.target, "true": _r(r.net_true, 0), "pred": _r(r.net_pred, 0),
                      "lo95": _r(r.net_lo95, 0), "hi95": _r(r.net_hi95, 0), "naive": _r(naive_pred, 0),
                      "wape": _r(r.wape, 4), "cover80": _r(r.cover80, 3), "cover95": _r(r.cover95, 3)})

    names = {"glm_eb": "Модель «Пульса»", "ses": "Сглаживание прошлых акций",
             "seasonal_naive": "Как в тот же сезон год назад", "naive": "Как в прошлый раз"}
    models = [{"id": m, "name": names.get(m, m), "wape": _r(r.wape, 4), "network_ape": _r(r.network_ape, 4),
               "vs_naive": _r(r.wape_vs_naive, 4)} for m, r in summ.iterrows()]

    last_id = preds["action_id"].max()
    last = preds[preds["action_id"] == last_id].copy()
    last["short"] = last["kg"] - last["pred"]
    below = last[last["kg"] < last["lo80"]].sort_values("short")
    # килограммы синтетические — реальные магазины нельзя называть отстающими: в демо вместо адреса код магазина
    below_rows = [{"city": city.get(r.store_id, ""), "address": f"магазин {r.store_id[:6]} (адрес скрыт в демо)", "kg": _r(r.kg),
                   "pred": _r(r.pred), "lo80": _r(r.lo80), "gap": _r(r.short)} for r in below.head(25).itertuples()]

    a = alloc.copy()
    a["address_short"] = a["store_id"].map(addr)
    top = a.sort_values("gain_first_per_vol_hour", ascending=False).head(25)
    ranking = [{"city": r.city, "address": r.address_short, "date": r.date, "time": f"{int(r.start)}–{int(r.end)}",
                "base_kg": _r(r.base_kg), "gain_per_vol_hour": _r(r.gain_first_per_vol_hour, 2),
                "v_current": int(r.v_current), "v_opt": int(r.v_opt)} for r in top.itertuples()]
    city_rows = [{"city": c, "stores": int(r.stores), "shifts": int(r.shifts), "kg_current": _r(r.kg_current, 0),
                  "kg_opt": _r(r.kg_opt, 0), "uplift": _r(r.uplift, 4)} for c, r in cities.head(30).iterrows()]

    with open(facts_path, encoding="utf-8") as f:
        facts = list(csv.DictReader(f))

    exp = {k: des[k] for k in ("stores", "mean", "sd_raw", "sd_cuped", "sd_cuped_strata", "rho", "alpha", "power")}
    exp.update({"mde": des["mde"], "stores_needed": des["stores_needed"], "aa": des["check_aa"]["reject_rate"],
                "power_at_mde": des["check_power_at_mde"]["reject_rate"], "calibrated_on": des["calibrated_on"],
                "days_per_store": _r(len(hourly_plan[["store_id", "date"]].drop_duplicates()) / max(total["stores"], 1), 2)})

    return {
        "meta": {"generated": date.today().isoformat(), "synthetic": True, "action": total["action_id"],
                 "dates": sorted(hourly_plan["date"].unique().tolist()), "stores": total["stores"],
                 "regions": int(stores["region"].nunique()), "cities": int(stores["city"].nunique()),
                 "source_table": "https://docs.google.com/spreadsheets/d/1EN_UUkJ4GrCLz2ytDwNJYG4o2xCyVzXEkNijITP6Z3w/"},
        "kpi": {"pred_kg": _r(total["pred_kg"], 0), "lo80": _r(total["lo80_kg"], 0), "hi80": _r(total["hi80_kg"], 0),
                "lo95": _r(total["lo95_kg"], 0), "hi95": _r(total["hi95_kg"], 0),
                "shifts": alloc_sum["shifts"], "uplift_vs_current": _r(alloc_sum["uplift_opt_vs_current"], 4),
                "uplift_vs_uniform": _r(alloc_sum["uplift_opt_vs_uniform"], 4),
                "kg_opt": _r(alloc_sum["kg"]["opt"], 0), "kg_current": _r(alloc_sum["kg"]["current"], 0),
                "kg_per_shift_current": _r(alloc_sum["kg_per_shift_current"], 2),
                "kg_per_shift_opt": _r(alloc_sum["kg_per_shift_opt"], 2)},
        "portions": PORTIONS,
        "hourly": hourly,
        "models": models,
        "steps": steps,
        "below": {"action": last_id, "count": int(len(below)), "of": int(len(last)), "rows": below_rows},
        "ranking": ranking,
        "cities": city_rows,
        "experiment": exp,
        "facts": facts,
    }


def write(out_dir: Path, data: dict, csv_files: dict[str, Path]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dashboard.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                            encoding="utf-8")
    for name, src in csv_files.items():
        if name in MACHINE_CSV:
            (out_dir / name).write_bytes(src.read_bytes())
        else:  # файлы для скачивания — так, чтобы русский Excel открыл их двойным щелчком
            excel_csv(pd.read_csv(src, dtype={"store_id": str}), out_dir / name)


MACHINE_CSV = {"demo_export.csv"}  # его читает сам сайт; остальные CSV — для людей


def excel_csv(df: pd.DataFrame, path: Path) -> None:
    """CSV для русского Excel: «;», десятичная запятая, UTF-8 с BOM."""
    df.to_csv(path, sep=";", decimal=",", float_format="%.6g", index=False, encoding="utf-8-sig")


COORD_FIELDS = ["city", "address", "chain", "date", "start", "end", "v_current", "v_opt", "kg_current", "kg_opt", "hi80"]


def coordinator(alloc: pd.DataFrame, per_store: pd.DataFrame, b=None, sigma: float = 0.0) -> dict:
    """План для координатора города: слоты «магазин × день» с людьми и ожидаемыми кг.

    hi80 — верхняя граница 80% интервала для слота (на сколько кг готовить тару):
    отношение hi80 / прогноз магазина переносится на слот.
    """
    ratio = (per_store["hi80"] / per_store["pred_kg"]).set_axis(per_store["store_id"])
    s = alloc.copy()
    s["hi80"] = s["kg_opt"] * s["store_id"].map(ratio).fillna(1.5)
    s["address"] = s["address"].map(short_address)
    s = s.sort_values(["city", "date", "start", "address"], kind="stable").reset_index(drop=True)
    rows = [[r.city, r.address, r.chain, r.date, int(r.start), int(r.end), int(r.v_current), int(r.v_opt),
             _r(r.kg_current), _r(r.kg_opt), _r(r.hi80)] for r in s.itertuples()]
    out = {"fields": COORD_FIELDS, "synthetic": True, "rows": rows}
    if b is not None:
        out["goal"] = goal(s, b, sigma)
    return out


def goal(s: pd.DataFrame, b, sigma: float) -> dict:
    """Данные для «Сколько людей нужно для цели»: новые смены по убыванию прироста.

    steps — [номер строки листа координатора, прирост кг × 10, прирост при эффекте вдвое меньше × 10].
    """
    from .allocate import extra_steps, multiplier
    alt = 0.5
    row = pd.Series(range(len(s)), index=pd.MultiIndex.from_frame(s[["store_id", "date"]]))
    # Осторожный сценарий: эффект волонтёра × alt. Уровень сбора привязан к публичной цифре фонда, поэтому
    # прогноз при нынешней расстановке не меняется — меняется только то, сколько из него «дают» люди:
    # сбор без волонтёров в сценарии = прогноз / множитель(нынешние люди, b × alt).
    b_alt = b * alt
    s = s.assign(base_alt_kg=s["kg_current"] / multiplier(s["v_current"].to_numpy(), b_alt))
    st = extra_steps(s, b, alt)
    idx = row.reindex(pd.MultiIndex.from_frame(st[["store_id", "date"]])).to_numpy()
    steps = [[int(i), int(round(g * 10)), int(round(ga * 10))]
             for i, g, ga in zip(idx, st["gain_kg"], st["gain_alt_kg"])]
    kg_alt = lambda v: float((s["base_alt_kg"] * multiplier(s[v].to_numpy(), b_alt)).sum())  # noqa: E731
    return {"kg_current": _r(s["kg_current"].sum()), "kg_opt": _r(s["kg_opt"].sum()),
            "kg_current_alt": _r(kg_alt("v_current")), "kg_opt_alt": _r(kg_alt("v_opt")),
            "shifts": int(s["v_opt"].sum()), "sigma": round(float(sigma), 4), "alt_scale": alt, "steps": steps}
