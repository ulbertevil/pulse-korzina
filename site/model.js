/* Пульс «Корзины доброты»: модель прогноза в браузере.
 * Зеркало Python-кода (pulse/upload.py, pulse/features.py, pulse/models.py, pulse/backtest.py).
 * Совпадение результатов проверяет tests/test_js_parity.py.
 * Данные никуда не отправляются: всё считается на устройстве пользователя.
 */
(function (root) {
  "use strict";

  const SEASON_OF_MONTH = { 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "november", 12: "november", 1: "november", 2: "spring" };
  const SEASONS = ["spring", "summer", "autumn", "november"];
  const VOL_LEVELS = [1, 2, 3];
  const ACTION_GAP_DAYS = 7, DEFAULT_HOURS = 4, PRIOR_WEIGHT = 0.05, PRIOR_NET_LOG_SD = 0.15;
  const KAPPAS = [10, 25, 50, 100, 200, 400];
  const DAY = 86400000;

  // ---------- разбор CSV ----------
  function parseCSV(text) {
    text = text.replace(/^﻿/, "");
    const first = text.slice(0, text.indexOf("\n") + 1 || text.length);
    const counts = [";", ",", "\t"].map((d) => [d, first.split(d).length]);
    const delim = counts.sort((a, b) => b[1] - a[1])[0][0];
    const rows = [];
    let row = [], field = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
        else field += c;
      } else if (c === '"') q = true;
      else if (c === delim) { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); field = "";
        if (row.some((v) => v.trim() !== "")) rows.push(row);
        row = [];
      } else field += c;
    }
    if (field !== "" || row.length) { row.push(field); if (row.some((v) => v.trim() !== "")) rows.push(row); }
    return { delim, header: rows[0] || [], rows: rows.slice(1) };
  }

  const SYNONYMS = {
    store: ["магазин", "store", "store_id", "id магазина", "код магазина", "адрес", "address"],
    date: ["дата", "date", "день"],
    kg: ["кг", "kg", "вес", "собрано", "собрано, кг", "собрано кг", "вес, кг", "вес кг"],
    start: ["начало", "start", "с"],
    end: ["конец", "end", "до"],
    hours: ["часы", "hours", "часов"],
    volunteers: ["волонтёров_в_час", "волонтеров_в_час", "волонтёры", "волонтеры", "волонтёров", "волонтеров", "volunteers"],
    city: ["город", "city", "населённый пункт", "населенный пункт"],
    region: ["регион", "region", "субъект"],
    chain: ["сеть", "тс", "chain", "формат"],
  };
  const norm = (s) => String(s).trim().toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ");

  function mapColumns(header) {
    const idx = {};
    const h = header.map(norm);
    for (const [key, names] of Object.entries(SYNONYMS)) {
      const i = h.findIndex((x) => names.map(norm).includes(x));
      if (i >= 0) idx[key] = i;
    }
    return idx;
  }

  function parseNum(v) {
    if (v == null) return NaN;
    const s = String(v).trim().replace(/\s/g, "").replace(",", ".");
    return s === "" ? NaN : Number(s);
  }
  function parseDate(v) {
    const s = String(v).trim();
    let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) return okDate(+m[1], +m[2], +m[3]);
    m = s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{2,4})/);
    if (m) { const y = +m[3] < 100 ? 2000 + +m[3] : +m[3]; return okDate(y, +m[2], +m[1]); }
    return NaN;
  }
  /** Дата существует: 31.02 или месяц 13 (американский порядок «12/31») — не дата, строка пропускается с причиной. */
  function okDate(y, mo, d) {
    const t = Date.UTC(y, mo - 1, d);
    return mo >= 1 && mo <= 12 && new Date(t).getUTCDate() === d ? t : NaN;
  }
  /** Час: «16», «16:00», «16:30» → 16, 16, 16.5. */
  function parseHour(v) {
    const m = String(v ?? "").trim().match(/^(\d{1,2})[:.](\d{2})(?::\d{2})?$/);
    return m ? +m[1] + +m[2] / 60 : parseNum(v);
  }
  const iso = (t) => new Date(t).toISOString().slice(0, 10);

  /** Текст CSV → записи «магазин × день» и отчёт о проверке. */
  function readExport(text) {
    const { header, rows, delim } = parseCSV(text);
    const col = mapColumns(header);
    const missing = ["store", "date", "kg"].filter((k) => !(k in col));
    const report = { delim, rows: rows.length, columns: Object.keys(col), missing, skipped: 0, reasons: {} };
    if (missing.length) return { records: [], report };
    const skip = (why) => { report.skipped++; report.reasons[why] = (report.reasons[why] || 0) + 1; };
    const records = [];
    for (const r of rows) {
      const store = (r[col.store] || "").trim();
      const date = parseDate(r[col.date]);
      const kg = parseNum(r[col.kg]);
      if (!store) { skip("нет магазина"); continue; }
      if (Number.isNaN(date)) { skip("дата не распознана"); continue; }
      if (Number.isNaN(kg) || kg < 0) { skip("кг не число"); continue; }
      let hours = NaN;
      if ("start" in col && "end" in col) hours = parseHour(r[col.end]) - parseHour(r[col.start]);
      else if ("hours" in col) hours = parseNum(r[col.hours]);
      records.push({
        store, date, kg, hours: hours > 0 ? hours : DEFAULT_HOURS,
        vol: "volunteers" in col ? (Number.isNaN(parseNum(r[col.volunteers])) ? 0 : parseNum(r[col.volunteers])) : 0,
        city: "city" in col ? (r[col.city] || "").trim() : "",
        region: "region" in col ? (r[col.region] || "").trim() : "",
        chain: "chain" in col ? (r[col.chain] || "").trim() : "",
      });
    }
    report.used = records.length;
    report.hasVolunteers = "volunteers" in col;
    report.hasHours = ("start" in col && "end" in col) || "hours" in col;
    return { records, report };
  }

  // ---------- агрегация «магазин × акция» ----------
  function detectActions(dates) {
    const u = [...new Set(dates)].sort((a, b) => a - b);
    const ids = new Map();
    let cur = null, prev = null;
    for (const d of u) {
      if (prev === null || (d - prev) / DAY > ACTION_GAP_DAYS) cur = iso(d);
      ids.set(d, cur);
      prev = d;
    }
    return ids;
  }

  function aggregate(records) {
    const act = detectActions(records.map((r) => r.date));
    const cityStores = new Map();
    for (const r of records) {
      if (!cityStores.has(r.city)) cityStores.set(r.city, new Set());
      cityStores.get(r.city).add(r.store);
    }
    const g = new Map();
    for (const r of records) {
      const a = act.get(r.date), key = a + "\u0000" + r.store;
      let o = g.get(key);
      if (!o) {
        const region = r.region || r.city || "все";
        o = { action_id: a, store_id: r.store, kg: 0, hours: 0, first: r.date, city: r.city, region, chain: r.chain,
          vh: [0, 0, 0], thu: 0, sat: 0, sun: 0 };
        g.set(key, o);
      }
      o.kg += r.kg; o.hours += r.hours; if (r.date < o.first) o.first = r.date;
      const v = Math.round(r.vol);
      VOL_LEVELS.forEach((k, i) => { if (v >= k) o.vh[i] += r.hours; });
      const wd = (new Date(r.date).getUTCDay() + 6) % 7; // пн=0 … вс=6, как в pandas
      if (wd === 3) o.thu += r.hours; else if (wd === 5) o.sat += r.hours; else if (wd === 6) o.sun += r.hours;
    }
    const out = [...g.values()];
    const start = Math.min(...out.map((o) => o.first));
    for (const o of out) {
      VOL_LEVELS.forEach((k, i) => { o["v" + k] = o.vh[i] / o.hours; });
      o.share_thu = o.thu / o.hours; o.share_sat = o.sat / o.hours; o.share_sun = o.sun / o.hours;
      o.city_stores = cityStores.get(o.city).size;
      o.season = SEASON_OF_MONTH[new Date(o.first).getUTCMonth() + 1];
      o.t_years = (o.first - start) / DAY / 365.25;
      o.first_date = iso(o.first);
    }
    return out;
  }

  // ---------- линейная алгебра ----------
  function solve(A, b) {
    const n = b.length, M = A.map((r, i) => [...r, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      [M[c], M[p]] = [M[p], M[c]];
      const piv = M[c][c] || 1e-300;
      for (let r = c + 1; r < n; r++) {
        const f = M[r][c] / piv;
        if (f) for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
      }
    }
    const x = new Array(n).fill(0);
    for (let r = n - 1; r >= 0; r--) {
      let s = M[r][n];
      for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k];
      x[r] = s / (M[r][r] || 1e-300);
    }
    return x;
  }

  const NAMES = ["const", "season_summer", "season_autumn", "season_november", "t_years", "log_hours",
    "share_thu", "share_sat", "share_sun", "vol_ge1", "vol_ge2", "vol_ge3", "chain_perekrestok", "log_city_stores"];
  const isPerek = (c) => norm(c) === "перекресток";
  function designRow(o) {
    return [1, +(o.season === "summer"), +(o.season === "autumn"), +(o.season === "november"), o.t_years,
      Math.log(o.hours), o.share_thu, o.share_sat, o.share_sun, o.v1, o.v2, o.v3, +isPerek(o.chain), Math.log(o.city_stores)];
  }

  function fitPoisson(X, y, offset, pen, beta0) {
    const n = X.length, p = X[0].length;
    let beta = beta0 ? beta0.slice() : new Array(p).fill(0);
    if (!beta0) {
      const my = y.reduce((a, b) => a + b, 0) / n, mo = offset.reduce((a, b) => a + b, 0) / n;
      beta[0] = Math.log(Math.max(my, 1e-9)) - mo;
    }
    for (let it = 0; it < 50; it++) {
      const A = Array.from({ length: p }, () => new Array(p).fill(0)), b = new Array(p).fill(0);
      for (let i = 0; i < n; i++) {
        const xi = X[i];
        let eta = offset[i];
        for (let j = 0; j < p; j++) eta += xi[j] * beta[j];
        eta = Math.max(-30, Math.min(30, eta));
        const mu = Math.exp(eta), z = eta - offset[i] + (y[i] - mu) / mu;
        for (let j = 0; j < p; j++) {
          const wx = mu * xi[j];
          b[j] += wx * z;
          for (let k = j; k < p; k++) A[j][k] += wx * xi[k];
        }
      }
      for (let j = 0; j < p; j++) { A[j][j] += pen[j]; for (let k = 0; k < j; k++) A[j][k] = A[k][j]; }
      const nb = solve(A, b);
      const diff = Math.max(...nb.map((v, j) => Math.abs(v - beta[j])));
      beta = nb;
      if (diff < 1e-8) break;
    }
    return beta;
  }

  // ---------- модели ----------
  const sum = (a) => a.reduce((s, v) => s + v, 0);
  const median = (a) => { const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const actionsOf = (rows) => [...new Set(rows.map((r) => r.action_id))].sort();
  function groupSum(rows, key, fields) {
    const m = new Map();
    for (const r of rows) { const k = r[key]; const o = m.get(k) || Object.fromEntries(fields.map((f) => [f, 0])); fields.forEach((f) => { o[f] += r[f]; }); m.set(k, o); }
    return m;
  }

  function coldStart(train, plan) {
    const acts = actionsOf(train), last = train.filter((r) => r.action_id === acts[acts.length - 1]);
    const byReg = new Map();
    for (const r of last) { if (!byReg.has(r.region)) byReg.set(r.region, []); byReg.get(r.region).push(r.kg); }
    const reg = new Map([...byReg].map(([k, v]) => [k, median(v)]));
    const glob = median(last.map((r) => r.kg));
    return plan.map((r) => (reg.has(r.region) ? reg.get(r.region) : glob));
  }

  function naive(train, plan) {
    const sorted = train.slice().sort((a, b) => (a.action_id < b.action_id ? -1 : a.action_id > b.action_id ? 1 : 0));
    const last = new Map(); for (const r of sorted) last.set(r.store_id, r.kg);
    const cold = coldStart(train, plan);
    return plan.map((r, i) => (last.has(r.store_id) ? last.get(r.store_id) : cold[i]));
  }

  function glmCore(train, kappa) {
    const X = train.map(designRow), y = train.map((r) => r.kg);
    const lam = PRIOR_WEIGHT * sum(y);
    const pen = NAMES.map((n, j) => {
      if (n.startsWith("season_") || n === "t_years") return lam;
      if (j > 0 && X.every((x) => x[j] === X[0][j])) return 1e6 * lam + 1;  // постоянная колонка (нет данных) → коэффициент 0
      return 1e-6;
    });
    let logR = new Array(train.length).fill(0), beta = null, rReg, rSt;
    for (let round = 0; round < 3; round++) {
      beta = fitPoisson(X, y, logR, pen, null);
      const mu = X.map((x) => Math.exp(x.reduce((s, v, j) => s + v * beta[j], 0)));
      const d = train.map((r, i) => ({ ...r, mu: mu[i] }));
      const reg = groupSum(d, "region", ["kg", "mu"]);
      rReg = new Map([...reg].map(([k, o]) => [k, (o.kg + kappa) / (o.mu + kappa)]));
      const st = new Map();
      for (const r of d) { const o = st.get(r.store_id) || { kg: 0, mu: 0, region: r.region }; o.kg += r.kg; o.mu += r.mu; st.set(r.store_id, o); }
      rSt = new Map([...st].map(([k, o]) => { const prior = rReg.has(o.region) ? rReg.get(o.region) : 1; return [k, (o.kg + kappa * prior) / (o.mu + kappa)]; }));
      logR = train.map((r) => Math.log(rSt.get(r.store_id)));
    }
    return { beta, rReg, rSt, kappa };
  }

  function glmPredict(m, plan) {
    return plan.map((r) => {
      const x = designRow(r);
      const r0 = m.rSt.has(r.store_id) ? m.rSt.get(r.store_id) : m.rReg.has(r.region) ? m.rReg.get(r.region) : 1;
      return Math.exp(x.reduce((s, v, j) => s + v * m.beta[j], 0)) * r0;
    });
  }

  function glmFit(train) {
    const acts = actionsOf(train);
    let kappa = 50;
    if (acts.length >= 3) {
      const last = acts[acts.length - 1];
      const tr = train.filter((r) => r.action_id < last), te = train.filter((r) => r.action_id === last);
      let best = Infinity;
      for (const k of KAPPAS) {
        const p = glmPredict(glmCore(tr, k), te);
        const sc = sum(te.map((r, i) => Math.abs(r.kg - p[i])));
        if (sc < best) { best = sc; kappa = k; }
      }
    }
    return glmCore(train, kappa);
  }

  function quantile(a, q) {
    const s = a.slice().sort((x, y) => x - y), pos = (s.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return s[lo] + (s[hi] - s[lo]) * (pos - lo);
  }
  const QS = [0.1, 0.9, 0.025, 0.975];
  function ratioQuantiles(train) {
    const acts = actionsOf(train);
    if (acts.length < 3) return { 0.1: 0.6, 0.9: 1.5, 0.025: 0.4, 0.975: 2.0 };
    const last = acts[acts.length - 1];
    const tr = train.filter((r) => r.action_id < last), te = train.filter((r) => r.action_id === last);
    const p = glmPredict(glmFit(tr), te);
    const ratio = te.map((r, i) => r.kg / p[i]);
    return Object.fromEntries(QS.map((q) => [q, quantile(ratio, q)]));
  }

  // ---------- бэктест и прогноз ----------
  function backtest(agg, minTrain = 3, onStep) {
    const acts = actionsOf(agg), steps = [];
    for (let i = minTrain; i < acts.length; i++) {
      const target = acts[i];
      const train = agg.filter((r) => r.action_id < target), test = agg.filter((r) => r.action_id === target);
      const y = test.map((r) => r.kg), ty = sum(y);
      const pg = glmPredict(glmFit(train), test), pn = naive(train, test);
      steps.push({ target, stores: test.length, net_true: ty, net_pred: sum(pg), net_naive: sum(pn),
        wape_glm: sum(y.map((v, j) => Math.abs(v - pg[j]))) / ty, wape_naive: sum(y.map((v, j) => Math.abs(v - pn[j]))) / ty });
      if (onStep) onStep(i - minTrain + 1, acts.length - minTrain);
    }
    return steps;
  }

  function netLogSd(steps) {
    if (steps.length < 2) return PRIOR_NET_LOG_SD;
    return Math.sqrt(sum(steps.map((s) => Math.log(s.net_true / s.net_pred) ** 2)) / steps.length);
  }

  /** План следующей акции: магазины последней акции с их часами и волонтёрами, сезон и тренд — по дате. */
  function nextPlan(agg, nextDateIso) {
    const acts = actionsOf(agg), last = agg.filter((r) => r.action_id === acts[acts.length - 1]);
    const start = Math.min(...agg.map((r) => Date.parse(r.first_date + "T00:00:00Z")));
    const t = Date.parse(nextDateIso + "T00:00:00Z");
    return last.map((r) => ({ ...r, action_id: nextDateIso, first_date: nextDateIso,
      season: SEASON_OF_MONTH[new Date(t).getUTCMonth() + 1], t_years: (t - start) / DAY / 365.25 }));
  }

  /** Полный расчёт: план-факт последней акции, бэктест, прогноз следующей. */
  function analyze(records, nextDateIso, onProgress) {
    const agg = aggregate(records);
    const acts = actionsOf(agg);
    const out = { actions: acts, stores: new Set(agg.map((r) => r.store_id)).size, rows: agg.length };
    if (acts.length < 2) { out.error = "Нужны данные хотя бы двух акций: модель учится на прошлых, чтобы прогнозировать следующую."; return out; }
    const last = acts[acts.length - 1];
    const prev = agg.filter((r) => r.action_id < last), cur = agg.filter((r) => r.action_id === last);
    const mPrev = glmFit(prev), pCur = glmPredict(mPrev, cur), q = ratioQuantiles(prev);
    out.planFact = cur.map((r, i) => ({ store: r.store_id, city: r.city, region: r.region, kg: r.kg, pred: pCur[i],
      lo80: pCur[i] * q[0.1], hi80: pCur[i] * q[0.9] })).sort((a, b) => (a.kg - a.pred) - (b.kg - b.pred));
    out.lastAction = last;
    out.steps = acts.length > 3 ? backtest(agg, 3, onProgress) : [];
    const sd = netLogSd(out.steps.map((s) => s));
    const plan = nextPlan(agg, nextDateIso);
    const m = glmFit(agg), p = glmPredict(m, plan), qa = ratioQuantiles(agg);
    const total = sum(p);
    out.forecast = { date: nextDateIso, stores: plan.length, kg: total, kappa: m.kappa, sd,
      lo80: total * Math.exp(-1.2816 * sd), hi80: total * Math.exp(1.2816 * sd),
      lo95: total * Math.exp(-1.96 * sd), hi95: total * Math.exp(1.96 * sd),
      perStore: plan.map((r, i) => ({ store: r.store_id, city: r.city, region: r.region, pred: p[i], lo80: p[i] * qa[0.1], hi80: p[i] * qa[0.9] })) };
    out.coef = Object.fromEntries(NAMES.map((n, j) => [n, m.beta[j]]));
    return out;
  }

  const api = { parseCSV, mapColumns, readExport, aggregate, fitPoisson, glmFit, glmPredict, naive, backtest,
    ratioQuantiles, nextPlan, analyze, NAMES };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PulseModel = api;
})(typeof self !== "undefined" ? self : this);
