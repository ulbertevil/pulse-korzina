"""Дизайн и анализ A/B-эксперимента на магазинах акции.

Пример вопроса: «Даёт ли второй волонтёр в магазине прирост, и какой?»
или «Работает ли новая табличка у короба?». Единица рандомизации — магазин,
метрика — кг за акцию.

Что сокращает нужную выборку:
- CUPED: вычитаем из метрики то, что объясняется ковариатой до эксперимента
  (прогноз модели или сбор в прошлую акцию); дисперсия падает в (1 − ρ²) раз.
- Стратификация: рандомизируем внутри групп похожих магазинов, поэтому
  тест и контроль сбалансированы по сети и размеру магазина.
Одна акция — одно измерение, поэтому проблемы подглядывания нет: результат
смотрим один раз после акции.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

def z(p: float) -> float:
    """Квантиль нормального распределения — та же формула, что в site/app.js, чтобы README и сайт совпадали."""
    return _norm_ppf(p)


def _norm_ppf(p: float) -> float:
    """Обратная функция нормального распределения (Acklam), без scipy."""
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690,
         -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572]
    c = [-7.784894002430293e-03, -0.3223964580411365, -2.400758277161838, -2.549732539343734,
         4.374664141464968, 2.938163982698783]
    d = [7.784695709041462e-03, 0.3224671290700398, 2.445134137142996, 3.754408661907416]
    lo = 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > 1 - lo:
        return -_norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2))


# --- дисперсия и мощность ---------------------------------------------------

def strata(df: pd.DataFrame, covariate: str = "pred", n_bins: int = 10, by: tuple[str, ...] = ("chain",)) -> pd.Series:
    """Страта = сеть × дециль ковариаты (ожидаемого сбора)."""
    q = pd.qcut(df[covariate].rank(method="first"), n_bins, labels=False)
    parts = [df[c].astype(str) for c in by] + [q.astype(str)]
    return pd.Series(["|".join(t) for t in zip(*parts)], index=df.index, name="stratum")


def residual_sd(df: pd.DataFrame, y: str = "kg", covariate: str = "pred", stratum: pd.Series | None = None) -> dict:
    """Стандартное отклонение метрики: как есть, после CUPED и после CUPED внутри страт."""
    yv, xv = df[y].to_numpy(float), df[covariate].to_numpy(float)
    theta = np.cov(yv, xv)[0, 1] / np.var(xv, ddof=1)
    cuped = yv - theta * (xv - xv.mean())
    out = {"mean": float(yv.mean()), "sd_raw": float(yv.std(ddof=1)), "sd_cuped": float(cuped.std(ddof=1)),
           "rho": float(np.corrcoef(yv, xv)[0, 1]), "theta": float(theta)}
    if stratum is not None:
        resid = cuped - pd.Series(cuped, index=df.index).groupby(stratum).transform("mean").to_numpy()
        n, k = len(resid), stratum.nunique()
        out["sd_cuped_strata"] = float(np.sqrt((resid ** 2).sum() / (n - k)))
    return out


def mde(sd: float, mean: float, n_test: int, n_control: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Минимальный обнаружимый эффект (доля от среднего), двусторонний тест."""
    se = sd * math.sqrt(1 / n_test + 1 / n_control)
    return (z(1 - alpha / 2) + z(power)) * se / mean


def sample_size(sd: float, mean: float, effect: float, share_test: float = 0.5,
                alpha: float = 0.05, power: float = 0.8) -> int:
    """Сколько магазинов всего нужно, чтобы увидеть относительный эффект `effect`."""
    k = (z(1 - alpha / 2) + z(power)) * sd / (effect * mean)
    n = k ** 2 * (1 / share_test + 1 / (1 - share_test))
    return int(math.ceil(n))


# --- рандомизация -----------------------------------------------------------

