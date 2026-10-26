// D7 (cartao 1e6381fe): receita = valor - frete, so de venda nao cancelada, e o
// dia da venda e o dia de Brasilia. Espelho de backend/app/utils/receita_venda.py.

export type VendaComValor = {
  value?: number | string | null;
  freight?: number | string | null;
  status?: string | null;
};

function num(v: number | string | null | undefined): number {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function centavos(v: number): number {
  return Math.round(v * 100) / 100;
}

export function vendaCancelada(sale: Pick<VendaComValor, "status">): boolean {
  return String(sale.status ?? "").trim().toLowerCase().startsWith("cancel");
}

export function receitaDaVenda(sale: VendaComValor): number {
  if (vendaCancelada(sale)) return 0;
  return centavos(num(sale.value) - num(sale.freight));
}

export function freteDaVenda(sale: VendaComValor): number {
  if (vendaCancelada(sale)) return 0;
  return centavos(num(sale.freight));
}

// Limites de um periodo dado em datas (AAAA-MM-DD) no fuso de Brasilia. Valor que
// nao e data pura (instante completo) passa como veio.
export function limitesDoDiaBRT(
  from: string | null | undefined,
  to: string | null | undefined,
): { gte: string | null; lte: string | null } {
  const gte = from ? (from.length === 10 ? `${from}T00:00:00.000-03:00` : from) : null;
  const lte = to ? (to.length === 10 ? `${to}T23:59:59.999-03:00` : to) : null;
  return { gte, lte };
}
