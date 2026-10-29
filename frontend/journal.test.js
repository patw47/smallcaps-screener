// Lecture du journal des alertes : `make test-frontend`. Valeurs de fixture inventées.
import test from "node:test";
import assert from "node:assert/strict";

import { summarize } from "./journal.js";

const line = (ticker, session, exit, ret = {}) => ({
  ticker, session, entry: session, risk: [], exit,
  ret_5: ret[5]?.[0] ?? null, iwm_5: ret[5]?.[1] ?? null,
  ret_21: ret[21]?.[0] ?? null, iwm_21: ret[21]?.[1] ?? null,
  ret_63: null, iwm_63: null,
});

// 3 alertes : AAA échue à 5 et 21 séances, BBB échue à 5 seulement, CCC du jour.
const payload = {
  last_session: "2026-12-01",
  horizons: [5, 21, 63],
  net: {},
  lines: [
    line("AAA", "2026-10-01", { 5: "2026-10-08", 21: "2026-10-30", 63: "2026-12-30" },
      { 5: [3.5, 1.0], 21: [12.0, 2.0] }),
    line("BBB", "2026-11-20", { 5: "2026-11-28", 21: "2026-12-21", 63: "2027-02-20" },
      { 5: [-6.5, 0.5] }),
    line("CCC", "2026-12-01", { 5: "2026-12-08", 21: "2026-12-31", 63: "2027-03-03" }),
  ],
};

test("3 alertes dont 1 échue à 21 séances : 3 lignes, moyenne à 21 séances sur n = 1", () => {
  const s = summarize(payload);
  assert.equal(s.rows.length, 3);
  const h21 = s.stats.find((x) => x.h === 21);
  assert.equal(h21.n, 1);
  assert.equal(h21.ret, 12.0);
  assert.equal(h21.iwm, 2.0);
  assert.equal(h21.excess, 10.0);
  assert.equal(h21.pending, 2);
  const h5 = s.stats.find((x) => x.h === 5);
  assert.equal(h5.n, 2);
  assert.equal(h5.ret, -1.5);
});

test("publications du jour = lignes de la dernière séance close ; tri le plus récent d'abord", () => {
  const s = summarize(payload);
  assert.deepEqual(s.today.map((r) => r.ticker), ["CCC"]);
  assert.deepEqual(s.rows.map((r) => r.ticker), ["CCC", "BBB", "AAA"]);
});

test("horizon passé sans cours : compté à part, hors moyenne", () => {
  const gone = line("DDD", "2026-09-01", { 5: "2026-09-09", 21: "2026-10-01", 63: "2026-12-01" });
  const s = summarize({ ...payload, lines: [...payload.lines, gone] });
  const h21 = s.stats.find((x) => x.h === 21);
  assert.equal(h21.n, 1);
  assert.equal(h21.ret, 12.0);
  assert.equal(h21.missing, 1);
  assert.equal(s.rows.find((r) => r.ticker === "DDD").cells[21], "missing");
  // séance d'horizon = dernière séance close : le job du soir peut ne pas être passé
  assert.equal(s.rows.find((r) => r.ticker === "DDD").cells[63], "pending");
});

test("journal vide : état vide, aucune erreur", () => {
  const s = summarize({ last_session: "2026-12-01", horizons: [5, 21, 63], net: {}, lines: [] });
  assert.equal(s.empty, true);
  assert.deepEqual(s.rows, []);
  assert.deepEqual(s.today, []);
  assert.deepEqual(s.stats.map((x) => [x.n, x.ret, x.excess]), [[0, null, null], [0, null, null], [0, null, null]]);
  assert.equal(summarize(undefined).empty, true);
});
