// Interpolation des libellés : `make test-frontend`.
import test from "node:test";
import assert from "node:assert/strict";

import { fmt } from "./fmt.js";

test("chaque occurrence d'une variable est remplacée", () => {
  assert.equal(fmt("{n} séances, encore {n}", { n: 31 }), "31 séances, encore 31");
});

test("une variable absente ou nulle s'affiche en tiret, jamais en « null »", () => {
  assert.equal(fmt("constaté le {d}", { d: null }), "constaté le —");
  assert.equal(fmt("constaté le {d}", { d: undefined }), "constaté le —");
});

test("un zéro reste un zéro", () => {
  assert.equal(fmt("{n} séances", { n: 0 }), "0 séances");
});

test("un gabarit vide rend une chaîne vide", () => {
  assert.equal(fmt(undefined, { n: 1 }), "");
  assert.equal(fmt("", { n: 1 }), "");
});
