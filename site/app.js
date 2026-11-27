"use strict";

// ---------- форматирование ----------
const nf = (d = 0) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "—" : nf(d).format(x));
const pct = (x, d = 1) => (x == null ? "—" : nf(d).format(x * 100) + "%");
const signedPct = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + nf(d).format(Math.abs(x) * 100) + "%";
const tons = (kg, d = 1) => fmt(kg / 1000, d) + " т";
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
/** CSV для русского Excel: разделитель «;», десятичная запятая, BOM — открывается двойным щелчком без мастера импорта. */
const excelCell = (v) => {
  const t = typeof v === "number" ? String(v).replace(".", ",") : String(v ?? "");
  return /[";\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
};
const excelCsv = (head, rows) => "\ufeff" + [head, ...rows].map((r) => r.map(excelCell).join(";")).join("\r\n");
const csvUrlOf = (head, rows) => URL.createObjectURL(new Blob([excelCsv(head, rows)], { type: "text/csv;charset=utf-8" }));
const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const dateLabel = (iso) => { const d = new Date(iso + "T00:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const dateShort = (iso) => { const d = new Date(iso + "T00:00:00"); return `${WD[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`; };
/** ["2026-12-10","2026-12-11"] → «10–11 декабря»; разные месяцы — через тире. */
const datesLabel = (ds) => {
  if (!ds || !ds.length) return "";
  const a = new Date(ds[0] + "T00:00:00"), b = new Date(ds[ds.length - 1] + "T00:00:00");
  if (ds.length === 1) return dateLabel(ds[0]);
  if (a.getMonth() === b.getMonth()) return `${a.getDate()}–${b.getDate()} ${MONTHS[a.getMonth()]}`;
  return `${dateLabel(ds[0])} – ${dateLabel(ds[ds.length - 1])}`;
};
const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
};
const actionLabel = (id) => { const [y, m] = id.split("-").map(Number); return `${MONTHS[m - 1].slice(0, 3)} ${y}`; };
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------- DOM ----------
const $ = (id) => document.getElementById(id);
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
}
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

function table(container, cols, rows) {
  const t = el("table");
  const tr = el("tr");
  cols.forEach((c) => tr.append(el("th", { class: c.num ? "num" : "", scope: "col", text: c.title })));
  t.append(el("thead", {}, tr));
  const tb = el("tbody");
  rows.forEach((r) => {
    const row = el("tr");
    cols.forEach((c) => {
      const td = el("td", { class: c.num ? "num" : "", "data-label": c.title });
      const v = c.render ? c.render(r) : r[c.key];
      if (v instanceof Node) td.append(v); else td.textContent = v ?? "";
      row.append(td);
    });
    tb.append(row);
  });
  t.append(tb);
  container.replaceChildren(t);
}

// ---------- подсказка ----------
const tip = $("tooltip");
function showTip(evt, title, rows) {
  const box = el("div", { class: "tt-title", text: title });
  const lines = rows.map((r) => el("div", { class: "tt-row" },
    el("span", { class: "key-line", style: `background:${r.color}` }), el("b", { text: r.value }), el("span", { text: r.name })));
  tip.replaceChildren(box, ...lines);
  tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { tip.hidden = true; };

function niceTicks(min, max, n = 4) {
  const span = max - min || 1, step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= step0);
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(v);
  return ticks;
}
const compact = (v) => (Math.abs(v) >= 10000 ? nf(0).format(v / 1000) + " тыс." : nf(0).format(v));

// ---------- линейный график с полосой ----------
// series: [{name, color, points:[{x, y, lo, hi}], band:bool, dots:bool}], xs: [x...], xLabel(x)
function lineChart(container, { series, xs, xLabel, yFmt = compact, valFmt = (v) => fmt(v), titleFmt = xLabel, height = 260, yMin = null, xTicks = null }) {
  const draw = () => {
    const W = Math.max(280, container.clientWidth), H = height;
    const m = { t: 12, r: 16, b: 28, l: 52 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const all = series.flatMap((sr) => sr.points.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]));
    const lo = yMin ?? Math.min(0, ...all), hi = Math.max(...all);
    const ticks = niceTicks(lo, yMin == null ? hi * 1.05 : hi + (hi - lo) * 0.05);
    const st = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
    while (ticks[0] > lo + 1e-9) ticks.unshift(ticks[0] - st);
    while (ticks[ticks.length - 1] < hi - 1e-9) ticks.push(ticks[ticks.length - 1] + st);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const xi = (x) => xs.indexOf(x);
    const X = (x) => m.l + (xs.length === 1 ? iw / 2 : (xi(x) / (xs.length - 1)) * iw);
    const Y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": container.dataset.label || "график" });
    ticks.forEach((t) => {
      svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === y0 ? "base" : "grid" }));
      const tx = s("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }); tx.textContent = yFmt(t); svg.append(tx);
    });
    const every = Math.ceil(xs.length / Math.max(2, Math.floor(iw / 64)));
    xs.forEach((x, i) => {
      if (xTicks ? !xTicks.includes(x) : i % every) return;
      const tx = s("text", { x: X(x), y: H - 8, "text-anchor": "middle" }); tx.textContent = xLabel(x); svg.append(tx);
    });
    series.forEach((sr) => {
      if (sr.band) {
        const up = sr.points.map((p) => `${X(p.x)},${Y(p.hi)}`).join(" ");
        const dn = sr.points.slice().reverse().map((p) => `${X(p.x)},${Y(p.lo)}`).join(" ");
        svg.append(s("polygon", { points: `${up} ${dn}`, fill: sr.color, "fill-opacity": 0.1 }));
      }
    });
    series.forEach((sr) => {
      svg.append(s("polyline", { points: sr.points.map((p) => `${X(p.x)},${Y(p.y)}`).join(" "), fill: "none",
        stroke: sr.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      if (sr.dots) sr.points.forEach((p) => svg.append(s("circle", { cx: X(p.x), cy: Y(p.y), r: 4, fill: sr.color,
        stroke: css("--surface"), "stroke-width": 2 })));
    });
    const cross = s("line", { y1: m.t, y2: m.t + ih, class: "cross", visibility: "hidden" });
    svg.append(cross);
    const hit = s("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent", tabindex: 0 });
    let focusI = xs.length - 1;
    const at = (i, evt) => {
      const x = xs[i];
      cross.setAttribute("x1", X(x)); cross.setAttribute("x2", X(x)); cross.setAttribute("visibility", "visible");
      const rows = series.map((sr) => { const p = sr.points.find((q) => q.x === x);
        return p ? { color: sr.color, value: valFmt(p.y), name: sr.name } : null; }).filter(Boolean);
      showTip(evt, titleFmt(x), rows);
    };
    hit.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
      const i = Math.round(((px - m.l) / iw) * (xs.length - 1));
      at(Math.max(0, Math.min(xs.length - 1, i)), e);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    hit.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      focusI = Math.max(0, Math.min(xs.length - 1, focusI + (e.key === "ArrowRight" ? 1 : -1)));
      const r = svg.getBoundingClientRect();
      at(focusI, { clientX: r.left + (X(xs[focusI]) / W) * r.width, clientY: r.top + 20 });
      e.preventDefault();
    });
    hit.addEventListener("blur", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    svg.append(hit);
    container.replaceChildren(svg);
  };
  draw();
  new ResizeObserver(() => draw()).observe(container);
}

