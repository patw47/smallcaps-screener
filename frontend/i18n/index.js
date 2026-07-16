// Helper i18n maison (Epic 6 S3) — aucune lib. Dictionnaires plats fr/en,
// interpolation {placeholder} partagée avec les templates servis par l'API.
import fr from "./fr.json";
import en from "./en.json";

const DICTS = { fr, en };

export let lang = (typeof localStorage !== "undefined" && localStorage.getItem("lang")) || "fr";

export function setLang(l) {
  lang = l;
  localStorage.setItem("lang", l);
}

// Interpolation {clé} — sert aussi aux templates du bloc `display` de l'API.
export const fmt = (tpl, vars = {}) =>
  tpl ? Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, v ?? "—"), tpl) : "";

export const t = (key, vars) => fmt(DICTS[lang][key] ?? key, vars);
