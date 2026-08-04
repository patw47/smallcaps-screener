// Gate anti-jargon de l'interface (Epic 8 S1, liste complétée au S3) — sort 0 si propre.
//
// Périmètre : les dictionnaires i18n (valeur par valeur, la clé fautive est
// nommée) et les CHAÎNES LITTÉRALES du JSX. Les commentaires du code sont retirés
// avant le scan : ils documentent l'architecture et n'atteignent jamais l'écran.
// Hors chaînes, le JSX manipule les champs techniques du payload (v4_cohort,
// display.v4…) dont les noms ne sont pas affichés — d'où le scan sur les seules
// chaînes plutôt que sur les lignes entières.
//
// Ajouter un terme = ajouter une entrée à BANNED.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const BANNED = [
  { re: /protocole?s?\b/i, what: "mot « protocole »" },
  { re: /§\s*\d/, what: "référence de section de protocole" },
  { re: /\bv[1-5]\b/i, what: "numéro de version d'une famille" },
  { re: /\bcohorte?s?\b/i, what: "mot « cohorte »" },
  { re: /\bvalidation\s+[a-d]\b/i, what: "numéro de validation" },
  { re: /\brepo\b/i, what: "mot « repo »" },
  { re: /in-sample/i, what: "terme « in-sample »" },
  { re: /r[ée]sidu|residual/i, what: "terme « résidu »" },
  { re: /\bCMF\b/i, what: "acronyme de flux d'argent" },
];

const I18N = ["frontend/i18n/fr.json", "frontend/i18n/en.json"];
const SKIP = new Set(["i18n", "node_modules", "dist", "v", "cache"]);
const EXT = /\.(jsx?|mjs)$/;
// Chaînes littérales simple/double quote (pas les gabarits : ils ne portent que du CSS).
const STRINGS = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g;

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

const scan = (where, text) => {
  if (text.includes("://")) return;  // URL : jamais du texte affiché (…/v1/messages)
  for (const { re, what } of BANNED) {
    if (re.test(text)) report(where, what, text);
  }
};

for (const file of I18N) {
  for (const [key, value] of Object.entries(JSON.parse(readFileSync(file, "utf8")))) {
    if (typeof value === "string") scan(`${file}:${key}`, value);
  }
}

for (const file of walk("frontend")) {
  stripComments(readFileSync(file, "utf8")).split("\n").forEach((line, i) => {
    for (const str of line.match(STRINGS) ?? []) scan(`${file}:${i + 1}`, str);
  });
}

if (!fail) console.log("check-jargon OK");
process.exit(fail);
