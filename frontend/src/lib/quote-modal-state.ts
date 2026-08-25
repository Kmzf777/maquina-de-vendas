/**
 * Regras do MODAL de orçamento que não são cálculo de dinheiro.
 *
 * O cálculo (subtotal, desconto, frete, total, parcelas) já mora em
 * `@/lib/quote-state`, que está commitado e é compartilhado com a página
 * `/orcamento`. Aqui ficam as decisões que só o modal toma e que, mesmo assim,
 * podem dar errado em silêncio: qual verbo HTTP usar, como ler os DOIS 409
 * diferentes que o backend devolve, como reexibir o desconto na edição e como
 * interpretar um número digitado em pt-BR.
 *
 * Tudo isso vive fora do componente porque a suíte do frontend é de lógica pura
 * (não há runner de DOM no projeto): o que está aqui é testado, o componente é
 * casca de renderização.
 */
import type { OrderLine, OrderPayloadResult } from "@/lib/bling-order-state";
import type { QuoteDiscount } from "@/lib/quote-state";
import type { BlingContactCandidate } from "@/components/sales/bling-contact-resolver";

/** Modalidades de frete aceitas em `transporte.freteModalidade` (§2 da spec). */
export const FREIGHT_MODES: { value: number; label: string }[] = [
  { value: 0, label: "CIF — por conta do remetente" },
  { value: 1, label: "FOB — por conta do destinatário" },
  { value: 2, label: "Terceiros" },
  { value: 3, label: "Próprio remetente" },
  { value: 4, label: "Próprio destinatário" },
  { value: 9, label: "Sem transporte" },
];

/**
 * Rótulo e cor de cada situação.
 *
 * A cor é sempre um ponto de 6px ao lado do texto, nunca o fundo do badge: a
 * paleta do `DESIGN.md` reserva as cores fortes para dado, não para decoração,
 * e a lista de orçamentos fica dentro de um painel já cheio de cartões.
 */
const STATUS: Record<string, { label: string; dot: string }> = {
  rascunho: { label: "Rascunho", dot: "#7b7b78" },
  enviado: { label: "Enviado", dot: "#111111" },
  aprovado: { label: "Aprovado", dot: "#1f9d57" },
  nao_aprovado: { label: "Não aprovado", dot: "#c41c1c" },
  convertido: { label: "Convertido em venda", dot: "#1f9d57" },
  cancelado: { label: "Cancelado", dot: "#7b7b78" },
};

/**
 * Situação desconhecida devolve o próprio código como rótulo, em vez de vazio:
 * uma migration futura que acrescente um status não pode deixar a linha do
 * orçamento com um espaço em branco onde deveria estar a situação.
 */
export function quoteStatusView(status: string): { label: string; dot: string } {
  return STATUS[status] ?? { label: status, dot: "#dedbd6" };
}

/** Criar é POST na coleção; editar é PUT no id. */
export function quoteRequest(
  editing?: { id: string } | null,
): { url: string; method: "POST" | "PUT" } {
  return editing?.id
    ? { url: `/api/quotes/${editing.id}`, method: "PUT" }
    : { url: "/api/quotes", method: "POST" };
}

/**
 * Desconto de cabeçalho como o vendedor digitou, para a edição reexibir.
 *
 * Lê `discount_input` + `discount_unit`, NUNCA `discount_value`: o valor em
 * reais é o resultado (10% de R$267,00 = R$26,70) e mostrá-lo no campo faria o
 * vendedor achar que o sistema trocou o desconto dele ao reabrir o orçamento.
 * É exatamente para isto que a §3 da spec guarda as três colunas.
 */
export function discountFromQuote(
  quote?: { discount_unit: "REAL" | "PERCENTUAL"; discount_input: number } | null,
): QuoteDiscount | null {
  if (!quote) return null;
  // `numeric` volta como string em algumas rotas do PostgREST — sem o Number()
  // a comparação com zero passaria e o campo nasceria com texto.
  const valor = Number(quote.discount_input);
  if (!Number.isFinite(valor) || valor <= 0) return null;
  return {
    valor,
    unidade: quote.discount_unit === "PERCENTUAL" ? "PERCENTUAL" : "REAL",
  };
}

/**
 * Dono do orçamento — o que vai em `created_by`.
 *
 * Na criação é quem está logado. Na **edição é sempre quem criou**: o escopo
 * por vendedor (§8 da spec) filtra exatamente por esta coluna, então mandar o
 * e-mail de quem está editando transferiria o orçamento para o admin que abriu
 * a tela só para corrigir um frete — e ele sumiria da lista do vendedor que o
 * fez, sem ninguém entender por quê.
 *
 * Orçamento antigo sem dono (ou dono em branco) cai para quem está editando:
 * é melhor ter um dono do que continuar invisível para todo mundo.
 */
export function quoteOwner(
  editing: { created_by: string | null } | null | undefined,
  currentUserEmail: string | null | undefined,
): string | null {
  return (editing?.created_by || currentUserEmail || "").trim() || null;
}

/**
 * Linhas do orçamento a partir do resultado que o `BlingOrderForm` publica.
 *
 * O formulário de itens é reaproveitado inteiro do fluxo de venda, e ele só
 * expõe para fora o `OrderPayloadResult` — não as `OrderLine[]` internas. Como
 * `buildQuotePayload` precisa das linhas para somar subtotal, desconto e frete,
 * esta é a tradução de volta.
 *
 * Só chegam aqui as linhas COMPLETAS (o `buildOrderPayload` já filtrou), que é
 * exatamente o que o `buildQuotePayload` também consideraria — nada se perde.
 * O campo que se perde com facilidade é a `unidade`: o item da proposta
 * comercial a envia ao Bling, então ela precisa sobreviver à volta.
 */