def assign(df: pd.DataFrame, stratum: pd.Series, share_test: float = 0.5, seed: int = 20261210) -> pd.Series:
    """Стратифицированная рандомизация: внутри каждой страты доля теста ≈ share_test."""
    rng = np.random.default_rng(seed)
    group = pd.Series("control", index=df.index, name="group")
    for _, idx in stratum.groupby(stratum).groups.items():
        idx = np.array(list(idx))
        rng.shuffle(idx)
        n_t = int(np.floor(len(idx) * share_test + rng.random()))  # честное округление
        group.loc[idx[:n_t]] = "test"
    return group


# --- анализ -----------------------------------------------------------------

def analyze(df: pd.DataFrame, y: str = "kg", group: str = "group", covariate: str = "pred",
            stratum: pd.Series | None = None, alpha: float = 0.05) -> dict:
    """Оценка эффекта регрессией y ~ тест + ковариата (+ страты) с робастной ошибкой (HC1).

    Это то же, что CUPED, плюс поправка на страты. Эффект — в кг на магазин
    и в процентах от среднего контроля.
    """
    t = (df[group] == "test").to_numpy(float)
    cols = [np.ones(len(df)), t, df[covariate].to_numpy(float) - df[covariate].mean()]
    if stratum is not None:
        dummies = pd.get_dummies(stratum, drop_first=True, dtype=float)
        cols += [dummies[c].to_numpy() for c in dummies.columns]
    X = np.column_stack(cols)
    yv = df[y].to_numpy(float)
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ yv
    e = yv - X @ beta
    n, k = X.shape
    meat = (X * (e ** 2)[:, None]).T @ X
    cov = XtX_inv @ meat @ XtX_inv * n / (n - k)
    est, se = float(beta[1]), float(math.sqrt(cov[1, 1]))
    base = float(yv[t == 0].mean())
    zc = z(1 - alpha / 2)
    p = 2 * norm_sf(abs(est / se))
    return {"effect_kg": est, "se_kg": se, "ci_kg": (est - zc * se, est + zc * se),
            "effect_rel": est / base, "ci_rel": ((est - zc * se) / base, (est + zc * se) / base),
            "p_value": p, "significant": p < alpha, "n_test": int(t.sum()), "n_control": int((1 - t).sum()),
            "control_mean": base}


def simulate(df: pd.DataFrame, effect: float, n_sims: int = 200, y: str = "kg", covariate: str = "pred",
             share_test: float = 0.5, alpha: float = 0.05, seed: int = 1) -> dict:
    """Проверка дизайна на прошлой акции: доля «значимых» результатов.

    effect = 0 — A/A-тест: доля должна быть ≈ alpha. effect > 0 — мощность.
    Эффект добавляется мультипликативно к сбору магазинов теста.
    """
    st = strata(df, covariate)
    hits, ests = 0, []
    for i in range(n_sims):
        g = assign(df, st, share_test, seed=seed + i)
        d = df.assign(group=g)
        d[y] = np.where(g == "test", d[y] * (1 + effect), d[y])
        r = analyze(d, y=y, covariate=covariate, stratum=st, alpha=alpha)
        hits += r["significant"]
        ests.append(r["effect_rel"])
    return {"effect": effect, "reject_rate": hits / n_sims, "mean_estimate": float(np.mean(ests)), "n_sims": n_sims}


def design(df: pd.DataFrame, y: str = "kg", covariate: str = "pred", share_test: float = 0.5,
           alpha: float = 0.05, power: float = 0.8, effects=(0.05, 0.10, 0.20)) -> dict:
    """Сводка дизайна: MDE при разных методах и нужное число магазинов."""
    st = strata(df, covariate)
    sd = residual_sd(df, y, covariate, st)
    n = len(df)
    n_t = int(round(n * share_test))
    n_c = n - n_t
    out = {"stores": n, "n_test": n_t, "n_control": n_c, "alpha": alpha, "power": power, **sd,
           "mde": {m: mde(sd[f"sd_{m}"], sd["mean"], n_t, n_c, alpha, power) for m in ("raw", "cuped", "cuped_strata")},
           "stores_needed": {f"{int(e*100)}%": {m: sample_size(sd[f"sd_{m}"], sd["mean"], e, share_test, alpha, power)
                                                for m in ("raw", "cuped", "cuped_strata")} for e in effects}}
    return out
