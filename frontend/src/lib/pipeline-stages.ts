/**
 * Etapas de um funil novo.
 *
 * Vocabulário decidido na reunião de 10/09/2026 (spec
 * docs/superpowers/specs/2026-09-10-funil-joao-motor-followup-design.md, D1):
 * "Negociação" e "Proposta" foram removidas e "Contato" virou "Em conversa".
 *
 * TODA etapa nasce com `key`. A ausência de key nas quatro primeiras etapas do
 * template antigo é a causa raiz de §2.1 do spec: o código de negócio resolve etapa
 * por key, e etapa sem key é invisível para ele. "Em conversa" usa `respondeu`
 * porque é a key que `advance_deal_on_reply` (backend/app/leads/service.py:1192)
 * procura como destino — adotá-la faz o movimento automático funcionar sem código
 * novo. O rótulo visível e a key são coisas diferentes, e é para isso que servem.
 *
 * `conversion_event` fica AUSENTE de propósito: preenchê-lo despacha o card para a
 * Meta CAPI e para o CSV do Google Ads. A migration 20260909 documenta por que isso
 * contamina a série "Conversões (Ads)".
 */
export const DEFAULT_STAGES = [
  { label: "Novo",             key: "novo",              dot_color: "#e07a7a", order_index: 0, is_protected: false },
  { label: "Em conversa",      key: "respondeu",         dot_color: "#d4a04a", order_index: 1, is_protected: false },
  { label: "Em atenção",       key: "em_atencao",        dot_color: "#c9457b", order_index: 2, is_protected: false },
  { label: "Proposta Enviada", key: "proposta_enviada",  dot_color: "#9b7abf", order_index: 3, is_protected: false },
  { label: "Fechado Ganho",    key: "fechado_ganho",     dot_color: "#5aad65", order_index: 4, is_protected: true  },
  { label: "Perdido",          key: "fechado_perdido",   dot_color: "#9ca3af", order_index: 5, is_protected: true  },
] as const;

/**
 * True se a etapa não pode ser apagada pela tela.
 *
 * O DELETE só checava se havia cards dentro. Uma etapa-contrato VAZIA passava na
 * guarda e sumia — foi exatamente assim que a `proposta_enviada` do funil
 * "João - Reposição" desapareceu, e com ela o movimento do orçamento naquele funil
 * (quotes/router.py:272 procura por key, não acha, devolve False com log info).
 */
export function stageIsProtectedByKey(key: string | null | undefined): boolean {
  return Boolean(key);
}
