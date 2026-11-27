/* Обзор за 2 минуты: шаги по главным разделам с живыми действиями. Запуск — кнопкой в шапке или ссылкой ?tour=1. */
(function tour() {
  const STEPS = [
    { target: "#next .hero", title: "Сколько соберём",
      text: "Прогноз на следующую акцию по сети и по каждому из 1 740 магазинов — с диапазоном, а не одной цифрой. "
        + "Ниже — сколько наборов дадут те же волонтёры, если поставить их туда, где они нужнее." },
    { target: "#goal .goal", title: "Сколько людей нужно для цели",
      text: "Фонд задаёт цель акции — например, +10% к прогнозу — и видит, сколько смен волонтёров добавить и в какие города. "
        + "Можно попросить «чтобы получилось в 8 акциях из 10» и сразу увидеть осторожный вариант, если волонтёр помогает вдвое меньше." },
    { target: "#city .coord", title: "Лист координатора города",
      text: "Координатор выбирает город и получает лист: магазины, часы, сколько людей поставить, на сколько кг готовить тару. "
        + "Кнопка копирует готовый текст для чата волонтёров. Сейчас открыта Казань.",
      action: () => window.pulseCity && window.pulseCity("Казань", true) },
    { target: "#upload .upload", title: "Данные фонда — прямо в браузере",
      text: "Фонд загружает свою выгрузку «магазин × день × кг», модель учится в браузере за несколько секунд, файл никуда не уходит. "
        + "Сейчас идёт расчёт на демо-выгрузке: проверка файла, точность на прошлых акциях, магазины ниже ожидаемого.",
      action: () => window.pulseDemo && window.pulseDemo() },
    { target: "#reality", title: "Честно о синтетике",
      text: "Килограммы пока синтетические, поэтому мы сверили их с публичными цифрами и проверили, что рекомендации не вредят, "
        + "даже если волонтёры помогают меньше, чем думает модель. Прогноз на декабрь зафиксирован в git до акции." },
    { target: "#ab .ab", title: "Как проверить идею",
      text: "Калькулятор эксперимента: сколько магазинов нужно, чтобы отличить настоящий эффект от случайности. "
        + "Группы похожих магазинов и прогноз модели сокращают нужную выборку втрое; список «тест / контроль» готов к скачиванию." },
    { target: "#implement", title: "Как внедрить",
      text: "Серверы и персональные данные не нужны. К новой акции — кнопка «Новая акция» на GitHub и ссылка на таблицу магазинов: "
        + "сайт пересчитается сам. Код открыт, 107 автотестов — в том числе сайт проверяется в браузере при каждой публикации." },
  ];
  let i = -1, panel = null, focused = null;
  const done = new Set();

  function build() {
    panel = document.createElement("div");
    panel.className = "tour";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Обзор за 2 минуты");
    panel.innerHTML = `<div class="tour-head"><span class="tour-count"></span>
        <button type="button" class="tour-x" aria-label="Закрыть обзор">×</button></div>
      <h3 class="tour-title"></h3><p class="tour-text"></p>
      <div class="tour-nav"><button type="button" class="btn btn-2 tour-prev">Назад</button>
        <button type="button" class="btn tour-next">Дальше</button></div>`;
    document.body.append(panel);
    panel.querySelector(".tour-x").addEventListener("click", stop);
    panel.querySelector(".tour-prev").addEventListener("click", () => go(i - 1));
    panel.querySelector(".tour-next").addEventListener("click", () => (i < STEPS.length - 1 ? go(i + 1) : stop()));
  }

  function go(n) {
    if (n < 0 || n >= STEPS.length) return;
    i = n;
    const st = STEPS[i], t = document.querySelector(st.target);
    if (focused) focused.classList.remove("tour-focus");
    focused = t;
    if (t) {
      t.classList.add("tour-focus");
      const top = t.getBoundingClientRect().top + scrollY - 16;
      scrollTo({ top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
    if (st.action && !done.has(i)) { done.add(i); st.action(); }
    panel.querySelector(".tour-count").textContent = `${i + 1} из ${STEPS.length}`;
    panel.querySelector(".tour-title").textContent = st.title;
    panel.querySelector(".tour-text").textContent = st.text;
    panel.querySelector(".tour-prev").disabled = i === 0;
    panel.querySelector(".tour-next").textContent = i === STEPS.length - 1 ? "Готово" : "Дальше";
    panel.querySelector(".tour-next").focus({ preventScroll: true });
  }

  function start() {
    if (!panel) build();
    panel.hidden = false;
    document.body.classList.add("touring");
    go(0);
  }
  function stop() {
    if (focused) focused.classList.remove("tour-focus");
    focused = null;
    if (panel) panel.hidden = true;
    document.body.classList.remove("touring");
  }

  addEventListener("keydown", (e) => {
    if (!panel || panel.hidden) return;
    if (e.key === "Escape") { stop(); return; }
    // стрелки в поле ввода, списке или на графике — их, а не обзора
    if (e.target.closest && e.target.closest("input, select, textarea, [contenteditable], svg, [role='slider']")) return;
    if (e.key === "Escape") stop();
    else if (e.key === "ArrowRight") go(i + 1);
    else if (e.key === "ArrowLeft") go(i - 1);
  });
  document.querySelectorAll("[data-tour-start]").forEach((b) => b.addEventListener("click", start));
  window.pulseTour = { start, go: (n) => { if (!panel || panel.hidden) start(); go(n); }, stop };
  // ждём, пока страница отрисует данные, — иначе прокрутка уедет
  if (new URLSearchParams(location.search).get("tour") === "1") {
    const wait = () => (document.getElementById("app").getAttribute("aria-busy") === "false" ? setTimeout(start, 300) : setTimeout(wait, 100));
    wait();
  }
})();
