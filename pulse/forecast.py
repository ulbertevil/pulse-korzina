"""Прогноз следующей акции: план «магазин × день × час» → кг с интервалами."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest, features
from .models import GLMEB


def plan_from_slots(slots: pd.DataFrame, dates: list[str], action_id: str,
                    volunteers: pd.Series | float = 0.0) -> pd.DataFrame:
    """Расписание магазинов → почасовой план новой акции.

    Дни магазина по порядку переносятся на `dates` (лишние дни отбрасываются).
    `volunteers` — число волонтёров в час: одно число или Series по store_id.
    """
    rows = []
    for sid, g in slots.sort_values(["store_id", "date", "start"]).groupby("store_id"):
        for (_, r), d in zip(g.iterrows(), dates):
            for h in range(int(np.floor(r.start)), int(np.ceil(r.end))):
                rows.append((action_id, sid, d, h))
    plan = pd.DataFrame(rows, columns=["action_id", "store_id", "date", "hour"])
    if isinstance(volunteers, pd.Series):
        plan["volunteers"] = plan["store_id"].map(volunteers).fillna(0).round().astype(int)
    else:
        plan["volunteers"] = int(round(volunteers))
    return plan


def forecast(history: pd.DataFrame, plan_agg: pd.DataFrame, net_log_sd: float) -> tuple[pd.DataFrame, dict]:
    """Обучить GLMEB на всей истории и спрогнозировать план. Возвращает (магазины, итог)."""
    model = GLMEB().fit(history)
    p = model.predict(plan_agg)
    q = backtest.store_ratio_quantiles(history)
    out = plan_agg[["action_id", "store_id", "region", "city", "chain", "hours", "vol_hours"]].assign(
        pred_kg=p, lo80=p * q[0.10], hi80=p * q[0.90], lo95=p * q[0.025], hi95=p * q[0.975])
    total = float(p.sum())
    summary = {
        "action_id": str(plan_agg["action_id"].iloc[0]),
        "stores": int(len(plan_agg)),
        "pred_kg": total,
        "lo80_kg": total * float(np.exp(-1.2816 * net_log_sd)),
        "hi80_kg": total * float(np.exp(1.2816 * net_log_sd)),
        "lo95_kg": total * float(np.exp(-1.96 * net_log_sd)),
        "hi95_kg": total * float(np.exp(1.96 * net_log_sd)),
        "net_log_sd": net_log_sd,
        "kappa": model.kappa_,
        "coef": {k: float(v) for k, v in model.coef().items()},
    }
    return out, summary


def network_log_sd(res: pd.DataFrame) -> float:
    """Разброс ошибки суммы по сети по шагам бэктеста (RMS лог-ошибки)."""
    g = res[res["model"] == "glm_eb"]
    err = np.log(g["net_true"] / g["net_pred"])
    return float(np.sqrt(np.mean(np.square(err)))) if len(err) >= 2 else backtest.PRIOR_NET_LOG_SD


def kg_to_people(kg: float, set_kg: float = 6.0) -> dict:
    """Килограммы → наборы (≈6 кг, оценка из facts.csv: set_weight_kg)."""
    return {"sets": kg / set_kg}


__all__ = ["plan_from_slots", "forecast", "network_log_sd", "kg_to_people", "features"]
