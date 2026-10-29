// Lecture du journal des alertes (payload de /api/alerts) — module pur, sans DOM ni
// i18n, donc testable par `node --test` (journal.test.js). Le JSX ne fait qu'afficher.
//
// État d'une case (ligne × horizon h) :
//   done    — rendement réalisé écrit par le job ;
//   pending — séance d'horizon pas encore close, ou close aujourd'hui (le job du soir
//             ne l'a peut-être pas encore traitée) ;
//   missing — séance d'horizon antérieure à la dernière séance close et toujours aucun
//             cours : titre retiré de la cote ou cotation suspendue. Compté à part, hors
//             moyenne — l'ignorer ferait disparaître sans bruit des cas souvent perdants.

export function cellState(line, h, lastSession) {
  if (line[`ret_${h}`] != null) return "done";
  const exit = line.exit?.[h];
  return exit && lastSession && exit < lastSession ? "missing" : "pending";
}

const mean = (xs) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);

export function summarize(payload) {
  const p = payload ?? {};
  const last = p.last_session ?? null;
  const horizons = p.horizons ?? [];
  const lines = [...(p.lines ?? [])].sort(
    (a, b) => b.session.localeCompare(a.session) || a.ticker.localeCompare(b.ticker),
  );
  const rows = lines.map((x) => ({
    ...x,
    cells: Object.fromEntries(horizons.map((h) => [h, cellState(x, h, last)])),
  }));
  const stats = horizons.map((h) => {
    const done = rows.filter((r) => r.cells[h] === "done");
    const ret = mean(done.map((r) => r[`ret_${h}`]));
    const iwm = mean(done.map((r) => r[`iwm_${h}`]));
    return {
      h,
      n: done.length,
      ret,
      iwm,
      excess: ret == null ? null : ret - iwm,
      missing: rows.filter((r) => r.cells[h] === "missing").length,
      pending: rows.filter((r) => r.cells[h] === "pending").length,
      net: p.net?.[h] ?? null,
    };
  });
  return {
    lastSession: last,
    today: rows.filter((r) => r.session === last),
    rows,
    stats,
    empty: rows.length === 0,
  };
}
