/**
 * Lógica do formulário de orçamento (proposta comercial no Bling), separada do
 * componente.
 *
 * Mesma divisão de trabalho de `bling-order-state.ts`: a suíte do frontend é de
 * lógica pura (não há runner de DOM no projeto), então tudo que pode dar errado
 * mora aqui e é testado; o modal vira casca de renderização.
 *
 * O que o orçamento acrescenta ao pedido de venda são só três coisas — desconto
 * de cabeçalho (em R$ ou em %), frete, e o par de observações — e é por isso que
 * a montagem de itens, o total do item e a divisão de parcelas são IMPORTADAS de
 * `@/lib/bling-order-state` e `@/lib/bling` em vez de reescritas. Reimplementar
 * a divisão de parcelas aqui criaria dois espelhos do backend em vez de um, e o
 * segundo iria divergir na primeira mudança.
 *
 * Toda a aritmética é feita em INTEIROS (centavos, e milésimos para o que o
 * usuário digita) para não acumular erro de ponto flutuante — ver o comentário
 * de `milesimos()` para o caso concreto que motivou isso.
 *
 * PARIDADE OBRIGATÓRIA com `backend/app/quotes/proposals.py`: `resolveDiscount`
 * e `quoteTotal` têm que devolver exatamente o mesmo número que
 * `resolve_discount` e `quote_total` em Python, centavo a centavo. O contrato
 * está tabelado em `quote-state-parity.test.ts`.
 */
import { buildInstallments, orderTotal, type BlingInstallment } from "@/lib/bling";
import { type OrderLine, blankLine } from "@/lib/bling-order-state";
import type { QuoteItem } from "@/lib/types";

/** O desconto de cabeçalho como o vendedor digitou: número + unidade. */
export interface QuoteDiscount {
  valor: number;
  unidade: "REAL" | "PERCENTUAL";
}

export interface QuoteMeta {
  leadId: string;
  dealId: string | null;
  conversationId: string | null;
  /** Data do orçamento, `YYYY-MM-DD`. É a base dos vencimentos das parcelas. */
  quotedAt: string;
  /** E-mail do vendedor — é o que o escopo por vendedor filtra depois (§8). */
  createdBy: string | null;
  discount: QuoteDiscount | null;
  freight: number;
  /** 0 CIF · 1 FOB · 2 Terceiros · 3 Próprio remetente · 4 Próprio destinatário · 9 Sem transporte. */
  freightMode: number | null;
  paymentMethodId: number | null;
  terms: number[];
  /** Vai para o PDF e para o Bling. */
  notes: string;
  /** Só para o Bling — nunca entra no PDF que o cliente recebe. */
  internalNotes: string;
}

export interface QuotePayloadResult {
  valid: boolean;
  subtotal: number;
  /** O desconto já resolvido em reais — o que o resumo mostra e o total desconta. */
  discount: number;
  freight: number;
  total: number;
  installments: BlingInstallment[];
  payload: {
    lead_id: string;
    deal_id: string | null;
    conversation_id: string | null;
    quoted_at: string;
    created_by: string | null;
    items: {
      bling_product_id: number;
      codigo: string | null;
      descricao: string;
      unidade: string | null;
      quantidade: number;
      valor_unitario: number;
      desconto_percentual: number;
    }[];
    discount: QuoteDiscount | null;
    freight: number;
    freight_mode: number | null;
    payment: { method_id: number | null; terms: number[] };
    notes: string;
    internal_notes: string;
  };
}

const MILESIMOS = 1000;

/**
 * O valor digitado pelo usuário em MILÉSIMOS inteiros.
 *
 * Existe porque o caminho óbvio — `Math.round(valor * 100)` — diverge do
 * `Decimal.quantize(ROUND_HALF_UP)` do backend justamente no meio do centavo,
 * que é onde o arredondamento importa: `2.675 * 100` dá 267,49999999999997 em
 * binário, então o JS arredonda para 2,67 enquanto o Python dá 2,68. Passando
 * por milésimos o numerador vira inteiro exato (2675) e a divisão por 10 cai em
 * 267,5, que o `Math.round` sobe — igual ao HALF_UP.
 *
 * Três casas também é exatamente o que `quotes.discount_input numeric(12,3)`
 * guarda: uma quarta casa não sobreviveria ao INSERT, então também não pode
 * mudar o número que a tela mostra.
 */
