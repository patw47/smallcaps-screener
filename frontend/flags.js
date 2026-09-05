// Tri et filtre sur les drapeaux de contexte — PUREMENT client : aucun paramètre de
// requête, aucune route ; la liste servie reste la même, l'écran la réordonne ou en
// masque des lignes.
//
// Sorti du composant à la clôture de l'Epic 14 pour une seule raison : sans React ni DOM,
// cette logique s'exerce par un test (`make test-frontend`). Elle n'a rien gagné d'autre
// au passage — mêmes tables, même comparateur qu'au S3.

// Valeur numérique d'un titre pour chaque critère de tri, `null` quand le drapeau manque.
export const SORT_VALUE = {
  short_float: (f) => f.short_float,
  short_ratio: (f) => f.short_ratio,
  insider_transactions: (f) => f.insider_transactions,
  institutional_transactions: (f) => f.institutional_transactions,
  institutional_ownership: (f) => f.institutional_ownership,
  eps_surprise: (f) => f.eps_surprise,
  revenue_surprise: (f) => f.revenue_surprise,
  // Dates ramenées à un entier comparable : le jour ISO perd ses tirets, l'horodatage de
  // news est déjà un nombre de secondes.
  catalyst_8k_date: (f) => (f.catalyst_8k_date ? Number(f.catalyst_8k_date.replaceAll("-", "")) : null),
  news_date: (f) => f.news_date,
};

// Filtres : « ce titre porte ce drapeau ». Le signe d'une transaction nette ou d'une
// surprise est la frontière que porte la donnée elle-même, pas un seuil calibré — aucun
// nombre de règle n'entre ici, ils vivent tous dans le bloc `display` servi par l'API.
// Un drapeau absent vaut null : chaque comparaison le rend faux, il sort proprement.
export const FLAG_FILTER = {
  insiders_buy: (f) => f.insider_transactions > 0,
  inst_buy: (f) => f.institutional_transactions > 0,
  eps_beat: (f) => f.eps_surprise > 0,
  rev_beat: (f) => f.revenue_surprise > 0,
  optionable: (f) => f.optionable === true,
  shortable: (f) => f.shortable === true,
  catalyst: (f) => f.catalyst_8k_date != null,
  news: (f) => f.news_title != null,
};

// Comparateur d'un tri par drapeau : valeur la plus forte d'abord, drapeau absent en fin
// de liste, et à valeur égale l'ordre précédent tient (le tri de JS est stable depuis
// ES2019). Il DÉPLACE, il ne masque rien — masquer serait un filtre.
export const flagCompare = (cle) => {
  const val = SORT_VALUE[cle];
  return (a, b) => {
    const x = val(a.context), y = val(b.context);
    return (x == null) - (y == null) || (y ?? 0) - (x ?? 0);
  };
};
