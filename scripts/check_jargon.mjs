// Gate anti-jargon de l'interface (Epic 8 S1) — sort 0 si propre.
//
// Périmètre : les dictionnaires i18n (valeur par valeur, la clé fautive est
// nommée) et les CHAÎNES du JSX. Les commentaires du code sont retirés avant le
// scan : ils documentent l'architecture et n'atteignent jamais l'écran.
//
// La liste est initialisée au S1 (références de section de protocole + le mot
// « protocole ») et sera étendue au S3 — ajouter une entrée à BANNED suffit.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const BANNED = [
  { re: /protocole?s?\b/i, what: "mot « protocole »" },
  { re: /§\s*\d/, what: "référence de section de protocole" },
];

const I18N = ["frontend/i18n/fr.json", "frontend/i18n/en.json"];
const SKIP = new Set(["i18n", "node_modules", "dist", "v", "cache"]);
const EXT = /\.(jsx?|mjs)$/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { if (!SKIP.has(name)) yield* walk(p); }
    else if (EXT.test(name)) yield p;
  }
}

// Même heuristique que scripts/check_i18n.mjs : retire /* … */ puis // … (sauf «://»).
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

let fail = 0;
const report = (where, what, text) => {
  console.error(`${where}: ${what} — ${text.trim().slice(0, 110)}`);
  fail = 1;
};

for (const file of I18N) {
  for (const [key, value] of Object.entries(JSON.parse(readFileSync(file, "utf8")))) {
    if (typeof value !== "string") continue;
    for (const { re, what } of BANNED) {
      if (re.test(value)) report(`${file}:${key}`, what, value);
    }
  }
}

for (const file of walk("frontend")) {
  stripComments(readFileSync(file, "utf8")).split("\n").forEach((line, i) => {
    for (const { re, what } of BANNED) {
      if (re.test(line)) report(`${file}:${i + 1}`, what, line);
    }
  });
}

if (!fail) console.log("check-jargon OK");
process.exit(fail);
