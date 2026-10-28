// Interpolation {clé} des dictionnaires i18n — module pur (ni JSON ni DOM), donc
// testable par `node --test` sans Vite.
export const fmt = (tpl, vars = {}) =>
  tpl ? Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, v ?? "—"), tpl) : "";
