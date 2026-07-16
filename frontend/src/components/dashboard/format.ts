// Formatadores compartilhados dos blocos do dashboard principal.

/** 0..1 → "12,5%" (pt-BR, até 1 casa decimal). */
export function fmtPct(rate: number): string {
  return `${(rate * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

// Moeda mora em ./currency.ts (dono único de formatação e conversão USD↔BRL).

/** Minutos → formato humano "38m" / "2h 10m". */
export function fmtDuration(minutes: number): string {
  const r = Math.round(minutes);
  if (r < 60) return `${r}m`;
  const h = Math.floor(r / 60);
  const m = r % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/** ISO → "12/07, 14:30" (pt-BR). */
export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Inteiro com separador pt-BR. */
export function fmtInt(n: number): string {
  return n.toLocaleString("pt-BR");
}
