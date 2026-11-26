/* Фоновый расчёт: страница не подвисает, пока модель учится. Данные не покидают браузер. */
importScripts("model.js");

self.onmessage = (e) => {
  const { text, nextDate } = e.data;
  try {
    const { records, report } = self.PulseModel.readExport(text);
    self.postMessage({ type: "report", report });
    if (report.missing.length || !records.length) { self.postMessage({ type: "done", result: null }); return; }
    const result = self.PulseModel.analyze(records, nextDate, (i, n) => self.postMessage({ type: "progress", i, n }));
    self.postMessage({ type: "done", result });
  } catch (err) {
    self.postMessage({ type: "error", message: String(err && err.message || err) });
  }
};