// ---------- горизонтальные столбики ----------
function hbarChart(container, rows, { valFmt, color }) {
  const draw = () => {
    const W = Math.max(280, container.clientWidth);
    const labelW = Math.min(230, W * 0.45), barH = 18, gap = 18, m = { t: 4, r: 56, l: labelW };
    const H = m.t + rows.length * (barH + gap);
    const max = Math.max(...rows.map((r) => r.value));
    const iw = W - m.l - m.r;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": container.dataset.label || "столбики" });
    rows.forEach((r, i) => {
      const y = m.t + i * (barH + gap), w = Math.max(2, (r.value / max) * iw);
      const lab = s("text", { x: 0, y: y + barH / 2 + 4, class: "val" }); lab.textContent = r.label; svg.append(lab);
      svg.append(s("line", { x1: m.l, x2: m.l, y1: y - 4, y2: y + barH + 4, class: "base" }));
      const path = `M${m.l},${y} h${w - 4} a4,4 0 0 1 4,4 v${barH - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z`;
      const bar = s("path", { d: path, fill: r.color || color, class: "bar", tabindex: 0 });
      const show = (e) => showTip(e, r.label, [{ color: r.color || color, value: valFmt(r.value), name: "ошибка по магазинам" }]);
      bar.addEventListener("pointermove", show);
      bar.addEventListener("pointerleave", hideTip);
      bar.addEventListener("focus", () => { const b = bar.getBoundingClientRect(); show({ clientX: b.right, clientY: b.top }); });
      bar.addEventListener("blur", hideTip);
      svg.append(bar);
      const v = s("text", { x: m.l + w + 6, y: y + barH / 2 + 4, class: "val" }); v.textContent = valFmt(r.value); svg.append(v);
    });
    container.replaceChildren(svg);
  };
  draw();
  new ResizeObserver(() => draw()).observe(container);
}

function legend(container, items) {
  container.replaceChildren(...items.map((it) => el("span", {},
    el("span", { class: it.rect ? "key-rect" : "key-line", style: `background:${it.color}` }), it.name)));
}

