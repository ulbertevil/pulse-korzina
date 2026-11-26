"use strict";

// ---------- форматирование ----------
const nf = (d = 0) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "—" : nf(d).format(x));
const pct = (x, d = 1) => (x == null ? "—" : nf(d).format(x * 100) + "%");
const signedPct = (x, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + nf(d).format(Math.abs(x) * 100) + "%";
const tons = (kg, d = 1) => fmt(kg / 1000, d) + " т";
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const dateLabel = (iso) => { const d = new Date(iso + "T00:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const dateShort = (iso) => { const d = new Date(iso + "T00:00:00"); return `${WD[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`; };
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
      const td = el("td", { class: c.num ? "num" : "" });
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
function lineChart(container, { series, xs, xLabel, yFmt = compact, valFmt = (v) => fmt(v), titleFmt = xLabel, height = 260 }) {
  const draw = () => {
    const W = Math.max(280, container.clientWidth), H = height;
    const m = { t: 12, r: 16, b: 28, l: 52 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const all = series.flatMap((sr) => sr.points.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]));
    const ticks = niceTicks(Math.min(0, ...all), Math.max(...all) * 1.05);
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
      if (i % every) return;
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
      const show = (e) => showTip(e, r.label, [{ color: r.color || color, value: valFmt(r.value), name: "WAPE" }]);
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
  $("robust-note").textContent = "Рекомендация не делает хуже ни в одном сценарии: при нулевом эффекте она равна ноябрьской, "
    + `при любом другом — лучше. «Недобор к идеалу» — сколько теряем против расстановки, которая знала бы настоящий эффект: не больше ${pct(worst, 1)}. `
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

  if (F) $("prereg-text").textContent = `Сбор по сети ${tons(F.pred)}: с вероятностью 80% от ${tons(F.lo80)} до ${tons(F.hi80)}, 95% — от ${tons(F.lo95)} до ${tons(F.hi95)}. `
    + `Это ${fmt(F.pred / F.stores)} кг на магазин при ${fmt(F.stores)} магазинах. Проверяем сумму по сети: разбивка по городам ненадёжна (см. выше).`;
}

function render(D) {
  const k = D.kpi, M = D.meta;
  $("src-table").href = M.source_table;
  $("next-title").textContent = `Следующая акция: ${M.dates.map(dateLabel).join(" и ").replace(/ декабря и (\d+) декабря/, "–$1 декабря")}`;
  $("kpi-tons").textContent = tons(k.pred_kg);
  $("kpi-range").textContent = `80% интервал: ${tons(k.lo80)} – ${tons(k.hi80)}; 95%: ${tons(k.lo95)} – ${tons(k.hi95)}`;
  $("kpi-stores").textContent = fmt(M.stores);
  $("kpi-geo").textContent = `${fmt(M.cities)} городов, ${fmt(M.regions)} регионов`;
  $("kpi-shifts").textContent = fmt(k.shifts);
  $("kpi-shift-gain").textContent = `При рекомендуемой расстановке ${signedPct(k.uplift_vs_current)} кг к «как в ноябре»`;
  const sel = $("portion-select");
  D.portions.forEach((p, i) => sel.append(el("option", { value: i, text: p.label })));
  const setPortion = () => { const p = D.portions[sel.value]; $("kpi-portions").textContent = fmt(k.pred_kg / p.kg); };
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
  $("vol-lede").textContent = `Те же ${fmt(k.shifts)} смен, расставленные по модели, дают ${signedPct(k.uplift_vs_current)} кг к раскладу «как в ноябре» `
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
  $("dl-cities").href = "data/allocation_2026-12_cities.csv";
  $("dl-slots").href = "data/allocation_2026-12_slots.csv";

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
    { title: "Наивный", num: true, render: (r) => tons(r.naive) }, { title: "WAPE магазинов", num: true, render: (r) => pct(r.wape) }], D.steps);
  const mrows = D.models.map((mo) => ({ label: mo.name, value: mo.wape, color: mo.id === "glm_eb" ? css("--s1") : css("--axis") }));
  $("models-chart").dataset.label = "Ошибка моделей по магазинам";
  hbarChart($("models-chart"), mrows, { valFmt: (v) => pct(v), color: css("--s1") });
  table($("models-table"), [{ title: "Модель", key: "name" }, { title: "WAPE", num: true, render: (r) => pct(r.wape) },
    { title: "Ошибка суммы", num: true, render: (r) => pct(r.network_ape) },
    { title: "К наивной", num: true, render: (r) => (r.id === "naive" ? "—" : signedPct(r.vs_naive)) }], D.models);

  // A/B
  const E = D.experiment;
  const nIn = $("ab-n"); nIn.max = E.stores; nIn.value = E.stores;
  const upd = () => {
    const n = +nIn.value, share = +$("ab-share").value, eff = +$("ab-eff").value;
    const alpha = +$("ab-alpha").value, power = +$("ab-power").value;
    const nt = Math.max(2, Math.round(n * share)), nc = Math.max(2, n - nt);
    $("ab-n-out").textContent = fmt(n); $("ab-share-out").textContent = pct(share, 0); $("ab-eff-out").textContent = "+" + pct(eff, 0);
    const mC = mde(E.sd_cuped_strata, E.mean, nt, nc, alpha, power), mR = mde(E.sd_raw, E.mean, nt, nc, alpha, power);
    const nC = need(E.sd_cuped_strata, E.mean, eff, share, alpha, power), nR = need(E.sd_raw, E.mean, eff, share, alpha, power);
    $("ab-mde").textContent = pct(mC); $("ab-mde-raw").textContent = `без CUPED и страт: ${pct(mR)}`;
    $("ab-need").textContent = fmt(nC); $("ab-need-raw").textContent = `без CUPED и страт: ${fmt(nR)}`;
    $("ab-verdict").textContent = nC <= n
      ? `Хватает: эффект ${pct(eff, 0)} будет заметен на ${fmt(n)} магазинах (${fmt(nt)} в тесте, ${fmt(nc)} в контроле).`
      : `Не хватает: для эффекта ${pct(eff, 0)} нужно ${fmt(nC)} магазинов, а в эксперименте ${fmt(n)}. Увеличьте выборку или ищите эффект крупнее.`;
  };
  ["ab-n", "ab-share", "ab-eff", "ab-alpha", "ab-power"].forEach((id) => $(id).addEventListener("input", upd));
  upd();
  $("ab-check").textContent = `Проверка на прошлой акции: в 200 A/A-тестах ложных срабатываний ${pct(E.aa, 0)} (норма 5%); `
    + `при эффекте, равном MDE, эксперимент находит его в ${pct(E.power_at_mde, 0)} случаев (цель 80%). Корреляция прогноза с фактом ρ = ${fmt(E.rho, 2)}.`;
  $("dl-assign").href = "data/experiment_2026-12_assignment.csv";

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
  renderReality(D.reality, { pred: D.kpi.pred_kg, lo80: D.kpi.lo80, hi80: D.kpi.hi80, lo95: D.kpi.lo95, hi95: D.kpi.hi95, stores: D.meta.stores });
  $("app").setAttribute("aria-busy", "false");
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
  const csvCell = (v) => (/[",;\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csvBlob = (cols, rows) => {
    const text = [cols.map((c) => c[0]).join(",")].concat(rows.map((r) => cols.map((c) => csvCell(c[1](r))).join(","))).join("\n");
    const u = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
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
    $("up-range").textContent = `${dateLabel(F.date)}, ${fmt(F.stores)} магазинов с часами и волонтёрами как в последней акции; 80% — ${tons(F.lo80)}…${tons(F.hi80)}`;
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
  }

  function run(text, label) {
    if (worker) worker.terminate();
    $("up-result").hidden = true;
    $("up-check").hidden = true;
    demoBtn.disabled = true;
    say(`Читаем ${label}…`);
    const t0 = performance.now();
    worker = new Worker("worker.js");
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === "report") { showReport(m.report); say("Обучаем модель…"); }
      else if (m.type === "progress") say(`Проверяем модель на прошлых акциях: ${m.i} из ${m.n}…`);
      else if (m.type === "error") { say(`Ошибка расчёта: ${m.message}`, true); demoBtn.disabled = false; }
      else if (m.type === "done") {
        demoBtn.disabled = false;
        worker.terminate(); worker = null;
        const R = m.result;
        if (!R) { say("Файл не подходит: см. проверку ниже.", true); return; }
        if (R.error) { say(R.error, true); return; }
        showResult(R);
        say(`Готово за ${fmt((performance.now() - t0) / 1000, 1)} с: ${label}.`);
      }
    };
    worker.onerror = (e) => { say(`Ошибка расчёта: ${e.message}`, true); demoBtn.disabled = false; };
    worker.postMessage({ text, nextDate: $("next-date").value || "2026-12-10" });
  }

  const readFile = (f) => {
    if (!f) return;
    if (f.size > 50 * 1024 * 1024) { say("Файл больше 50 МБ — сократите период или число колонок.", true); return; }
    f.text().then((t) => run(t, `файл «${f.name}»`), (e) => say(`Не удалось прочитать файл: ${e.message}`, true));
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
})();
