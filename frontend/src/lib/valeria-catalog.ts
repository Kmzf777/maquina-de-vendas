/**
 * Preço do catálogo da ValerIA (tabela `products`). O banco guarda TEXTO no
 * formato "R$ 1.234,56" — é o que vai pro prompt e o que `pricing.parse_brl`
 * (backend) lê. Não use Intl/toLocaleString: ele insere U+00A0 no lugar do
 * espaço e o texto deixa de bater com o resto do catálogo.
 */

export interface CatalogItem {
  id: string;
  sector: string;
  name: string;
  preco: number | null;
  price_formatted: string | null;
}

export const PRECO_MAXIMO = 99999;

export function formatPrecoCatalogo(valor: number): string {
  const centavos = Math.round(valor * 100);
  const inteiro = Math.floor(centavos / 100);
  const decimal = String(centavos % 100).padStart(2, "0");
  const milhar = String(inteiro).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `R$ ${milhar},${decimal}`;
}

/** Aceita "28,70", "28.70", "28,7", "1.169,70", "1169,70", "R$ 28,70". Lixo -> null. */
export function parsePrecoCatalogo(entrada: string | null | undefined): number | null {
  if (entrada == null) return null;
  const s = entrada.replace(/R\$/i, "").replace(/[\s ]/g, "");
  if (!/^\d[\d.,]*$/.test(s)) return null;

  let normal: string;
  const virgula = s.lastIndexOf(",");
  if (virgula >= 0) {
    // Vírgula é o decimal; pontos só podem ser milhar.
    if (s.indexOf(",") !== virgula) return null;
    const inteiro = s.slice(0, virgula);
    const decimal = s.slice(virgula + 1);
    if (decimal.length === 0 || decimal.length > 2) return null;
    if (inteiro.includes(".") && !/^\d{1,3}(\.\d{3})+$/.test(inteiro)) return null;
    normal = `${inteiro.replace(/\./g, "")}.${decimal}`;
  } else if (s.includes(".")) {
    // Só pontos: um único ponto seguido de 1-2 dígitos é decimal ("28.70");
    // grupos de 3 são milhar ("1.169").
    const ponto = s.lastIndexOf(".");
    const decimal = s.slice(ponto + 1);
    if (s.indexOf(".") === ponto && decimal.length >= 1 && decimal.length <= 2) normal = s;
    else if (/^\d{1,3}(\.\d{3})+$/.test(s)) normal = s.replace(/\./g, "");
    else return null;
  } else {
    normal = s;
  }

  const n = Number(normal);
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
}

export function precoValido(valor: unknown): valor is number {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return false;
  if (valor <= 0 || valor > PRECO_MAXIMO) return false;
  return Math.abs(valor * 100 - Math.round(valor * 100)) < 1e-6;
}
