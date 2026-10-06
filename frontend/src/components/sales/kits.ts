/**
 * Kits de degustação no topo do seletor de produtos (call de 01/10): o kit é
 * venda direta, a mais comum da conversa, e se perdia no meio do catálogo por
 * ordem alfabética — às vezes nem vinha na primeira página.
 *
 * Critério por nome ("kit degust", sem caixa nem acento), o mesmo do P3/P6
 * para `sale_items.descricao`. Os SKUs mudam entre as duas contas Bling; o nome
 * é o que as duas têm em comum.
 */
import { foldText } from "@/lib/search";

export const TERMO_KIT = "kit degust";

export function ehKitDegustacao(nome: string | null | undefined): boolean {
  return !!nome && foldText(nome).includes(TERMO_KIT);
}

/** Kits primeiro, o resto depois — ordem relativa preservada nos dois grupos. */
export function kitsPrimeiro<T extends { nome: string }>(lista: T[]): T[] {
  const kits = lista.filter((p) => ehKitDegustacao(p.nome));
  if (kits.length === 0) return lista;
  return [...kits, ...lista.filter((p) => !ehKitDegustacao(p.nome))];
}

/** Kits buscados à parte + página do catálogo, sem repetir produto. */
export function comKitsNoTopo<T extends { id: number; nome: string }>(
  kits: T[],
  pagina: T[],
): T[] {
  const vistos = new Set<number>();
  const out: T[] = [];
  for (const p of [...kits.filter((k) => ehKitDegustacao(k.nome)), ...kitsPrimeiro(pagina)]) {
    if (vistos.has(p.id)) continue;
    vistos.add(p.id);
    out.push(p);
  }
  return out;
}
