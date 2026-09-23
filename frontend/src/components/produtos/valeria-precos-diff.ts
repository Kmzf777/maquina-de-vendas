import {
  formatPrecoCatalogo,
  parsePrecoCatalogo,
  precoValido,
  type CatalogItem,
} from "@/lib/valeria-catalog";

export interface Alteracoes {
  alteracoes: { id: string; preco: number }[];
  invalidos: string[];
}

/** Texto do input ao abrir o modal: "28,70" (sem o "R$ "), ou "" sem preço. */
export function textoInicial(item: CatalogItem): string {
  return item.preco === null ? "" : formatPrecoCatalogo(item.preco).replace(/^R\$ /, "");
}

export function calcularAlteracoes(
  itens: CatalogItem[],
  textos: Record<string, string>,
): Alteracoes {
  const alteracoes: Alteracoes["alteracoes"] = [];
  const invalidos: string[] = [];
  for (const item of itens) {
    const texto = textos[item.id];
    if (texto === undefined) continue;
    if (texto.trim() === "" && item.preco === null) continue; // continua sem preço
    const preco = parsePrecoCatalogo(texto);
    if (preco === null || !precoValido(preco)) {
      invalidos.push(item.id);
      continue;
    }
    if (preco !== item.preco) alteracoes.push({ id: item.id, preco });
  }
  return { alteracoes, invalidos };
}
