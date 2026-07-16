// Gate anti-régression i18n (Epic 6 S3) — sort 0 si propre.
// Heuristique : aucun caractère accentué dans le code frontend hors frontend/i18n/
// (une chaîne UI française en dur contient presque toujours un accent).
// Les commentaires sont retirés avant le scan — ils restent libres d'être en français.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SKIP = new Set(["i18n", "node_modules", "dist", "v", "cache"]);
const EXT = /\.(jsx?|mjs|html|css)$/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { if (!SKIP.has(name)) yield* walk(p); }
    else if (EXT.test(name)) yield p;
  }
}

// Retire /* … */ (y compris {/* … */} JSX) puis les commentaires // — sauf «://»
// (URLs dans les chaînes). ponytail: heuristique regex, pas un parseur JS — suffit
// tant qu'aucune chaîne ne contient « // » hors URL.
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

let fail = 0;
for (const file of walk("frontend")) {
  const lines = stripComments(readFileSync(file, "utf8")).split("\n");
  lines.forEach((line, i) => {
    if (/[À-ÖØ-öø-ÿŒœ]/.test(line)) {
      console.error(`${file}:${i + 1}: chaîne accentuée hors i18n : ${line.trim().slice(0, 90)}`);
      fail = 1;
    }
  });
}
if (!fail) console.log("check-i18n OK");
process.exit(fail);
