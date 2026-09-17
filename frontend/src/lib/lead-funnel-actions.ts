import { isDealClosed, type LeadDeal } from "@/lib/deal-rows";

/**
 * Lógica pura da aba "Funis" do modal de lead — sem React e sem rede.
 * O tipo do card (`LeadDeal`) e a regra de fechamento (`isDealClosed`) vêm de
 * `deal-rows.ts`: é o mesmo card que o painel de /conversas já renderiza, e
 * duplicar o tipo aqui deixaria as duas telas divergirem na primeira coluna nova.
 */

/**
 * Primeiro card ABERTO do lead no funil dado, ou null. Base do aviso de
 * duplicata no modal de criação de card.
 *
 * Card já FECHADO naquele funil não conta: criar um novo card onde o anterior
 * foi ganho/perdido é justamente o fluxo de recompra/reposição, e avisar ali
 * treinaria o vendedor a ignorar o aviso.
 */
export function findOpenDealInPipeline(deals: LeadDeal[], pipelineId: string): LeadDeal | null {
  // Funil ainda não escolhido no formulário chega como "" — não existe card
  // "do funil vazio", e sem esta guarda um deal legado com pipeline_id null
  // casaria com a string vazia.
  if (!pipelineId) return null;
  return (
    deals.find((deal) => deal.pipeline_id === pipelineId && !isDealClosed(deal)) ?? null
  );
}

/**
 * Título convencional do card: "<nome do lead> - <nome do funil>".
 *
 * Espelha exatamente o `autoTitle` de `deal-create-modal.tsx`
 * (`${selectedLead?.name || selectedLead?.phone || "Lead"} - ${pipeline?.name || "Funil"}`),
 * para que um card criado pelo modal de lead nasça com o mesmo formato de um
 * criado pelo Kanban. O fallback do telefone é do chamador, que é quem tem o
 * lead em mão — aqui fica o fallback final "Lead".
 *
 * Aceita null/undefined porque `leads.name` é nullable no banco: o chamador
 * passa `lead.name || lead.phone` direto, sem coalescer antes.
 */
export function buildDealTitle(
  leadName: string | null | undefined,
  pipelineName: string | null | undefined,
): string {
  const nome = (leadName ?? "").trim() || "Lead";
  const funil = (pipelineName ?? "").trim() || "Funil";
  return `${nome} - ${funil}`;
}

/**
 * true quando o destino escolhido é onde o card já está — não vale gastar um
 * PATCH (e é o que desabilita o botão "Mover"). Exige os DOIS lados iguais:
 * mesmo funil com etapa diferente é um movimento válido, e mesma etapa em
 * outro funil também (o PATCH é que barra o par inconsistente).
 */
export function isSameTarget(deal: LeadDeal, pipelineId: string, stageId: string): boolean {
  // Deal legado sem funil/etapa (null) nunca é "o mesmo destino": um destino
  // escolhido é sempre um id concreto, e null == "" faria o botão morrer.
  if (!deal.pipeline_id || !deal.stage_id) return false;
  return deal.pipeline_id === pipelineId && deal.stage_id === stageId;
}
