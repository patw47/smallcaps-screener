// Parité stricte des clés fr/en — liste les manquantes, sort 1 si écart.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const dir = dirname(fileURLToPath(import.meta.url));
const load = (f) => JSON.parse(readFileSync(join(dir, f), "utf8"));
const fr = load("fr.json"), en = load("en.json");

const missingIn = (a, b) => Object.keys(a).filter((k) => !(k in b));
const enMissing = missingIn(fr, en);
const frMissing = missingIn(en, fr);

if (enMissing.length) console.error(`Manquantes dans en.json :\n  ${enMissing.join("\n  ")}`);
if (frMissing.length) console.error(`Manquantes dans fr.json :\n  ${frMissing.join("\n  ")}`);
if (enMissing.length || frMissing.length) process.exit(1);
console.log(`i18n-parity OK (${Object.keys(fr).length} clés)`);
