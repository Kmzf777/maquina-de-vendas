/**
 * Lógica do formulário de pedido Bling, separada do componente.
 *
 * A suíte do frontend é de lógica pura (não há runner de DOM no projeto), então
 * tudo que pode dar errado mora aqui e é testado; o componente vira casca de
 * renderização.
 */
import {
  buildInstallments,
  itemTotal,
  orderTotal,
  type BlingInstallment,
} from "@/lib/bling";
import type { SaleItem } from "@/lib/types";

export interface BlingProduct {
  id: number;
  codigo: string | null;
  nome: string;
  preco: number | null;
  unidade: string | null;
  saldo_virtual: number | null;
}

export interface OrderLine {
  blingProductId: number | null;
  descricao: string;
  codigo: string | null;
  unidade: string | null;
  quantidade: number;
  valorUnitario: number;
  descontoPercentual: number;
}

export interface BlingPaymentMethod {
  id: number;
  descricao: string;
  padrao?: number | null;
}

export interface OrderMeta {
  leadId: string;
  dealId: string | null;
  soldAt: string;
  soldBy: string | null;
  paymentMethodId: number | null;
  terms: number[];
  notes: string;
}

export interface OrderPayloadResult {
  valid: boolean;
  total: number;
  installments: BlingInstallment[];
  payload: {
    lead_id: string;
    deal_id: string | null;
    sold_at: string;
    sold_by: string | null;
    notes: string;
    items: {
      bling_product_id: number;
      codigo: string | null;
      descricao: string;
      unidade: string | null;
      quantidade: number;
      valor_unitario: number;
      desconto_percentual: number;
    }[];
    payment: { method_id: number | null; terms: number[] };
  };
}

export function blankLine(): OrderLine {
  return {
    blingProductId: null,
    descricao: "",
    codigo: null,
    unidade: null,
    quantidade: 1,
    valorUnitario: 0,
    descontoPercentual: 0,
  };
}

export function addLine(linhas: OrderLine[]): OrderLine[] {
  return [...linhas, blankLine()];
}

/**
 * Linhas iniciais do formulário de edição, a partir dos `sale_items` que a
 * venda já tem no CRM.
 *
 * Existe porque `BlingOrderForm` nascia sempre com uma linha em branco, mesmo
 * em edição — e o PUT em `/pedidos/vendas/{id}` no Bling substitui os itens do
 * pedido pelo que estiver no formulário no momento do submit. Sem isto, abrir
 * a edição de um pedido de 11 itens para mudar uma observação e salvar apagava
 * os outros 10 itens no ERP.
 *
 * Lista vazia devolve uma linha em branco — nunca um formulário sem nenhuma
 * linha, que ninguém consegue usar.
 */
export function linesFromSaleItems(
  items: SaleItem[] | null | undefined,
): OrderLine[] {
  if (!items || items.length === 0) return [blankLine()];
  return [...items]
    .sort((a, b) => a.ordem - b.ordem)
    .map((item) => ({
      blingProductId: item.bling_product_id,
      descricao: item.descricao,
      codigo: item.codigo,
      // `sale_items` não guarda unidade — só existe no catálogo do Bling.
      // Fica sem efeito no payload; é puramente informativo na tela.
      unidade: null,
      quantidade: Number(item.quantidade),
      valorUnitario: Number(item.valor_unitario),
      descontoPercentual: Number(item.desconto_percentual),
    }));
}

/** Nunca deixa o formulário sem nenhuma linha. */
export function removeLine(linhas: OrderLine[], index: number): OrderLine[] {
  if (linhas.length <= 1) return linhas;
  return linhas.filter((_, i) => i !== index);
}

export function updateLine(
  linhas: OrderLine[],
  index: number,
  patch: Partial<OrderLine>,
): OrderLine[] {
  return linhas.map((linha, i) => (i === index ? { ...linha, ...patch } : linha));
}

export function applyProduct(
  linhas: OrderLine[],
  index: number,
  productId: number,
  produtos: BlingProduct[],
): OrderLine[] {
  const produto = produtos.find((p) => p.id === productId);
  if (!produto) return linhas;
  return updateLine(linhas, index, {
    blingProductId: produto.id,
    descricao: produto.nome,
    codigo: produto.codigo,
    unidade: produto.unidade,
    valorUnitario: produto.preco ?? 0,
  });
}

/** Total da linha já com o desconto — o que a coluna "Total" mostra. */
export function lineTotal(linha: OrderLine): number {
  return itemTotal({
    quantidade: linha.quantidade,
    valorUnitario: linha.valorUnitario,
    descontoPercentual: linha.descontoPercentual,
  });
}

/**
 * Forma de pagamento pré-selecionada: a marcada como padrão no Bling.
 *
 * Com uma única forma cadastrada, escolhe ela — não há decisão a tomar e é um
 * clique a menos. Com várias e nenhuma padrão devolve `null` de propósito: a
 * forma define as parcelas do financeiro, e chutar seria pior que perguntar.
 */
export function defaultPaymentMethodId(
  metodos: BlingPaymentMethod[],
): number | null {
  const padrao = metodos.find((m) => m.padrao === 1);
  if (padrao) return padrao.id;
  return metodos.length === 1 ? metodos[0].id : null;
}

function isComplete(linha: OrderLine): boolean {
  return !!linha.blingProductId && linha.quantidade > 0;
}

export function buildOrderPayload(
  linhas: OrderLine[],
  meta: OrderMeta,
): OrderPayloadResult {
  const completas = linhas.filter(isComplete);
  const total = orderTotal(
    completas.map((l) => ({
      quantidade: l.quantidade,
      valorUnitario: l.valorUnitario,
      descontoPercentual: l.descontoPercentual,
    })),
  );
  const terms = meta.terms.length ? meta.terms : [0];

  return {
    valid: completas.length > 0 && !!meta.paymentMethodId,
    total,
    installments: buildInstallments(total, terms, meta.soldAt),
    payload: {
      lead_id: meta.leadId,
      deal_id: meta.dealId,
      sold_at: meta.soldAt,
      sold_by: meta.soldBy,
      notes: meta.notes,
      items: completas.map((l) => ({
        bling_product_id: l.blingProductId as number,
        codigo: l.codigo,
        descricao: l.descricao,
        unidade: l.unidade,
        quantidade: l.quantidade,
        valor_unitario: l.valorUnitario,
        desconto_percentual: l.descontoPercentual,
      })),
      payment: { method_id: meta.paymentMethodId, terms },
    },
  };
}
