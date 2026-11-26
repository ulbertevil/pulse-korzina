// Запуск: node tests/js_parity.cjs <выгрузка.csv> <дата следующей акции>
const fs = require("fs");
const M = require("../site/model.js");
const { records, report } = M.readExport(fs.readFileSync(process.argv[2], "utf8"));
const res = M.analyze(records, process.argv[3]);
const pf = Object.fromEntries(res.planFact.map((r) => [r.store, r.pred]));
console.log(JSON.stringify({ report, coef: res.coef, forecast: res.forecast.kg, kappa: res.forecast.kappa,
  steps: res.steps, planFact: pf, lastAction: res.lastAction }));
