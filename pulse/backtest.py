"""Бэктест скользящим окном: учим на акциях до t, прогнозируем акцию t.

Интервалы — эмпирические: множители y/ŷ на последней акции истории
(прогноз по ещё более ранним) дают квантили для магазина; ошибка суммы по
сети берётся из прошлых шагов бэктеста (до двух шагов — априорные 15%).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .models import MODELS, GLMEB

Q80, Q95 = (0.10, 0.90), (0.025, 0.975)
PRIOR_NET_LOG_SD = 0.15  # допущение до появления собственной истории ошибок


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    tot_y, tot_p = y.sum(), p.sum()
    return {
        "wape": np.abs(y - p).sum() / tot_y,
        "network_ape": abs(tot_p - tot_y) / tot_y,
        "bias": tot_p / tot_y - 1,
        "mape_store": np.mean(np.abs(y - p) / np.maximum(y, 1.0)),
    }


def store_ratio_quantiles(train: pd.DataFrame, model_cls=GLMEB) -> dict:
    """Квантили y/ŷ на последней акции истории — для интервалов магазина."""
    acts = sorted(train["action_id"].unique())
    if len(acts) < 3:
        return {q: v for q, v in zip(Q80 + Q95, (0.6, 1.5, 0.4, 2.0))}
    tr, te = train[train["action_id"] < acts[-1]], train[train["action_id"] == acts[-1]]
    m = model_cls().fit(tr)
    ratio = te["kg"].to_numpy() / m.predict(te)
    return {q: float(np.quantile(ratio, q)) for q in Q80 + Q95}


def run(data: pd.DataFrame, min_train: int = 3, models=MODELS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Вернуть (метрики по шагам и моделям, прогнозы магазинов лучшей модели)."""
    acts = sorted(data["action_id"].unique())
    rows, preds, net_log_err = [], [], []
    for i in range(min_train, len(acts)):
        target = acts[i]
        train, test = data[data["action_id"] < target], data[data["action_id"] == target]
        y = test["kg"].to_numpy(float)
        for cls in models:
            m = cls().fit(train)
            p = m.predict(test)
            rows.append({"target": target, "model": cls.name, "n_stores": len(test), **metrics(y, p)})
            if cls is GLMEB:
                q = store_ratio_quantiles(train)
                sd = np.sqrt(np.mean(np.square(net_log_err))) if len(net_log_err) >= 2 else PRIOR_NET_LOG_SD
                tot_p = p.sum()
                rows[-1].update({
                    "cover80": np.mean((y >= p * q[Q80[0]]) & (y <= p * q[Q80[1]])),
                    "cover95": np.mean((y >= p * q[Q95[0]]) & (y <= p * q[Q95[1]])),
                    "net_pred": tot_p, "net_true": y.sum(),
                    "net_lo95": tot_p * np.exp(-1.96 * sd), "net_hi95": tot_p * np.exp(1.96 * sd),
                    "kappa": m.kappa_,
                })
                net_log_err.append(np.log(y.sum() / tot_p))
                preds.append(test[["action_id", "store_id"]].assign(
                    kg=y, pred=p, lo80=p * q[Q80[0]], hi80=p * q[Q80[1]]))
    return pd.DataFrame(rows), pd.concat(preds, ignore_index=True)


def summary(res: pd.DataFrame) -> pd.DataFrame:
    """Средние метрики по моделям и выигрыш к наивной модели."""
    s = res.groupby("model")[["wape", "network_ape", "bias", "mape_store"]].mean()
    s["wape_vs_naive"] = s["wape"] / s.loc["naive", "wape"] - 1
    return s.sort_values("wape")
