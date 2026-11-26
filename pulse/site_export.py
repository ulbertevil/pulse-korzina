"""Сборка компактного JSON для статического дашборда (site/data/dashboard.json)."""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PORTIONS = [  # data/facts.csv: set_weight_kg, portion_wrap_g, portion_fa_g, portion_tgtg_g
    {"id": "sets", "label": "наборов по 6 кг", "kg": 6.0, "fact": "set_weight_kg"},
    {"id": "wrap", "label": "порций WRAP (420 г)", "kg": 0.42, "fact": "portion_wrap_g"},
    {"id": "fa", "label": "порций Feeding America (544 г)", "kg": 0.544, "fact": "portion_fa_g"},
    {"id": "tgtg", "label": "порций Too Good To Go (1 кг)", "kg": 1.0, "fact": "portion_tgtg_g"},
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

    names = {"glm_eb": "GLM + эмпирический Байес", "ses": "Экспоненциальное сглаживание",
             "seasonal_naive": "Сезонная наивная", "naive": "Наивная («как в прошлый раз»)"}
    models = [{"id": m, "name": names.get(m, m), "wape": _r(r.wape, 4), "network_ape": _r(r.network_ape, 4),
               "vs_naive": _r(r.wape_vs_naive, 4)} for m, r in summ.iterrows()]

    last_id = preds["action_id"].max()
    last = preds[preds["action_id"] == last_id].copy()
    last["short"] = last["kg"] - last["pred"]
    below = last[last["kg"] < last["lo80"]].sort_values("short")
    below_rows = [{"city": city.get(r.store_id, ""), "address": addr.get(r.store_id, ""), "kg": _r(r.kg),
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
                "power_at_mde": des["check_power_at_mde"]["reject_rate"], "calibrated_on": des["calibrated_on"]})

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
        (out_dir / name).write_bytes(src.read_bytes())