export function linesFromOrderPayload(
  result?: OrderPayloadResult | null,
): OrderLine[] {
  return (result?.payload.items ?? []).map((item) => ({
    blingProductId: item.bling_product_id,
    descricao: item.descricao,
    codigo: item.codigo,
    unidade: item.unidade,
    quantidade: item.quantidade,
    valorUnitario: item.valor_unitario,
    descontoPercentual: item.desconto_percentual,
  }));
}

export type QuoteSaveOutcome =
  | { kind: "saved"; id: string | null; numero: number | null; total: number | null }
  | {
      kind: "contact";
      status: "ambiguous" | "suggested" | "missing";
      reason?: string;
      candidates: BlingContactCandidate[];
    }
  | { kind: "converted" }
  | { kind: "error"; message: string };

const texto = (v: unknown): string | null =>
  typeof v === "string" && v.trim() ? v : null;

const numero = (v: unknown): number | null => {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};

/**
 * Traduz a resposta de `POST /api/quotes` e `PUT /api/quotes/{id}`.
 *
 * O ponto perigoso é que o backend usa **409 para duas coisas diferentes**, e a
 * distinção vive só no campo `error`:
 *
 * - `contact_unresolved` — o cliente não foi identificado no Bling; nada foi
 *   criado e o vendedor resolve pelo `BlingContactResolver`.
 * - `quote_converted` — o orçamento já virou venda e não aceita mais edição.
 *
 * Tratar os dois como um só abriria o resolvedor de contato (vazio) para um
 * orçamento convertido, e o vendedor ficaria cadastrando cliente para um PUT
 * que nunca vai passar. Por isso o 409 desconhecido cai em erro legível em vez
 * de "provavelmente é contato".
 */
export function quoteSaveOutcome(
  status: number,
  body: Record<string, unknown>,
): QuoteSaveOutcome {
  if (status === 200 || status === 201) {
    return {
      kind: "saved",
      id: texto(body.id),
      // O POST da proposta no Bling devolve só o id; o `numero` depende de um
      // GET seguinte que é best-effort no backend. Ausente não é falha.
      numero: numero(body.bling_proposal_number),
      total: numero(body.total),
    };
  }

  if (status === 409) {
    if (body.error === "quote_converted") return { kind: "converted" };

    const s = body.status;
    const ehContato =
      body.error === "contact_unresolved" ||
      s === "ambiguous" ||
      s === "suggested" ||
      s === "missing";
    if (ehContato) {
      return {
        kind: "contact",
        status: s === "ambiguous" || s === "suggested" ? s : "missing",
        reason: texto(body.reason) ?? undefined,
        candidates: Array.isArray(body.candidates)
          ? (body.candidates as BlingContactCandidate[])
          : [],
      };
    }
  }

  return {
    kind: "error",
    // A mensagem original do Bling é a que diz o que corrigir (422); o código
    // HTTP entra só quando o corpo não trouxe nada, para o vendedor ter o que
    // relatar em vez de "erro".
    message:
      [texto(body.message), texto(body.detail)].filter(Boolean).join(" ") ||
      texto(body.error) ||
      `Não foi possível salvar o orçamento (HTTP ${status}).`,
  };
}

/**
 * Número digitado em pt-BR.
 *
 * Vírgula é o separador decimal, e o ponto de milhar é descartado QUANDO há
 * vírgula: "1.250,00" no parse ingênuo (`replace(",", ".")`) vira `NaN` e cai
 * para 0 — o frete simplesmente sumiria do total sem nenhum aviso.
 *
 * Sem vírgula, o ponto continua sendo decimal ("12.5" = 12,5), que é como o
 * resto do app já se comporta e como um teclado numérico costuma entregar.
 * "1.250" sem centavos é ambíguo por natureza e resolve para 1,25 — a
 * alternativa (tratar como milhar) transformaria "1.25" em 125.
 *
 * Negativo vira 0: desconto e frete negativos são erro de digitação e furariam
 * as garantias de sinal do `quote-state`.
 */
export function parseDecimalInput(raw: string): number {
  const limpo = String(raw ?? "").trim().replace(/\s/g, "");
  if (!limpo) return 0;
  const normalizado = limpo.includes(",")
    ? limpo.replace(/\./g, "").replace(",", ".")
    : limpo;
  const n = Number(normalizado);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** "#13" ou "sem nº" — o número só existe depois que o Bling responde o GET. */
export function quoteNumberLabel(quote: {
  bling_proposal_number: number | null;
}): string {
  return quote.bling_proposal_number ? `#${quote.bling_proposal_number}` : "sem nº";
}

/** O PDF é sempre pelo id do orçamento, que existe mesmo sem número no Bling. */
export function quotePdfHref(quoteId: string): string {
  return `/api/quotes/${quoteId}/pdf`;
}

/**
 * "2026-08-25" -> "25/08/2026", sem passar por `Date`.
 *
 * `quotes.quoted_at` é uma coluna `date` (sem hora). `new Date("2026-08-25")` é
 * meia-noite **UTC**, e `toLocaleDateString("pt-BR")` em BRT (-3) devolve
 * 24/08 — todo orçamento apareceria com um dia a menos para o Brasil inteiro.
 * O mesmo cuidado que `diaMesAno` já toma com o vencimento das parcelas.
 */
export function formatQuoteDate(iso: string | null | undefined): string {
  const d = String(iso ?? "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(d)
    ? `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}`
    : "—";
}
