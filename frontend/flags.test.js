// Verrou du tri et des filtres de drapeaux (clôture Epic 14). Le S3 avait prouvé ce
// comportement UNE fois, par un script jeté après usage : rien ne l'aurait retenu de
// repartir. `node --test` suffit — aucune bibliothèque, aucune dépendance installée.
//
// Lancer : make test-frontend
import test from "node:test";
import assert from "node:assert/strict";

import { SORT_VALUE, FLAG_FILTER, flagCompare } from "./flags.js";

const titre = (ticker, context) => ({ ticker, context });
const ordre = (liste, cle) => [...liste].sort(flagCompare(cle)).map((s) => s.ticker);

test("un drapeau absent part en fin de tri, jamais devant une vraie valeur", () => {
  const liste = [
    titre("VIDE", { short_float: null }),
    titre("BAS", { short_float: 0.01 }),
    titre("HAUT", { short_float: 0.42 }),
  ];
  // Valeur la plus forte d'abord ; `null` n'est pas un zéro qui se classe, il sort.
  assert.deepEqual(ordre(liste, "short_float"), ["HAUT", "BAS", "VIDE"]);
});

test("un zéro se classe comme une valeur, pas comme une absence", () => {
  const liste = [
    titre("ABSENT", { insider_transactions: null }),
    titre("ZERO", { insider_transactions: 0 }),
    titre("VENTE", { insider_transactions: -0.05 }),
  ];
  assert.deepEqual(ordre(liste, "insider_transactions"), ["ZERO", "VENTE", "ABSENT"]);
});

test("à valeur égale l'ordre du scan tient (tri stable, ES2019)", () => {
  const liste = ["A", "B", "C", "D"].map((tk) => titre(tk, { eps_surprise: 0.1 }));
  assert.deepEqual(ordre(liste, "eps_surprise"), ["A", "B", "C", "D"]);
});

test("une date ISO se compare comme un nombre, pas comme du texte", () => {
  const liste = [
    titre("AOUT", { catalyst_8k_date: "2026-08-31" }),
    titre("SEPT", { catalyst_8k_date: "2026-09-01" }),
    titre("SANS", { catalyst_8k_date: null }),
  ];
  // Le plus récent d'abord : « 2026-09-01 » > « 2026-08-31 » une fois les tirets ôtés.
  assert.deepEqual(ordre(liste, "catalyst_8k_date"), ["SEPT", "AOUT", "SANS"]);
  assert.equal(SORT_VALUE.catalyst_8k_date({ catalyst_8k_date: null }), null);
});

test("les filtres de signe suivent la donnée, sans seuil calibré", () => {
  assert.equal(FLAG_FILTER.insiders_buy({ insider_transactions: 0.001 }), true);
  assert.equal(FLAG_FILTER.insiders_buy({ insider_transactions: 0 }), false);
  assert.equal(FLAG_FILTER.insiders_buy({ insider_transactions: -0.2 }), false);
  assert.equal(FLAG_FILTER.eps_beat({ eps_surprise: 0.084 }), true);
  assert.equal(FLAG_FILTER.rev_beat({ revenue_surprise: -0.019 }), false);
});

test("un drapeau absent ne passe aucun filtre, et aucun ne lève", () => {
  const vide = Object.fromEntries(
    Object.keys(SORT_VALUE).concat(["optionable", "shortable", "news_title"]).map((k) => [k, null]),
  );
  for (const [nom, garde] of Object.entries(FLAG_FILTER)) {
    assert.equal(garde(vide), false, `${nom} laisse passer un drapeau absent`);
  }
});

test("optionable et shortable exigent true, jamais une valeur seulement véridique", () => {
  // `false` et `null` se ressemblent à l'écran (rien n'est affiché) : le filtre, lui,
  // ne doit retenir que le `true` explicite.
  assert.equal(FLAG_FILTER.optionable({ optionable: true }), true);
  assert.equal(FLAG_FILTER.optionable({ optionable: false }), false);
  assert.equal(FLAG_FILTER.optionable({ optionable: 1 }), false);
  assert.equal(FLAG_FILTER.shortable({ shortable: "Yes" }), false);
});

test("chaque option de tri a bien une valeur, chaque filtre une garde", () => {
  // Un nom ajouté à l'écran sans entrée ici planterait au clic : le tri appellerait
  // `undefined`. Ce test tient la liste des clés que l'écran connaît.
  const triAttendu = [
    "short_float", "short_ratio", "insider_transactions", "institutional_transactions",
    "institutional_ownership", "eps_surprise", "revenue_surprise", "catalyst_8k_date",
    "news_date",
  ];
  const filtreAttendu = [
    "insiders_buy", "inst_buy", "eps_beat", "rev_beat",
    "optionable", "shortable", "catalyst", "news",
  ];
  assert.deepEqual(Object.keys(SORT_VALUE).sort(), [...triAttendu].sort());
  assert.deepEqual(Object.keys(FLAG_FILTER).sort(), [...filtreAttendu].sort());
});
