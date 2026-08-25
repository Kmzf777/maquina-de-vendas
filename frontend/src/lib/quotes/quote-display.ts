/**
 * Derivacoes de exibicao do orcamento: rotulo da situacao, o que cada linha
 * permite fazer, e a taxa de aprovacao.
 *
 * Mora em `lib` e nao no componente porque e tudo o que pode dar errado nesta
 * tela: a suite do frontend nao tem runner de DOM, entao uma regra escrita
 * dentro do JSX e uma regra que nunca sera verificada. `quotes-table.tsx` e
 * `quotes-metrics-cards.tsx` sao casca em cima daqui.
 *
 * Gemeo do `sale-display.ts`, e o formato do `StatusTone` e o mesmo de la de
 * proposito — as duas tabelas ficam lado a lado no menu e um verde que so
 * significa "bom" numa delas seria ruido.
 */
import type { Quote } from "@/lib/types";

export type QuoteStatus = Quote["status"];

/**
 * `locked` e a razao de este tom existir separado de `neutral`: o convertido nao
 * e "mais um estado", e o fim da linha — a partir dele o orcamento nao volta.
 */
export type QuoteTone = "draft" | "waiting" | "approved" | "refused" | "locked";

export interface QuoteStatusView {
  label: string;
  tone: QuoteTone;
}

/**
 * Vocabulario da coluna "Situação".
 *
 * Os rotulos sao os do CRM, com acento e em caixa de frase — nao os enums do
 * Bling (`Não aprovado`, `Pendente`), que vivem em `bling_situacao` e existem
 * para o ERP, nao para o vendedor. "Enviado" e mais honesto que "Pendente" para
 * quem esta olhando: diz o que ele fez, nao o que o Bling acha.
 */
const STATUS_VIEW: Record<QuoteStatus, QuoteStatusView> = {
  rascunho: { label: "Rascunho", tone: "draft" },
  enviado: { label: "Enviado", tone: "waiting" },
  aprovado: { label: "Aprovado", tone: "approved" },
  nao_aprovado: { label: "Não aprovado", tone: "refused" },
  convertido: { label: "Convertido", tone: "locked" },
  cancelado: { label: "Cancelado", tone: "refused" },
};

/**
 * Situacao de um `status` vindo do banco.
 *
 * O fallback nao e zelo: `quotes.status` e `text` com DEFAULT, sem CHECK
 * constraint (ver a migration), entao um valor fora do vocabulario e uma
 * possibilidade real — um backfill, uma correcao manual no SQL editor. Sem o
 * fallback a celula renderizaria `undefined` e o acesso a `.tone` derrubaria a
 * tabela inteira; com ele a linha mostra o texto cru e o vendedor ve que ha algo
 * estranho ali, sem perder as outras vinte e quatro linhas.
 */
export function quoteStatus(status: string): QuoteStatusView {
  return STATUS_VIEW[status as QuoteStatus] ?? { label: status || "—", tone: "draft" };
}

/**
 * O orcamento ainda pode ser editado?
 *
 * Espelha o `409 {error:"quote_converted"}` do `PUT /api/quotes/{id}`: depois de
 * virar venda, o pedido ja existe no ERP e mexer nos itens da proposta contaria
 * uma historia diferente da que foi faturada. Esconder o botao e mais honesto
 * que deixa-lo abrir um formulario que o backend vai recusar no submit.
 */
export function podeEditar(quote: Pick<Quote, "status">): boolean {
  return quote.status !== "convertido";
}

/**
 * O orcamento ainda pode virar venda?
 *
 * So o `convertido` bloqueia — e o unico caso em que o backend responde
 * `409 {error:"already_converted"}`. Converter um "não aprovado" e estranho, mas
 * acontece (cliente volta atras) e a decisao e do vendedor, nao da tela.
 */
export function podeConverter(quote: Pick<Quote, "status">): boolean {
  return quote.status !== "convertido";
}

/**
 * O que aparece na coluna "Nº".
 *
 * Nulo e um estado esperado, nao um defeito: o `POST /propostas-comerciais`
 * devolve so `{data:{id}}` e o numero vem de um GET seguinte que e best-effort
 * (§2 da spec). Um orcamento sem numero existe no Bling e tem PDF — por isso a
 * celula mostra um traco e nao um erro.
 */
export function numeroDoOrcamento(quote: Pick<Quote, "bling_proposal_number">): string {
  return quote.bling_proposal_number ? `#${quote.bling_proposal_number}` : "—";
}

/** Os status que contam como aceite para a taxa de aprovacao. */
const APROVADOS: readonly QuoteStatus[] = ["aprovado", "convertido"];

/**
 * Um orcamento so entra no DENOMINADOR da taxa depois de sair do rascunho.
 *
 * Rascunho e trabalho em andamento: contar como "não aprovado ainda" faria a
 * taxa despencar toda vez que o vendedor comecasse a montar uma proposta, o que
 * transforma o indicador num desincentivo a usar a ferramenta.
 *
 * `cancelado` FICA no denominador de proposito, apesar de nunca ter chegado ao
 * cliente em alguns casos: e a definicao literal do §5 da spec ("todos menos
 * rascunho"), e tira-lo daria ao vendedor uma forma de melhorar a propria taxa
 * cancelando o que foi recusado.
 */
function decidido(status: string): boolean {
  return status !== "rascunho";
}

export interface ApprovalTally {
  /** Aprovados + convertidos. */
  approved: number;
  /** Todos menos os rascunhos. */
  decided: number;
}

/** Conta numerador e denominador da taxa a partir das situacoes do periodo. */
export function contarAprovacoes(statuses: readonly string[]): ApprovalTally {
  return {
    approved: statuses.filter((s) => APROVADOS.includes(s as QuoteStatus)).length,
    decided: statuses.filter(decidido).length,
  };
}

/**
 * Taxa de aprovacao em 0..1, ou `null` quando nao ha o que dividir.
 *
 * O `null` e o ponto inteiro desta funcao. Um periodo so com rascunhos — ou
 * vazio, que e como a tela abre para um vendedor novo — tem denominador zero, e
 * as duas saidas "naturais" mentem: `0/0` em JS da `NaN`, que renderiza
 * "NaN%" e parece um bug; e devolver `0` afirma que nada foi aprovado, quando o
 * verdadeiro e que nada foi decidido ainda. Nulo obriga quem chama a escolher um
 * traco.
 *
 * Denominador negativo ou fracionario nao acontece por construcao, mas a guarda
 * e `> 0` em vez de `!== 0` para que um dado corrompido caia no traco em vez de
 * produzir uma porcentagem negativa.
 */
export function taxaDeAprovacao(tally: ApprovalTally): number | null {
  if (!(tally.decided > 0)) return null;
  return tally.approved / tally.decided;
}

/**
 * A taxa como texto. `null` vira travessao — nunca "NaN%", nunca "0%".
 *
 * Sem casa decimal: a diferenca entre 62% e 62,4% nao muda nenhuma decisao, e o
 * numero inteiro le mais rapido num card que o vendedor olha de relance.
 */
export function formatarTaxa(taxa: number | null): string {
  if (taxa == null) return "—";
  return `${Math.round(taxa * 100)}%`;
}

/** R$ com duas casas, no formato que o resto do CRM usa. */
export function formatarBRL(valor: number): string {
  return `R$ ${Number(valor || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
