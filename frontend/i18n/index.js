// Helper i18n maison (Epic 6 S3) — aucune lib. Dictionnaires plats fr/en,
// interpolation {placeholder}.
import fr from "./fr.json";
import en from "./en.json";
import { fmt } from "./fmt.js";

const DICTS = { fr, en };

export let lang = (typeof localStorage !== "undefined" && localStorage.getItem("lang")) || "fr";

export function setLang(l) {
  lang = l;
  localStorage.setItem("lang", l);
}

export { fmt };

export const t = (key, vars) => fmt(DICTS[lang][key] ?? key, vars);