const milesimos = (valor: number): number =>
  Math.round((Number(valor) || 0) * MILESIMOS);

/** Reais -> centavos inteiros, passando por milésimos (ver `milesimos`). */
const centavos = (valor: number): number => Math.round(milesimos(valor) / 10);

const reais = (centavosInteiros: number): number =>
  Math.round(centavosInteiros) / 100;

/**
 * Linha que vale dinheiro: produto escolhido no catálogo e quantidade positiva.
 *
 * Mesma regra do `buildOrderPayload` — o predicado é privado lá e é curto
 * demais para justificar um import só dele, mas as duas definições PRECISAM
 * continuar iguais: é ela que decide o que entra no subtotal e o que vai no
 * POST.
 */
function isComplete(linha: OrderLine): boolean {
  return !!linha.blingProductId && linha.quantidade > 0;
}

/**
 * Desconto de cabeçalho convertido para reais.
 *
 * `PERCENTUAL` incide sobre o subtotal (que já vem com os descontos de item
 * aplicados); `REAL` é o valor absoluto. Nos dois casos SATURA no subtotal: um
 * desconto maior que o pedido é erro de digitação, e deixá-lo passar produziria
 * total negativo — parcela negativa no Bling, receita negativa em `quotes.total`.
 * Isto é o oposto do que `apply_discount` faz no pedido de venda, onde o valor
 * negativo é deixado de propósito para aparecer na mensagem de erro; aqui o
 * vendedor vê o resumo antes de salvar, então saturar é o que ele consegue
 * entender sem ler um 422.
 *
 * Sem desconto (nulo, zero ou negativo) devolve 0 — nunca crédito.
 */
export function resolveDiscount(
  subtotal: number,
  d: QuoteDiscount | null | undefined,
): number {
  const subtotalCentavos = centavos(subtotal);
  if (!d || subtotalCentavos <= 0) return 0;

  const valorMilesimos = milesimos(d.valor);
  if (valorMilesimos <= 0) return 0;

  const bruto =
    d.unidade === "PERCENTUAL"
      // Numerador inteiro (centavos × milésimos) dividido por 100 × 1000: sem
      // isso, 23,58% de R$3.525,00 dá 831,19 no JS e 831,20 no Decimal do
      // backend — um centavo de divergência que o Bling recusa em silêncio.
      ? Math.round((subtotalCentavos * valorMilesimos) / (100 * MILESIMOS))
      : Math.round(valorMilesimos / 10);

  return reais(Math.min(bruto, subtotalCentavos));
}

/**
 * Soma das linhas, cada uma já com o seu desconto de item — o "Subtotal" do
 * resumo.
 *
 * Só conta linha completa, pela mesma razão que o payload só envia linha
 * completa: um valor digitado numa linha sem produto escolhido não vai para o
 * Bling, e somá-lo aqui faria o resumo prometer um total que o POST não confirma.
 */
export function quoteSubtotal(linhas: OrderLine[]): number {
  return orderTotal(
    linhas.filter(isComplete).map((l) => ({
      quantidade: l.quantidade,
      valorUnitario: l.valorUnitario,
      descontoPercentual: l.descontoPercentual,
    })),
  );
}

/**
 * `subtotal - desconto + frete`, em centavos.
 *
 * O frete ENTRA no total e é parcelado junto (§4 da spec): é dinheiro que o
 * cliente vai pagar, e deixá-lo fora faria a soma das parcelas não fechar com o
 * total da proposta — recusa do Bling.
 *
 * Não clampa em zero de propósito: é espelho literal do `quote_total` do
 * backend, e quem impede o total negativo é a saturação do `resolveDiscount`.
 * Um clamp só deste lado criaria exatamente a divergência que o teste de
 * paridade existe para impedir.
 */
export function quoteTotal(
  subtotal: number,
  descontoEmReais: number,
  frete: number,
): number {
  return reais(centavos(subtotal) - centavos(descontoEmReais) + centavos(frete));
}

/**
 * Corpo do `POST/PUT /api/quotes` (o `QuoteIn` do backend) mais os números que o
 * resumo da tela mostra, calculados uma única vez.
 *
 * `valid` exige ao menos uma linha completa E forma de pagamento escolhida: as
 * `parcelas[]` são obrigatórias no POST da proposta comercial no Bling e cada
 * parcela carrega a forma, então sem ela não há o que enviar.
 */