// ---------- статистика для калькулятора ----------
function normPpf(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const lo = 0.02425;
  if (p < lo) { const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
  if (p > 1 - lo) return -normPpf(1 - p);
  const q = p - 0.5, r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}
const mde = (sd, mean, nt, nc, alpha, power) => (normPpf(1 - alpha / 2) + normPpf(power)) * sd * Math.sqrt(1 / nt + 1 / nc) / mean;
const need = (sd, mean, eff, share, alpha, power) => {
  const k = (normPpf(1 - alpha / 2) + normPpf(power)) * sd / (eff * mean);
  return Math.ceil(k * k * (1 / share + 1 / (1 - share)));
};

// ---------- сборка страницы ----------
// ---------- проверка на реальности ----------
const times = (r) => (r >= 1 ? `в ${fmt(r, r < 10 ? 1 : 0)} раза больше` : `в ${fmt(1 / r, 1 / r < 10 ? 1 : 0)} раза меньше`);
function ratioChart(container, rows) {
  const draw = () => {
    const W = Math.max(280, container.clientWidth), narrow = W < 560;
    const labelW = narrow ? 0 : Math.min(260, W * 0.4), rowH = narrow ? 52 : 34;
    const m = { t: 8, r: 16, l: labelW + 8, b: 40 }, iw = W - m.l - m.r, H = m.t + rows.length * rowH + m.b;
    const lo = Math.log(0.1), hi = Math.log(10), X = (v) => m.l + ((Math.log(v) - lo) / (hi - lo)) * iw;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": container.dataset.label });
    [0.2, 0.5, 1, 2, 5].forEach((v) => {
      svg.append(s("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, class: v === 1 ? "ref" : "grid" }));
      const tx = s("text", { x: X(v), y: H - m.b + 16, "text-anchor": "middle", class: "tick" });
      tx.textContent = v === 1 ? "совпадает" : `×${fmt(v, v < 1 ? 1 : 0)}`; svg.append(tx);
    });
    const cap = s("text", { x: m.l + iw / 2, y: H - 6, "text-anchor": "middle", class: "tick" });
    cap.textContent = "← синтетика меньше реальности · больше →"; svg.append(cap);
    rows.forEach((r, i) => {
      const yc = m.t + i * rowH + (narrow ? 34 : rowH / 2), cls = r.in_sample ? " anchor" : "";
      const lab = s("text", { x: narrow ? m.l : 0, y: narrow ? yc - 14 : yc + 4, class: "val" });
      lab.textContent = r.label; svg.append(lab);
      svg.append(s("line", { x1: X(1), x2: X(r.ratio), y1: yc, y2: yc, class: "stem" + cls }));
      const dot = s("circle", { cx: X(r.ratio), cy: yc, r: 6, class: "dot" + cls, tabindex: 0 });
      const show = (e) => showTip(e, r.label, [
        { color: "transparent", value: `${fmt(r.real)} ${r.unit}`, name: "публичная цифра" },
        { color: "transparent", value: `${fmt(r.synthetic)} ${r.unit}`, name: "синтетика" },
        { color: "transparent", value: times(r.ratio), name: "" }]);
      dot.addEventListener("pointermove", show); dot.addEventListener("pointerleave", hideTip);
      dot.addEventListener("focus", () => { const b = dot.getBoundingClientRect(); show({ clientX: b.right, clientY: b.top }); });
      dot.addEventListener("blur", hideTip);
      svg.append(dot);
    });
    container.replaceChildren(svg);
  };
  draw();
  new ResizeObserver(() => draw()).observe(container);
}

function renderReality(R, F) {
  if (!R) return;
  const out = R.public.filter((r) => !r.in_sample);
  $("real-sub").textContent = `${out.length} проверок вне калибровки + 1 цифра, по которой синтетика откалибрована (серая).`;
  ratioChart($("real-chart"), R.public);
  $("real-note").textContent = `По сети синтетика совпадает с цифрой фонда по построению. По городам она промахивается в среднем в ${fmt(R.spread, 1)} раза `
    + "в обе стороны: реальные города различаются гораздо сильнее, чем заложено в синтетику. Поэтому цифрам по отдельным городам и магазинам "
    + "на этой странице верить нельзя — их даст только выгрузка фонда. Часть расхождения — разный охват: партнёр мог считать не все магазины города.";
  const uly = R.public.find((r) => r.fact === "partner_ulyanovsk_2026_11");
  if (uly && uly.ratio > 2) $("real-note").textContent += ` Пример: в Ульяновске синтетика ${times(uly.ratio)} публичной цифры, `
    + "а в топе «где первый волонтёр даёт больше всего» много ульяновских магазинов. Такие адресные рекомендации надо пересчитать на выгрузке фонда.";
  table($("real-table"), [
    { title: "Что сравниваем", render: (r) => el("span", {}, r.label, el("br"), el("span", { class: "muted", text: r.caveat })) },
    { title: "Публично", num: true, render: (r) => `${fmt(r.real)} ${r.unit}` },
    { title: "Синтетика", num: true, render: (r) => `${fmt(r.synthetic)} ${r.unit}` },
    { title: "Разница", num: true, render: (r) => (r.in_sample ? "калибровка" : times(r.ratio)) },
    { title: "Источник", render: (r) => { const a = el("a", { href: r.source_url, rel: "noopener", target: "_blank" });
      a.textContent = (r.source_url.match(/^https?:\/\/([^/]+)/) || [, r.source_url])[1].replace(/^www\./, ""); return a; } },
  ], R.public);

  const SC = { 0: "нет эффекта", 0.5: "вдвое меньше", 1: "как оценила модель", 2: "вдвое больше" };
  table($("robust-table"), [
    { title: "Эффект волонтёра в жизни", render: (r) => SC[r.scale] ?? `×${r.scale}` },
    { title: "К «как в ноябре»", num: true, render: (r) => signedPct(r.uplift_vs_current) },
    { title: "К «поровну»", num: true, render: (r) => signedPct(r.uplift_vs_uniform) },
    { title: "Недобор к идеалу", num: true, render: (r) => pct(r.regret, 1) },
  ], R.volunteers);
  const worst = Math.max(...R.volunteers.map((r) => r.regret));
  $("robust-note").textContent = "В проверенных сценариях (эффект от нуля до вдвое больше оценки, та же форма модели) рекомендация не хуже ноябрьской: "
    + `при нулевом эффекте она равна ей. Прогноз при нынешних людях во всех сценариях один — он привязан к цифре фонда. «Недобор к идеалу» — сколько теряем против расстановки, которая знала бы настоящий эффект: не больше ${pct(worst, 1)}. `
    + "Если эффект намного больше оценки (×4 и выше), людей выгоднее концентрировать сильнее — это проверит A/B-эксперимент.";

  table($("stress-table"), [
    { title: "Разброс магазинов / регионов", render: (r) => `×${fmt(Math.exp(r.sigma_store), 1)} / ×${fmt(Math.exp(r.sigma_region), 1)}` },
    { title: "Ошибка модели", num: true, render: (r) => pct(r.wape_glm) },
    { title: "«Как в прошлый раз»", num: true, render: (r) => pct(r.wape_naive) },
    { title: "Ошибка ниже на", num: true, render: (r) => pct(r.gain_vs_naive, 0) },
  ], R.stress);
  const last = R.stress[R.stress.length - 1];
  $("stress-note").textContent = `Разброс — типичное отличие магазина или региона от среднего. Даже при регионах, различающихся в ${fmt(Math.exp(last.sigma_region), 1)} раза `
    + `(примерно как в публичных цифрах), модель ошибается на ${pct(last.gain_vs_naive, 0)} меньше, чем «как в прошлый раз».`;

  $("prereg").hidden = !F;
  if (!F) return;
  $("prereg-title").textContent = `Прогноз на ${datesLabel(F.dates)} зафиксирован ${dateLabel(F.made)}, до акции`;
  $("prereg-text").textContent = `Сбор по сети ${tons(F.pred_kg)}: 80% диапазон модели — от ${tons(F.lo80_kg)} до ${tons(F.hi80_kg)}, 95% — от ${tons(F.lo95_kg)} до ${tons(F.hi95_kg)}. `
    + `Это ${fmt(F.pred_kg / F.stores)} кг на магазин при ${fmt(F.stores)} магазинах. Проверяем сумму по сети и кг на магазин: разбивка по городам ненадёжна (см. выше). `
    + `Числа берутся из файла ${F.stores_csv.replace(/_stores\.csv$/, ".json")}, а не из пересборки; SHA-256 прогноза по магазинам начинается с ${F.stores_csv_sha256.slice(0, 16)}, тег в git — ${F.git_tag}.`;
}

let abUse = null; // ставит калькулятору A/B данные загруженного файла
function render(D) {
  const k = D.kpi, M = D.meta;
  $("src-table").href = M.source_table;
  if (!M.table_connected) $("banner-hours").textContent = `; таблицы на ${datesLabel(M.dates)} ещё нет — взяты ноябрьские магазины и часы`;
  const demo = (name) => (M.synthetic ? "ДЕМО_" : "") + name;
  [["dl-cities", "расстановка_по_городам.csv"], ["dl-slots", "расстановка_по_точкам.csv"], ["dl-assign", "тест_контроль.csv"]]
    .forEach(([id, name]) => $(id).setAttribute("download", demo(name)));
  const past = new Date() > new Date(M.dates[M.dates.length - 1] + "T23:59:59");
  $("next-title").textContent = past ? `Акция ${datesLabel(M.dates)} прошла — ниже прогноз, сделанный до неё` : `Следующая акция: ${datesLabel(M.dates)}`;
  $("next-date").value = M.dates[0];
  $("kpi-tons").textContent = tons(k.pred_kg);
  $("kpi-range").textContent = `80% диапазон модели — от ${tons(k.lo80)} до ${tons(k.hi80)}, 95% — от ${tons(k.lo95)} до ${tons(k.hi95)}. `
    + "Это разброс ошибок на прошлых акциях синтетики; ошибки в допущениях (сезон, рост, число магазинов) в него не входят.";
  $("kpi-stores").textContent = fmt(M.stores);
  $("kpi-geo").textContent = `${fmt(M.cities)} городов, ${fmt(M.regions)} регионов`;
  $("kpi-shifts").textContent = fmt(k.shifts);
  $("kpi-shift-gain").textContent = `При рекомендуемой расстановке ${signedPct(k.uplift_vs_uniform)}…${signedPct(k.uplift_vs_current)} кг: к раскладу «поровну» и к смоделированному ноябрю`;
  const extra = k.kg_opt - k.kg_current, extraUni = k.kg_opt - k.kg_opt / (1 + k.uplift_vs_uniform);
  const r10 = (x) => Math.round(x / 6 / 10) * 10, hiSets = r10(extra);
  $("kpi-gain").replaceChildren(
    el("strong", { text: `От +${fmt(r10(extraUni))} до +${fmt(hiSets)} ${plural(hiSets, "набора", "наборов", "наборов")} без новых волонтёров. ` }),
    `Те же ${fmt(k.shifts)} смен, поставленные туда, где они дают больше: +${tons(extraUni)} к раскладу «поровну» и +${tons(extra)} к ноябрьской расстановке `
      + "(в демо она смоделирована, реальной у нас нет). ",
    el("span", { class: "muted", text: "Оценка модели на синтетике; эффект волонтёров нужно подтвердить " }),
    el("a", { href: "#ab", text: "экспериментом" }), el("span", { class: "muted", text: "." }));
  const sel = $("portion-select");
  D.portions.forEach((p, i) => sel.append(el("option", { value: i, text: p.label })));
  const setPortion = () => { const p = D.portions[sel.value]; $("kpi-portions").textContent = "≈ " + fmt(Math.round(k.pred_kg / p.kg / 100) * 100); };
  sel.addEventListener("change", setPortion); setPortion();
  $("generated").textContent = `Данные собраны ${M.generated}.`;

  // почасовая кривая
  const dates = M.dates, hours = [...new Set(D.hourly.map((h) => h.hour))].sort((a, b) => a - b);
  const colors = [css("--s1"), css("--s2")];
  const hs = dates.map((d, i) => ({ name: dateShort(d), color: colors[i % 2], band: true,
    points: hours.map((h) => { const r = D.hourly.find((q) => q.date === d && q.hour === h);
      return r ? { x: h, y: r.kg, lo: r.lo80, hi: r.hi80 } : null; }).filter(Boolean) }));
  legend($("hourly-legend"), hs);
  $("hourly-chart").dataset.label = "Прогноз сбора по часам по дням акции";
  lineChart($("hourly-chart"), { series: hs, xs: hours, xLabel: (h) => `${h}:00`, valFmt: (v) => fmt(v) + " кг",
    titleFmt: (h) => `${h}:00–${h + 1}:00` });
  table($("hourly-table"), [{ title: "День", key: "d" }, { title: "Час", key: "h" },
    { title: "Прогноз, кг", key: "kg", num: true }, { title: "80% интервал, кг", key: "iv", num: true }],
    D.hourly.map((r) => ({ d: dateShort(r.date), h: `${r.hour}:00`, kg: fmt(r.kg), iv: `${fmt(r.lo80)} – ${fmt(r.hi80)}` })));

  // волонтёры
  $("vol-lede").textContent = `Те же ${fmt(k.shifts)} смен, расставленные по модели, дают ${signedPct(k.uplift_vs_current)} кг к раскладу «как в ноябре» (в демо он смоделирован) `
    + `и ${signedPct(k.uplift_vs_uniform)} к раскладу «поровну». Килограммы на смену: ${fmt(k.kg_per_shift_current, 1)} → ${fmt(k.kg_per_shift_opt, 1)}.`;
  table($("cities-table"), [
    { title: "Город", key: "city" }, { title: "Магазинов", key: "stores", num: true }, { title: "Смен", key: "shifts", num: true },
    { title: "Сейчас, кг", render: (r) => fmt(r.kg_current), num: true }, { title: "С расстановкой, кг", render: (r) => fmt(r.kg_opt), num: true },
    { title: "Прирост", num: true, render: (r) => el("span", { class: r.uplift >= 0 ? "up" : "down", text: signedPct(r.uplift) }) },
  ], D.cities.slice(0, 15));
  const gmax = Math.max(...D.ranking.map((r) => r.gain_per_vol_hour));
  table($("ranking-table"), [
    { title: "Магазин", render: (r) => el("span", {}, r.city, el("br"), el("span", { class: "muted", text: r.address })) },
    { title: "Когда", render: (r) => `${dateShort(r.date)}, ${r.time}` },
    { title: "кг / волонтёро-час", num: true, render: (r) => el("span", {},
      el("span", { class: "inline-bar", style: `width:${Math.round((r.gain_per_vol_hour / gmax) * 48)}px` }), fmt(r.gain_per_vol_hour, 1)) },
    { title: "Людей: сейчас → надо", num: true, render: (r) => `${r.v_current} → ${r.v_opt}` },
  ], D.ranking.slice(0, 15));
  $("dl-cities").href = "data/allocation_cities.csv";
  $("dl-slots").href = "data/allocation_slots.csv";

  // ниже ожидаемого
  const B = D.below;
  $("below-lede").textContent = `План-факт по прошлой акции (${actionLabel(B.action)}): ${fmt(B.count)} магазинов из ${fmt(B.of)} собрали меньше нижней границы `
    + `80% интервала прогноза. С ними стоит поговорить первыми: часы, место короба, волонтёры.`;
  table($("below-table"), [
    { title: "Магазин", render: (r) => el("span", {}, r.city, el("br"), el("span", { class: "muted", text: r.address })) },
    { title: "Факт, кг", num: true, render: (r) => fmt(r.kg) }, { title: "Прогноз, кг", num: true, render: (r) => fmt(r.pred) },
    { title: "Нижняя граница, кг", num: true, render: (r) => fmt(r.lo80) },
    { title: "Недобор", num: true, render: (r) => el("span", { class: "down", text: `${fmt(r.gap)} кг` }) },
  ], B.rows.slice(0, 15));

  // точность
  const acts = D.steps.map((st) => st.action);
  const ss = [
    { name: "Факт", color: css("--fact"), dots: true, points: D.steps.map((st) => ({ x: st.action, y: st.true })) },
    { name: "Прогноз модели", color: css("--s1"), dots: true, band: true,
      points: D.steps.map((st) => ({ x: st.action, y: st.pred, lo: st.lo95, hi: st.hi95 })) },
    { name: "Наивный прогноз", color: css("--s2"), dots: true, points: D.steps.map((st) => ({ x: st.action, y: st.naive })) },
  ];
  legend($("steps-legend"), ss);
  $("steps-chart").dataset.label = "Факт и прогнозы суммы по сети по акциям";
  lineChart($("steps-chart"), { series: ss, xs: acts, xLabel: actionLabel, valFmt: (v) => tons(v), yFmt: (v) => fmt(v / 1000) + " т", height: 240 });
  table($("steps-table"), [{ title: "Акция", render: (r) => actionLabel(r.action) }, { title: "Факт", num: true, render: (r) => tons(r.true) },
    { title: "Модель", num: true, render: (r) => tons(r.pred) }, { title: "95% интервал", num: true, render: (r) => `${tons(r.lo95)} – ${tons(r.hi95)}` },
    { title: "Наивный", num: true, render: (r) => tons(r.naive) }, { title: "Ошибка по магазинам", num: true, render: (r) => pct(r.wape) }], D.steps);
  const mrows = D.models.map((mo) => ({ label: mo.name, value: mo.wape, color: mo.id === "glm_eb" ? css("--s1") : css("--axis") }));
  $("models-chart").dataset.label = "Ошибка моделей по магазинам";
  hbarChart($("models-chart"), mrows, { valFmt: (v) => pct(v), color: css("--s1") });
  table($("models-table"), [{ title: "Модель", key: "name" }, { title: "Ошибка по магазинам", num: true, render: (r) => pct(r.wape) },
    { title: "Ошибка суммы", num: true, render: (r) => pct(r.network_ape) },
    { title: "К наивной", num: true, render: (r) => (r.id === "naive" ? "—" : signedPct(r.vs_naive)) }], D.models);

  // A/B: по умолчанию — синтетика, после загрузки выгрузки — её последняя акция
  const SYN = D.experiment;
  let E = SYN, own = null;
  const nIn = $("ab-n");
  const upd = () => {
    const n = +nIn.value, share = +$("ab-share").value, eff = +$("ab-eff").value;
    const alpha = +$("ab-alpha").value, power = +$("ab-power").value;
    const nt = Math.max(2, Math.round(n * share)), nc = Math.max(2, n - nt);
    $("ab-n-out").textContent = fmt(n); $("ab-share-out").textContent = pct(share, 0); $("ab-eff-out").textContent = "+" + pct(eff, 0);
    const mC = mde(E.sd_cuped_strata, E.mean, nt, nc, alpha, power), mR = mde(E.sd_raw, E.mean, nt, nc, alpha, power);
    const nC = need(E.sd_cuped_strata, E.mean, eff, share, alpha, power), nR = need(E.sd_raw, E.mean, eff, share, alpha, power);
    $("ab-mde").textContent = pct(mC); $("ab-mde-raw").textContent = `при простом делении: ${pct(mR)}`;
    $("ab-need").textContent = fmt(nC); $("ab-need-raw").textContent = `при простом делении: ${fmt(nR)}`;
    $("ab-verdict").textContent = nC <= n
      ? `Хватает: эффект ${pct(eff, 0)} будет заметен на ${fmt(n)} магазинах (${fmt(nt)} в тесте, ${fmt(nc)} в контроле).`
      : `Не хватает: для эффекта ${pct(eff, 0)} нужно ${fmt(nC)} магазинов, а в эксперименте ${fmt(n)}. Увеличьте выборку или ищите эффект крупнее.`;
    const extra = Math.round(nt * (E.days_per_store || SYN.days_per_store || 2) / 10) * 10;
    $("ab-cost").textContent = `Если проверяется «+1 волонтёр»: это ≈ ${fmt(extra)} новых смен на ${fmt(nt)} тестовых магазинах. `
      + "Люди должны быть новыми, а не снятыми с контрольных магазинов, — иначе тест сравнивает перестановку, а не добавку.";
  };
  const note = () => {
    const sim = `Проверено 200 раз на последней синтетической акции: когда эффекта нет, эксперимент ошибочно «находит» его в ${pct(SYN.aa, 0)} случаев (допустимо 5%); `
      + `когда эффект равен минимальному заметному, находит его в ${pct(SYN.power_at_mde, 0)} случаев (цель 80%). `;
    const data = own
      ? `Разброс сборов и то, насколько прогноз его объясняет, взяты из вашего файла: акция ${dateLabel(own.action)}, ${fmt(own.stores)} магазинов, `
        + `связь факта с прогнозом ρ = ${fmt(own.rho, 2)} (в синтетике ${fmt(SYN.rho, 2)}). Прогноз для неё сделан только по прошлым акциям — как будет и в настоящем эксперименте. `
      : "Разброс сборов и то, насколько прогноз его объясняет, взяты из синтетики: на настоящей выгрузке нужное число магазинов будет другим — загрузите её в разделе «Свои данные», и калькулятор пересчитается. ";
    $("ab-check").textContent = sim + data
      + `Эффект перестановки волонтёров по модели — от ${signedPct(D.kpi.uplift_vs_uniform)} до ${signedPct(D.kpi.uplift_vs_current)}, это на границе того, что видно за одну акцию: надёжнее проверять на двух акциях подряд.`;
  };
  const use = (stats) => {
    own = stats; E = stats || SYN;
    nIn.min = Math.min(100, Math.max(20, Math.floor(E.stores / 2)));
    nIn.step = own ? 1 : 20;
    nIn.max = E.stores; nIn.value = E.stores;
    $("ab-badge").textContent = own ? "ваш файл" : "синтетика";
    $("ab-src").hidden = !own;
    if (own) $("ab-src-text").textContent = `Калькулятор пересчитан на загруженном файле (акция ${dateLabel(own.action)}, ${fmt(own.stores)} магазинов).`;
    upd(); note();
  };
  ["ab-n", "ab-share", "ab-eff", "ab-alpha", "ab-power"].forEach((id) => $(id).addEventListener("input", upd));
  $("ab-reset").addEventListener("click", () => use(null));
  abUse = use;
  use(null);
  $("dl-assign").href = "data/experiment_assignment.csv";

  // факты
  const ST = { primary: "первоисточник", secondary: "СМИ", fund_statement: "заявление фонда", unverified: "не проверено", estimate: "оценка" };
  table($("facts-table"), [
    { title: "Показатель", render: (r) => el("span", {}, r.metric, el("br"), el("span", { class: "muted", text: [r.period, r.geo].filter(Boolean).join(" · ") })) },
    { title: "Значение", num: true, render: (r) => (r.value ? `${/^[\d.]+$/.test(r.value) ? fmt(+r.value, r.value.includes(".") ? 2 : 0) : r.value} ${r.unit}` : "—") },
    { title: "Статус", render: (r) => el("span", { class: "badge", text: ST[r.status] || r.status }) },
    { title: "Источник", render: (r) => { const a = el("a", { href: r.source_url, rel: "noopener", target: "_blank" });
      a.textContent = (r.source_url.match(/^https?:\/\/([^/]+)/) || [, r.source_url])[1].replace(/^www\./, ""); return a; } },
  ], D.facts);
  $("dl-facts").href = "data/facts.csv";
  renderReality(D.reality, D.frozen || null);
  $("app").setAttribute("aria-busy", "false");
}

// ?shot=city — показать один раздел (для скриншотов и ссылок «посмотреть только это»)
{
  const shot = new URLSearchParams(location.search).get("shot");
  if (shot && document.getElementById(shot)) { document.body.classList.add("shot"); document.getElementById(shot).classList.add("shot-target"); }
}

fetch("data/dashboard.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(render)
  .catch((e) => { $("app").prepend(el("p", { class: "banner", text: `Не удалось загрузить данные (${e.message}). Запустите scripts/build.py.` })); });

// ---------- Свои данные: расчёт в браузере (model.js в Web Worker) ----------
(function upload() {
  const status = $("up-status"), demoBtn = $("demo-btn"), drop = $("drop"), fileInput = $("file");
  let worker = null, urls = [];
  const say = (text, err = false) => { status.textContent = text; status.classList.toggle("err", err); };
  const csvBlob = (cols, rows) => {
    const u = csvUrlOf(cols.map((c) => c[0]), rows.map((r) => cols.map((c) => c[1](r))));
    urls.push(u);
    return u;
  };
  const r1 = (x) => Math.round(x * 10) / 10;
  const COLS = { store: "магазин", date: "дата", kg: "кг", start: "начало", end: "конец", hours: "часы",
    volunteers: "волонтёры", city: "город", region: "регион", chain: "сеть" };

  function showReport(rep) {
    const box = $("up-check");
    const ok = rep.missing.length === 0;
    const items = [
      `Строк в файле: ${fmt(rep.rows)}, взято в расчёт: ${fmt(rep.used ?? 0)}.`,
      `Узнали колонки: ${rep.columns.map((c) => COLS[c] || c).join(", ") || "никакие"}.`,
    ];
    if (!ok) items.push(`Не хватает обязательных колонок: ${rep.missing.map((c) => COLS[c]).join(", ")}. Сверьтесь с шаблоном.`);
    Object.entries(rep.reasons).forEach(([why, n]) => items.push(`Пропущено строк — ${why}: ${fmt(n)}.`));
    if (ok && !rep.hasHours) items.push("Нет часов работы точки: считаем по 4 часа на день.");
    if (ok && !rep.hasVolunteers) items.push("Нет числа волонтёров: эффект волонтёров не оценивается.");
    const ul = el("ul");
    items.forEach((t) => ul.append(el("li", { text: t })));
    box.replaceChildren(el("strong", { text: "Проверка файла" }), ul);
    box.hidden = false;
  }

  function showResult(R) {
    const F = R.forecast;
    const box = $("up-check");
    box.querySelector("ul").append(el("li", { text:
      `Нашли акций: ${R.actions.length} (${R.actions.map((d) => `${dateLabel(d)} ${d.slice(0, 4)}`).join(", ")}), магазинов: ${fmt(R.stores)}. `
      + "Новая акция начинается после перерыва больше 7 дней." }));
    $("up-tons").textContent = tons(F.kg);
    $("up-range").textContent = `${dateLabel(F.date)}, ${fmt(F.stores)} магазинов с часами и волонтёрами как в последней акции из файла; 80% — ${tons(F.lo80)}…${tons(F.hi80)}. `
      + "Прогноз вверху страницы другой: он считается по таблице магазинов следующей акции.";
    if (R.steps.length) {
      const y = R.steps.reduce((a, s) => a + s.net_true, 0);
      const w = (k) => R.steps.reduce((a, s) => a + s[k] * s.net_true, 0) / y;
      $("up-wape").textContent = pct(w("wape_glm"));
      $("up-wape-sub").textContent = `средняя ошибка по магазину на ${R.steps.length} прошлых акциях; «как в прошлый раз» — ${pct(w("wape_naive"))}`;
    } else {
      $("up-wape").textContent = "—";
      $("up-wape-sub").textContent = "для проверки на истории нужно хотя бы 4 акции";
    }
    const below = R.planFact.filter((r) => r.kg < r.lo80);
    $("up-below").textContent = fmt(below.length);
    $("up-below-sub").textContent = `из ${fmt(R.planFact.length)} магазинов акции ${dateLabel(R.lastAction)} — ниже нижней границы 80% прогноза`;
    table($("up-table"), [
      { title: "Магазин", render: (r) => el("span", {}, r.store, el("br"), el("span", { class: "muted", text: r.region || r.city })) },
      { title: "Факт, кг", num: true, render: (r) => fmt(r.kg) },
      { title: "Ожидали, кг", num: true, render: (r) => `${fmt(r.pred)} (${fmt(r.lo80)}–${fmt(r.hi80)})` },
      { title: "Разница", num: true, render: (r) => el("span", { class: r.kg < r.pred ? "down" : "", text: signedPct(r.kg / r.pred - 1, 0) }) },
    ], R.planFact.slice(0, 10));
    urls.forEach((u) => URL.revokeObjectURL(u)); urls = [];
    const a1 = $("up-dl-plan"), a2 = $("up-dl-fc");
    a1.href = csvBlob([["магазин", (r) => r.store], ["город", (r) => r.city], ["регион", (r) => r.region], ["факт_кг", (r) => r1(r.kg)],
      ["прогноз_кг", (r) => r1(r.pred)], ["нижняя_80", (r) => r1(r.lo80)], ["верхняя_80", (r) => r1(r.hi80)],
      ["ниже_ожидаемого", (r) => (r.kg < r.lo80 ? "да" : "")]], R.planFact);
    a1.download = `план-факт_${R.lastAction}.csv`;
    a2.href = csvBlob([["магазин", (r) => r.store], ["город", (r) => r.city], ["регион", (r) => r.region], ["прогноз_кг", (r) => r1(r.pred)],
      ["нижняя_80", (r) => r1(r.lo80)], ["верхняя_80", (r) => r1(r.hi80)]], F.perStore);
    a2.download = `прогноз_${F.date}.csv`;
    $("up-result").hidden = false;
    const note = $("up-ab");
    if (R.ab && abUse) {
      abUse({ ...R.ab, action: R.lastAction });
      note.replaceChildren("Калькулятор ", el("a", { href: "#ab", text: "A/B-эксперимента" }),
        ` пересчитан на этом файле: разброс сборов ${fmt(R.ab.stores)} магазинов акции ${dateLabel(R.lastAction)}.`);
    } else note.textContent = "Калькулятор A/B остался на синтетике: для пересчёта нужно хотя бы 40 магазинов в последней акции.";
  }

  function run(text, label) {
    if (worker) worker.terminate();
    $("up-result").hidden = true;
    $("up-check").hidden = true;
    demoBtn.disabled = true;
    say(`Читаем ${label}…`);
    const t0 = performance.now();
    const nextDate = $("next-date").value || "2026-12-10";
    const handle = (m) => {
      if (m.type === "report") { showReport(m.report); say("Обучаем модель…"); }
      else if (m.type === "progress") say(`Проверяем модель на прошлых акциях: ${m.i} из ${m.n}…`);
      else if (m.type === "error") { say(`Ошибка расчёта: ${m.message}`, true); demoBtn.disabled = false; }
      else if (m.type === "done") {
        demoBtn.disabled = false;
        if (worker) { worker.terminate(); worker = null; }
        const R = m.result;
        if (!R) { say("Файл не подходит: см. проверку ниже.", true); return; }
        if (R.error) { say(R.error, true); return; }
        showResult(R);
        say(`Готово за ${fmt((performance.now() - t0) / 1000, 1)} с: ${label}.`);
      }
    };
    if (SHOT) { inline(text, nextDate, handle); return; }
    worker = new Worker("worker.js");
    worker.onmessage = (e) => handle(e.data);
    // фоновый поток не запустился (старый браузер, политика сайта) — считаем в основном потоке
    worker.onerror = (e) => { e.preventDefault(); worker.terminate(); worker = null; say("Считаем без фонового потока…"); inline(text, nextDate, handle); };
    worker.postMessage({ text, nextDate });
  }

  // Для скриншотов (?shot=…): считаем в основном потоке — headless Chrome не ждёт фоновый поток.
  const SHOT = new URLSearchParams(location.search).has("shot");
  function inline(text, nextDate, handle) {
    const go = () => {
      const { records, report } = window.PulseModel.readExport(text);
      handle({ type: "report", report });
      const result = report.missing.length || !records.length ? null : window.PulseModel.analyze(records, nextDate);
      handle({ type: "done", result });
    };
    if (window.PulseModel) { go(); return; }
    const sc = document.createElement("script");
    sc.src = "model.js"; sc.onload = go; document.head.append(sc);
  }

  const readFile = (f) => {
    if (!f) return;
    if (f.size > 50 * 1024 * 1024) { say("Файл больше 50 МБ — сократите период или число колонок.", true); return; }
    if (/\.(xlsx?|ods)$/i.test(f.name)) {
      say("Это файл Excel. Откройте его и сохраните как «CSV (разделители — запятые или точка с запятой)», затем загрузите CSV.", true);
      return;
    }
    // CSV из русского Excel обычно в кодировке Windows-1251: пробуем UTF-8, при ошибке — 1251
    f.arrayBuffer().then((buf) => {
      let t, enc = "";
      try { t = new TextDecoder("utf-8", { fatal: true }).decode(buf); }
      catch { t = new TextDecoder("windows-1251").decode(buf); enc = ", кодировка Windows-1251"; }
      run(t, `файл «${f.name}»${enc}`);
    }, (e) => say(`Не удалось прочитать файл: ${e.message}`, true));
  };
  fileInput.addEventListener("change", () => readFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); readFile(e.dataTransfer.files[0]); });
  demoBtn.addEventListener("click", () => {
    say("Загружаем демо-выгрузку…");
    fetch("data/demo_export.csv").then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then((t) => run(t, "демо-выгрузка (синтетические данные)"))
      .catch((e) => say(`Демо-выгрузка не найдена (${e.message}). Запустите scripts/build.py.`, true));
  });
  window.pulseDemo = () => demoBtn.click();
  if (new URLSearchParams(location.search).get("demo") === "1") demoBtn.click();
})();

// ---------- План для координатора города ----------
const coordData = fetch("data/coordinator.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });

(function cityPlan() {
  const input = $("city-input"), daySel = $("city-day"), status = $("city-status");
  let rows = [], cities = new Map(), byNorm = new Map(), csvUrl = null, dates = [];
  let current = null, demo = false, tableOk = true;
  const norm = (x) => String(x || "").toLowerCase().replace(/ё/g, "е").replace(/[\s,]+(г|город|с|село|п|пгт|рп|сп|д|ст-ца|станица|сл|х)\.?$/, "").replace(/\s+/g, " ").trim();
  const resolve = (x) => (cities.has(x) ? x : byNorm.get(norm(x)));
  const store = { get: () => { try { return localStorage.getItem("pulse.city"); } catch { return null; } },
    set: (v) => { try { localStorage.setItem("pulse.city", v); } catch { /* приватный режим */ } } };

  function show(raw, fromUser = true) {
    const city = resolve(raw), all = cities.get(city);
    if (!all) { $("city-sheet").hidden = true; status.textContent = String(raw || "").trim() ? "Такого города нет в акции — выберите из списка." : ""; return; }
    status.textContent = "";
    if (input.value !== city) input.value = city;
    store.set(city);
    if (fromUser) { const u = new URL(location.href); u.searchParams.set("city", city); history.replaceState(null, "", u); }
    const day = daySel.value, list = day ? all.filter((r) => r.date === day) : all;
    const sum = (k) => list.reduce((a, r) => a + r[k], 0);
    const moved = list.filter((r) => r.v_opt !== r.v_current).length;
    $("city-title").textContent = `${city} · акция ${day ? dateShort(day) : datesLabel(dates)}`;
    $("city-stores").textContent = fmt(new Set(list.map((r) => r.address)).size);
    $("city-slots").textContent = `${fmt(list.length)} смен магазинов (магазин × день)`;
    $("city-shifts").textContent = fmt(sum("v_opt"));
    $("city-moves").textContent = moved ? `в ${fmt(moved)} из ${fmt(list.length)} точек число людей меняется` : "рекомендация совпадает с ноябрём";
    $("city-kg").textContent = sum("kg_opt") >= 1000 ? tons(sum("kg_opt")) : `${fmt(sum("kg_opt"))} кг`;
    const g = sum("kg_opt") / sum("kg_current") - 1;
    const sets = Math.round(sum("kg_opt") / 6);
    $("city-gain").textContent = `≈ ${fmt(sets)} ${plural(sets, "набор", "набора", "наборов")}; ${Math.abs(g) < 0.0005 ? "как при ноябрьской расстановке" : signedPct(g) + " к ноябрьской расстановке"}`;
    const cols = [
      ...(day ? [] : [{ title: "День", render: (r) => dateShort(r.date) }]),
      { title: "Часы", render: (r) => `${r.start}:00–${r.end}:00` },
      { title: "Магазин", render: (r) => el("span", {}, r.address, el("br"), el("span", { class: "muted", text: r.chain })) },
      { title: "Людей: было → надо", num: true, render: (r) => {
        if (r.v_opt === r.v_current) return String(r.v_opt);
        return el("span", { class: "move " + (r.v_opt > r.v_current ? "up" : "down"), text: `${r.v_current} → ${r.v_opt}` }); } },
      { title: "Ожидаем, кг", num: true, render: (r) => fmt(r.kg_opt) },
      { title: "Тара до, кг", num: true, render: (r) => fmt(r.hi80) },
    ];
    table($("city-table"), cols, list);
    $("city-table").querySelectorAll("tbody tr").forEach((tr, i) => {
      if (i > 0 && list[i].date !== list[i - 1].date) tr.classList.add("day-break");
    });
    if (csvUrl) URL.revokeObjectURL(csvUrl);
    const head = ["город", "дата", "начало", "конец", "магазин", "сеть", "людей_было", "людей_надо", "ожидаем_кг", "тара_до_кг"];
    csvUrl = csvUrlOf(head, list.map((r) => [city, r.date, r.start, r.end, r.address, r.chain, r.v_current, r.v_opt, r.kg_opt, r.hi80]));
    const a = $("city-csv"); a.href = csvUrl; a.download = `${demo ? "ДЕМО_" : ""}план_${city.replace(/[^\p{L}\d-]+/gu, "_")}_${day || dates.join("_")}.csv`;
    $("city-sheet").hidden = false;
    current = { city, list, day };
    if (!$("city-msg-box").hidden) $("city-msg").value = message(current);
  }

  /** Готовое сообщение для чата волонтёров: где и когда нужны люди. */
  function message({ city, list, day }) {
    const need = list.filter((r) => r.v_opt > 0);
    const when = day ? dateLabel(day) : datesLabel(dates);
    const lines = [`«Корзина доброты» · ${city.replace(/\s*г\.?$/, "")} · ${when}`, ""];
    if (demo) lines.unshift("ДЕМО: люди и килограммы посчитаны на синтетике" + (tableOk ? "" : ", часы — ноябрьские") + ". Не для рассылки.", "");
    if (!need.length) return lines.concat("В этом городе волонтёры на точках не требуются.").join("\n");
    const ns = new Set(need.map((r) => r.address)).size;
    lines.push(`Ищем волонтёров: ${ns} ${plural(ns, "магазин", "магазина", "магазинов")}, ${need.length} ${plural(need.length, "смена", "смены", "смен")}. `
      + "Сколько человек нужно на смену:");
    let prev = null;
    need.forEach((r) => {
      if (r.date !== prev && !day) { lines.push("", dateShort(r.date)); prev = r.date; }
      lines.push(`• ${r.start}:00–${r.end}:00 — ${r.address} (${r.chain}): ${r.v_opt}`);
    });
    const free = list.length - need.length;
    if (free) lines.push("", `Ещё ${free} ${plural(free, "точка", "точки", "точек")} — по плану без волонтёров.`);
    lines.push("", "Откликнитесь координатору — распределим по точкам.");
    return lines.join("\n");
  }

  coordData.then((D) => {
    rows = D.rows.map((v) => Object.fromEntries(D.fields.map((f, i) => [f, v[i]])));
    demo = !!D.synthetic; tableOk = !!D.table_connected;
    dates = D.dates || [...new Set(rows.map((r) => r.date))].sort();
    $("city-when").textContent = datesLabel(dates);
    rows.forEach((r) => { if (!cities.has(r.city)) cities.set(r.city, []); cities.get(r.city).push(r); });
    const names = [...cities.keys()].sort((a, b) => cities.get(b).length - cities.get(a).length || a.localeCompare(b, "ru"));
    names.forEach((n) => byNorm.set(norm(n), n));
    $("city-list").replaceChildren(...names.map((n) => el("option", { value: n })));
    [...new Set(rows.map((r) => r.date))].sort().forEach((d) => daySel.append(el("option", { value: d, text: dateShort(d) })));
    const want = new URL(location.href).searchParams.get("city") || store.get();
    show(resolve(want) || names[0], false);
  }).catch((e) => { status.textContent = `Не удалось загрузить план (${e.message}). Запустите scripts/build.py.`; status.classList.add("err"); });

  input.addEventListener("change", () => show(input.value.trim()));
  input.addEventListener("input", () => { if (cities.has(input.value.trim())) show(input.value.trim()); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") show(input.value.trim()); });
  daySel.addEventListener("change", () => show(input.value.trim()));
  window.pulseCity = (name, withMessage) => {
    const c = resolve(name); if (!c) return;
    show(c);
    if (withMessage) {  // в обзоре — только показать текст, буфер обмена без клика не трогаем
      $("city-msg").value = message(current);
      $("city-msg-box").querySelector(".sub").textContent = "Готовый текст для чата волонтёров — кнопка выше копирует его, перед отправкой можно поправить:";
      $("city-msg-box").hidden = false;
    }
  };
  $("city-msg-btn").addEventListener("click", async () => {
    if (!current) return;
    const box = $("city-msg-box"), ta = $("city-msg");
    ta.value = message(current);
    box.hidden = false;
    try { await navigator.clipboard.writeText(ta.value); box.querySelector(".sub").textContent = "Скопировано — вставьте в чат волонтёров города. Перед отправкой можно поправить:"; }
    catch { box.querySelector(".sub").textContent = "Выделите текст и скопируйте (Ctrl+C) — браузер не дал скопировать автоматически:"; ta.select(); }
  });
  $("city-print").addEventListener("click", () => {
    document.body.classList.add("print-city");
    addEventListener("afterprint", () => document.body.classList.remove("print-city"), { once: true });
    print();
  });
})();

// ---------- цель акции → сколько смен добавить ----------
(function goalPlan() {
  const input = $("goal-t"), conf = $("goal-conf"), status = $("goal-status");
  let G = null, rows = [], cum = [], cumAlt = [], csvUrl = null, chartKey = "";

  /** Сколько первых шагов нужно, чтобы прибавка дошла до need кг; null — не хватает. */
  const stepsFor = (c, need) => {
    if (need <= 0) return 0;
    let lo = 0, hi = c.length - 1;
    if (!c.length || c[hi] < need) return null;
    while (lo < hi) { const m = (lo + hi) >> 1; if (c[m] >= need) hi = m; else lo = m + 1; }
    return lo + 1;
  };
  const t = (kg) => tons(kg, 1);
  const shiftsTxt = (n) => `${fmt(n)} ${plural(n, "смена", "смены", "смен")}`;
  const altStart = () => G.kg_opt_alt ?? G.kg_opt;  // осторожный вариант: и перестановка, и новые смены при эффекте × 0,5

  function chart(n, nAlt, targetMean) {
    const all = cum.length;
    const max = n == null ? all : Math.min(all, Math.max(500, 3 * n, Math.round((nAlt || 0) * 1.15)));
    const step = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000].find((v) => max / v <= 80) || 2000;
    const xs = []; for (let i = 0; i <= max; i += step) xs.push(i);
    if (xs[xs.length - 1] !== max) xs.push(max);
    if (n && !xs.includes(n)) { xs.push(n); xs.sort((a, b) => a - b); }
    const lab = niceTicks(0, max, 5).filter((v) => v % step === 0);
    const key = `${targetMean}|${n}|${max}`;
    if (key === chartKey) return;
    chartKey = key;
    const at = (c, i) => (i === 0 ? 0 : c[i - 1]);
    const s1 = css("--s1"), s2 = css("--s2"), ref = css("--muted");
    const series = [
      { name: "по модели", color: s1, points: xs.map((x) => ({ x, y: G.kg_opt + at(cum, x) })) },
      { name: "если эффект вдвое меньше", color: s2, points: xs.map((x) => ({ x, y: altStart() + at(cumAlt, x) })) },
      { name: "цель с учётом уверенности", color: ref, points: xs.map((x) => ({ x, y: targetMean })) },
    ];
    legend($("goal-legend"), series.map((sr) => ({ name: sr.name, color: sr.color })));
    if (n) series.push({ name: "ваш план", color: s1, dots: true, points: [{ x: n, y: G.kg_opt + at(cum, n) }] });
    const lo = Math.min(G.kg_current, targetMean, altStart()) * 0.97;
    lineChart($("goal-chart"), { series, xs, yMin: lo, height: 240,
      xTicks: lab, xLabel: (x) => fmt(x), titleFmt: (x) => `+${shiftsTxt(x)}`, yFmt: (v) => fmt(v / 1000) + " т", valFmt: (v) => t(v) });
  }

  function show() {
    if (!G) return;
    const goalT = Number(String(input.value).replace(",", "."));
    if (!(goalT > 0)) { status.textContent = "Введите цель в тоннах, например 150."; $("goal-body").hidden = true; return; }
    status.textContent = "";
    const target = goalT * 1000, p = Number(conf.value);
    const mean = target * Math.exp(normPpf(p) * G.sigma);  // ожидание, при котором сумма ≥ цели с вероятностью p
    const n = stepsFor(cum, mean - G.kg_opt), nAlt = stepsFor(cumAlt, mean - altStart());
    const max = G.kg_opt + (cum[cum.length - 1] || 0);
    const confTxt = p > 0.5 ? ` в ${p === 0.8 ? "8" : "9"} акциях из 10` : "";
    $("goal-body").hidden = false;
    let verdict;
    if (mean <= G.kg_current) {
      verdict = `Цель ${t(target)}${confTxt} достижима и без изменений: прогноз при ноябрьской расстановке — ${t(G.kg_current)}.`;
    } else if (n === 0) {
      verdict = `Новые люди не нужны: хватит переставить нынешних ${fmt(G.shifts)} по рекомендации — это ${t(G.kg_opt)} вместо ${t(G.kg_current)}.`;
    } else if (n == null) {
      verdict = `Даже по 3 человека на каждой точке модель ждёт не больше ${t(max)}, `
        + (p > 0.5 ? `а чтобы собрать ${t(target)}${confTxt}, нужно в среднем ${t(mean)}. ` : `а цель — ${t(target)}. `)
        + "Нужны новые магазины или более длинные часы — или цель поскромнее.";
    } else {
      verdict = `Для цели ${t(target)}${confTxt}: переставить нынешних людей по рекомендации и добавить ${shiftsTxt(n)} — `
        + `это +${pct(n / G.shifts, 0)} к ${fmt(G.shifts)} сменам ноября. Перестановка даёт +${tons(G.kg_opt - G.kg_current)}, `
        + `новые смены — ещё +${tons(cum[n - 1])}.`;
    }
    $("goal-verdict").textContent = verdict;
    const nn = n ?? cum.length;
    const gain = nn ? cum[nn - 1] : 0, gainAlt = nn ? cumAlt[nn - 1] : 0;
    $("goal-need").textContent = n == null ? `${fmt(cum.length)}+` : fmt(n);
    $("goal-need-sub").textContent = n == null ? "все свободные места на точках — и всё равно мало" : n ? `≈ ${fmt(n / 2, 0)} человек, если каждый выходит оба дня` : "хватит нынешних людей";
    $("goal-kg").textContent = t(G.kg_opt + gain);
    $("goal-kg-sub").textContent = `≈ ${fmt((G.kg_opt + gain) / 6)} наборов` + (gain ? `; из них +${t(gain)} — новые смены` : "");
    $("goal-alt").textContent = t(altStart() + gainAlt);
    $("goal-alt-sub").textContent = `вместо ${t(G.kg_opt + gain)}; `
      + (nAlt == null ? "до цели не хватит даже всех свободных мест на точках"
        : nAlt === 0 ? "цель достижима и так" : `для цели понадобится ${shiftsTxt(nAlt)}`);
    chart(n, nAlt, mean);
    // где добавлять
    const add = new Map();
    for (let i = 0; i < nn; i++) { const [ri, g] = G.steps[i]; add.set(ri, (add.get(ri) || { n: 0, kg: 0 })); const a = add.get(ri); a.n += 1; a.kg += g / 10; }
    const byCity = new Map();
    add.forEach((a, ri) => { const r = rows[ri]; const c = byCity.get(r.city) || { city: r.city, n: 0, kg: 0, points: 0 };
      c.n += a.n; c.kg += a.kg; c.points += 1; byCity.set(r.city, c); });
    const list = [...byCity.values()].sort((a, b) => b.n - a.n || b.kg - a.kg);
    $("goal-where-sub").textContent = nn ? `${fmt(list.length)} ${plural(list.length, "город", "города", "городов")}, ${fmt(add.size)} ${plural(add.size, "точка", "точки", "точек")}; первые 12 городов по числу новых смен — остальные в CSV.` : "";
    $("goal-table").hidden = !nn; $("goal-csv").hidden = !nn; $("goal-where-sub").parentElement.hidden = !nn;
    if (!nn) return;
    table($("goal-table"), [
      { title: "Город", key: "city" },
      { title: "Новых смен", num: true, render: (r) => fmt(r.n) },
      { title: "Точек", num: true, render: (r) => fmt(r.points) },
      { title: "+ кг", num: true, render: (r) => fmt(r.kg) },
    ], list.slice(0, 12));
    if (csvUrl) URL.revokeObjectURL(csvUrl);
    const head = ["город", "дата", "начало", "конец", "магазин", "сеть", "людей_по_рекомендации", "людей_с_новыми", "прибавка_кг"];
    const body = [...add.entries()].sort((a, b) => a[0] - b[0]).map(([ri, a]) => { const r = rows[ri];
      return [r.city, r.date, r.start, r.end, r.address, r.chain, r.v_opt, r.v_opt + a.n, Math.round(a.kg * 10) / 10]; });
    csvUrl = csvUrlOf(head, body);
    $("goal-csv").href = csvUrl; $("goal-csv").download = `${G.synthetic ? "ДЕМО_" : ""}новые_смены_цель_${goalT}т.csv`;
  }

  coordData.then((D) => {
    if (!D.goal) { status.textContent = "Нет данных для цели — пересоберите scripts/build.py."; return; }
    G = { ...D.goal, synthetic: !!D.synthetic };
    rows = D.rows.map((v) => Object.fromEntries(D.fields.map((f, i) => [f, v[i]])));
    let a = 0, b = 0;
    cum = G.steps.map((x) => (a += x[1] / 10));
    cumAlt = G.steps.map((x) => (b += x[2] / 10));
    const want = Number(new URL(location.href).searchParams.get("goal"));
    input.value = want > 0 ? want : Math.round(G.kg_current * 1.1 / 1000);
    show();
  }).catch((e) => { status.textContent = `Не удалось загрузить данные (${e.message}).`; status.classList.add("err"); });
  input.addEventListener("input", show);
  conf.addEventListener("change", show);
})();
