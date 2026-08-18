/**
 * Cálculos do pedido Bling no cliente.
 *
 * A divisão de parcelas aqui precisa produzir EXATAMENTE o mesmo resultado que
 * `build_installments` em `backend/app/bling/orders.py` — o vendedor vê o valor
 * das parcelas antes de salvar, e o backend recalcula na hora de montar o
 * payload. Divergência de um centavo entre os dois vira recusa do Bling.
 *
 * Toda a aritmética é feita em CENTAVOS (inteiros) para não acumular erro de
 * ponto flutuante.
 */

export interface BlingLineItem {
  quantidade: number;
  valorUnitario: number;
  descontoPercentual: number;
}

export interface BlingInstallment {
  dataVencimento: string;
  valor: number;
}

const cents = (valor: number): number => Math.round(valor * 100);
const reais = (centavos: number): number => Math.round(centavos) / 100;

/** "30/60/90" -> [30, 60, 90]. Vazio ou não numérico -> [0] (à vista). */
export function parseTerms(raw: string | null | undefined): number[] {
  if (!raw) return [0];
  const dias = String(raw)
    .replace(/,/g, "/")
    .split("/")
    .map((p) => p.trim())
    .filter((p) => /^\d+$/.test(p))
    .map((p) => parseInt(p, 10));
  return dias.length ? dias : [0];
}

export function itemTotal(item: BlingLineItem): number {
  const bruto = cents(item.quantidade * item.valorUnitario);
  const desconto = (item.descontoPercentual || 0) / 100;
  return reais(bruto * (1 - desconto));
}

export function orderTotal(itens: BlingLineItem[]): number {
  return reais(itens.reduce((acc, i) => acc + cents(itemTotal(i)), 0));
}

export function buildInstallments(
  total: number,
  terms: number[],
  soldAt: string,
): BlingInstallment[] {
  const prazos = terms.length ? terms : [0];
  const totalCentavos = cents(total);
  const n = prazos.length;
  const base = Math.round(totalCentavos / n);
  // O backend RECUSA divisões em que alguma parcela ficaria sem valor
  // (`base > 0 && ultima > 0` em `build_installments`). Só acontece abaixo de
  // R$0,66 — nenhuma venda real — mas sem esta checagem o modal exibiria uma
  // parcela de R$0,00 e o backend devolveria 422 sem o vendedor entender por quê.
  const ultimaCentavos = totalCentavos - base * (n - 1);
  if (base <= 0 || ultimaCentavos <= 0) return [];

  return prazos.map((dias, i) => {
    // A última parcela absorve o resto: 100,00/3 = 33,33 + 33,33 + 33,34.
    // `base` usa Math.round (half-up), NUNCA Math.floor — ver o teste de
    // paridade. Floor fecha a soma igual, mas divide diferente do backend em
    // quase metade dos totais, e a divergência é silenciosa.
    const valorCentavos = i < n - 1 ? base : totalCentavos - base * (n - 1);
    const vencimento = new Date(`${soldAt}T12:00:00Z`);
    vencimento.setUTCDate(vencimento.getUTCDate() + dias);
    return {
      dataVencimento: vencimento.toISOString().slice(0, 10),
      valor: reais(valorCentavos),
    };
  });
}

export function productSummary(itens: { descricao: string }[]): string {
  if (!itens.length) return "Pedido Bling";
  const primeiro = itens[0].descricao || "Item";
  return itens.length === 1 ? primeiro : `${primeiro} +${itens.length - 1} itens`;
}