export function buildQuotePayload(
  linhas: OrderLine[],
  meta: QuoteMeta,
): QuotePayloadResult {
  const completas = linhas.filter(isComplete);
  const subtotal = quoteSubtotal(completas);
  const discount = resolveDiscount(subtotal, meta.discount);
  // Frete negativo seria desconto disfarçado — e furaria a garantia de que o
  // total nunca fica abaixo de zero, já que a saturação do desconto só olha o
  // subtotal.
  const freight = Math.max(0, reais(centavos(meta.freight)));
  const total = quoteTotal(subtotal, discount, freight);
  const terms = meta.terms.length ? meta.terms : [0];

  // Vai o PAR digitado, não o valor já convertido: `quotes` guarda
  // `discount_unit` + `discount_input` para a edição reexibir "10%" no campo
  // onde o vendedor digitou 10 — se mandássemos só os reais, reabrir o
  // orçamento mostraria "26,70" e ele acharia que o sistema mudou o desconto.
  // O número vai normalizado em milésimos para o backend recalcular a partir
  // EXATAMENTE do valor que a tela usou (a coluna é numeric(12,3)).
  const discountInput =
    meta.discount && milesimos(meta.discount.valor) > 0
      ? {
          valor: milesimos(meta.discount.valor) / MILESIMOS,
          unidade: meta.discount.unidade,
        }
      : null;

  return {
    valid: completas.length > 0 && !!meta.paymentMethodId,
    subtotal,
    discount,
    freight,
    total,
    // As parcelas saem do total COM frete e COM desconto — é o que o cliente
    // paga. `buildInstallments` devolve [] quando não sobra centavo para
    // dividir; o resumo mostra nada, em vez de uma parcela de R$ 0,00 que o
    // backend recusaria com 422.
    installments: buildInstallments(total, terms, meta.quotedAt),
    payload: {
      lead_id: meta.leadId,
      deal_id: meta.dealId,
      conversation_id: meta.conversationId,
      quoted_at: meta.quotedAt,
      created_by: meta.createdBy,
      items: completas.map((l) => ({
        bling_product_id: l.blingProductId as number,
        codigo: l.codigo,
        descricao: l.descricao,
        // A proposta comercial manda `unidade` no item (diferente de
        // `sale_items`, que não guarda esse campo) — por isso a linha carrega a
        // unidade do catálogo até aqui.
        unidade: l.unidade,
        quantidade: l.quantidade,
        valor_unitario: l.valorUnitario,
        desconto_percentual: l.descontoPercentual,
      })),
      discount: discountInput,
      freight,
      freight_mode: meta.freightMode,
      payment: { method_id: meta.paymentMethodId, terms },
      notes: meta.notes,
      internal_notes: meta.internalNotes,
    },
  };
}

/**
 * Linhas iniciais do formulário de edição, a partir dos `quote_items` já
 * gravados.
 *
 * Gêmeo do `linesFromSaleItems`, e existe pelo mesmo motivo: o PUT em
 * `/propostas-comerciais/{id}` SUBSTITUI os itens da proposta pelo que estiver
 * no formulário no momento do submit. Se a tela de edição nascesse com uma linha
 * em branco, abrir um orçamento de 11 itens só para mudar o frete e salvar
 * apagaria os 11 itens no ERP.
 *
 * Diferença para a venda: `quote_items` guarda `unidade`, então ela volta
 * preenchida — o item da proposta precisa dela no payload.
 *
 * Lista vazia (ou nula) devolve uma linha em branco — nunca um formulário sem
 * linha nenhuma, que ninguém consegue usar.
 */
export function linesFromQuoteItems(
  items: QuoteItem[] | null | undefined,
): OrderLine[] {
  if (!items || items.length === 0) return [blankLine()];
  return [...items]
    .sort((a, b) => a.ordem - b.ordem)
    .map((item) => ({
      blingProductId: item.bling_product_id,
      descricao: item.descricao,
      codigo: item.codigo,
      unidade: item.unidade,
      // `numeric` volta como string em algumas rotas do PostgREST; sem o
      // Number() a quantidade viraria texto e a aritmética concatenaria.
      quantidade: Number(item.quantidade),
      valorUnitario: Number(item.valor_unitario),
      descontoPercentual: Number(item.desconto_percentual),
    }));
}
