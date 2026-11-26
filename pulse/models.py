"""Модели прогноза сбора на магазин за акцию.

Все модели получают историю (`train`, строки «магазин × акция» с kg) и план
следующей акции (`plan`, те же признаки без kg) и возвращают прогноз kg.
Код намеренно простой (numpy), чтобы его можно было перенести в браузер.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import design


def _order(train: pd.DataFrame) -> list[str]:
    return sorted(train["action_id"].unique())


def _cold_start(train: pd.DataFrame, plan: pd.DataFrame) -> np.ndarray:
    """Новый магазин: медиана сбора на магазин в его регионе за последнюю акцию, иначе по сети."""
    last = train[train["action_id"] == _order(train)[-1]]
    reg = last.groupby("region")["kg"].median()
    glob = last["kg"].median()
    return plan["region"].map(reg).fillna(glob).to_numpy(float)


class Naive:
    """Сколько магазин собрал в прошлую акцию, в которой участвовал."""
    name = "naive"

    def fit(self, train):
        self.train = train
        self.last = train.sort_values("action_id").groupby("store_id")["kg"].last()
        return self

    def predict(self, plan):
        y = plan["store_id"].map(self.last).to_numpy(float)
        return np.where(np.isnan(y), _cold_start(self.train, plan), y)


class SeasonalNaive(Naive):
    """Сколько магазин собрал в тот же сезон годом раньше; если не было — как Naive."""
    name = "seasonal_naive"

    def predict(self, plan):
        base = super().predict(plan)
        hist = self.train.sort_values("action_id")
        same = hist[hist["season"].isin(plan["season"].unique())]
        last_same = same.groupby("store_id")["kg"].last()
        y = plan["store_id"].map(last_same).to_numpy(float)
        return np.where(np.isnan(y), base, y)


class SES(Naive):
    """Экспоненциальное сглаживание ряда магазина; alpha общая, подбирается по истории."""
    name = "ses"

    def fit(self, train, alphas=np.linspace(0.1, 0.9, 9)):
        self.train = train
        wide = train.pivot_table(index="store_id", columns="action_id", values="kg")
        best = None
        for a in alphas:
            err, lv = 0.0, None
            for col in wide.columns:
                y = wide[col].to_numpy()
                if lv is not None:
                    m = ~np.isnan(y) & ~np.isnan(lv)
                    err += np.abs(y[m] - lv[m]).sum()
                lv = np.where(np.isnan(y), lv if lv is not None else np.nan,
                              y if lv is None else np.where(np.isnan(lv), y, a * y + (1 - a) * lv))
            if best is None or err < best[0]:
                best = (err, a, lv)
        self.alpha = best[1]
        self.level = pd.Series(best[2], index=wide.index)
        return self

    def predict(self, plan):
        y = plan["store_id"].map(self.level).to_numpy(float)
        return np.where(np.isnan(y), _cold_start(self.train, plan), y)


def fit_poisson(X, y, offset=None, iters=50, penalty=None):
    """Квазипуассоновская регрессия (лог-связь) методом IRLS. y может быть нецелым (кг).

    penalty — вектор ridge-штрафов по коэффициентам (в единицах веса наблюдений):
    тянет коэффициент к нулю, пока данных о нём мало.
    """
    offset = np.zeros(len(y)) if offset is None else offset
    pen = np.full(X.shape[1], 1e-6) if penalty is None else np.asarray(penalty, float)
    beta = np.zeros(X.shape[1])
    beta[0] = np.log(max(y.mean(), 1e-9)) - offset.mean()
    for _ in range(iters):
        eta = np.clip(X @ beta + offset, -30, 30)
        mu = np.exp(eta)
        z = eta - offset + (y - mu) / mu
        XtW = X.T * mu
        new = np.linalg.solve(XtW @ X + np.diag(pen), XtW @ z)
        if np.max(np.abs(new - beta)) < 1e-8:
            beta = new
            break
        beta = new
    return beta


class GLMEB:
    """Лог-линейная модель (сезон, тренд, часы, дни недели, волонтёры, сеть, город)
    × эмпирико-байесовский множитель магазина, сжатый к множителю региона.

    Множитель магазина r = (Σy + κ·r_региона) / (Σμ + κ): у магазина с короткой
    историей прогноз ближе к региону, с длинной — к его собственному уровню.
    """
    name = "glm_eb"

    def __init__(self, kappa=None, kappas=(10, 25, 50, 100, 200, 400), rounds=3):
        self.kappa, self.kappas, self.rounds = kappa, kappas, rounds

    # Сезон и тренд оцениваются по считаным акциям, поэтому их коэффициенты сжимаются
    # к нулю априорным штрафом: вес априорного знания = PRIOR_WEIGHT × суммарный сбор.
    PRIOR_WEIGHT = 0.05

    def _penalty(self, names, y):
        lam = self.PRIOR_WEIGHT * y.sum()
        return np.array([lam if (n.startswith("season_") or n == "t_years") else 1e-6 for n in names])

    def _fit_core(self, train, kappa):
        X, self.names = design(train)
        y = train["kg"].to_numpy(float)
        pen = self._penalty(self.names, y)
        log_r = np.zeros(len(train))
        for _ in range(self.rounds):
            beta = fit_poisson(X, y, offset=log_r, penalty=pen)
            mu = np.exp(X @ beta)
            d = train.assign(mu=mu)
            reg = d.groupby("region").agg(y=("kg", "sum"), mu=("mu", "sum"))
            r_reg = (reg["y"] + kappa) / (reg["mu"] + kappa)
            st = d.groupby("store_id").agg(y=("kg", "sum"), mu=("mu", "sum"), region=("region", "first"))
            prior = st["region"].map(r_reg).fillna(1.0)
            r_st = (st["y"] + kappa * prior) / (st["mu"] + kappa)
            log_r = np.log(train["store_id"].map(r_st).to_numpy(float))
        return beta, r_reg, r_st

    def fit(self, train):
        acts = _order(train)
        if self.kappa is None:
            # κ подбираем на последней акции истории: учим на предыдущих, проверяем на ней
            if len(acts) >= 3:
                inner_tr, inner_te = train[train["action_id"] < acts[-1]], train[train["action_id"] == acts[-1]]
                scores = []
                for k in self.kappas:
                    b, rr, rs = self._fit_core(inner_tr, k)
                    p = self._predict_with(inner_te, b, rr, rs)
                    scores.append(np.abs(inner_te["kg"].to_numpy() - p).sum())
                self.kappa_ = self.kappas[int(np.argmin(scores))]
            else:
                self.kappa_ = 50
        else:
            self.kappa_ = self.kappa
        self.beta, self.r_reg, self.r_st = self._fit_core(train, self.kappa_)
        return self

    def _predict_with(self, plan, beta, r_reg, r_st):
        X, _ = design(plan)
        r = plan["store_id"].map(r_st)
        r = r.fillna(plan["region"].map(r_reg)).fillna(1.0).to_numpy(float)
        return np.exp(X @ beta) * r

    def predict(self, plan):
        return self._predict_with(plan, self.beta, self.r_reg, self.r_st)

    def coef(self) -> dict:
        return dict(zip(self.names, np.round(self.beta, 4)))


MODELS = (Naive, SeasonalNaive, SES, GLMEB)
