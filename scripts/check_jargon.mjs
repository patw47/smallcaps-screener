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
// Les deux formes de texte destiné à l'écran. Le reste d'une ligne de JSX est du
// code (v4_cohort, display.v4, la variable v4…) : des identifiants, jamais affichés.
const SCANNABLE = [
  // chaînes littérales simple/double quote (pas les gabarits : ils ne portent que du CSS)
  /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g,
  // texte JSX entre deux balises, sans expression {…} — <span>Cohorte v4</span>
  />([^<>{}]+)</g,
  // texte JSX ENTRE deux expressions — {n} titres de cohorte {suite}. Laissé de côté
  // jusqu'ici parce qu'un `[>}]…[<{]` naïf attrape aussi du JS courant (`} else if (…) {`).
  // Écarter les fragments qui portent de la syntaxe (parenthèses, `;`, `=`) suffit à les
  // distinguer : du texte destiné à l'écran n'en contient pas. Il doit aussi porter au
  // moins une lettre — « } : { » n'est pas une phrase.
  /\}([^<>{}();=]*[A-Za-zÀ-ÿ][^<>{}();=]*)\{/g,
];

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
  const clean = text.replace(/\w+:\/\/\S+/g, " ");  // retire les URL (…/v1/messages), pas la phrase
  for (const { re, what } of BANNED) {
    if (re.test(clean)) report(where, what, text);
  }
};

// ponytail: numéro de ligne recalculé par occurrence — fichiers de quelques
// centaines de lignes, un index cumulé ne se justifierait pas.
const lineOf = (src, idx) => src.slice(0, idx).split("\n").length;

for (const file of I18N) {
  for (const [key, value] of Object.entries(JSON.parse(readFileSync(file, "utf8")))) {
    if (typeof value === "string") scan(`${file}:${key}`, value);
  }
}

for (const file of walk("frontend")) {
  const src = stripComments(readFileSync(file, "utf8"));
  for (const re of SCANNABLE) {
    for (const m of src.matchAll(re)) scan(`${file}:${lineOf(src, m.index)}`, m[1] ?? m[0]);
  }
}

if (!fail) console.log("check-jargon OK");
process.exit(fail);
