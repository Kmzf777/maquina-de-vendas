export const AGENT_STAGES = [
  { key: "secretaria", label: "Secretaria", color: "bg-[#f4f4f0]", dotColor: "#c8cc8e", tintColor: "#f2f3eb", avatarColor: "#c8cc8e" },
  { key: "atacado", label: "Atacado", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5aad65" },
  { key: "private_label", label: "Private Label", color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "exportacao", label: "Exportacao", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#e8d44d" },
  { key: "consumo", label: "Consumo", color: "bg-[#f0ecd0]", dotColor: "#d4b84a", tintColor: "#f4f2ea", avatarColor: "#d4b84a" },
] as const;

// Vocabulário COMPLETO de etapas de funil. Ele tem dois usos, e é por isso que as
// keys abolidas continuam aqui:
//
//  1. TRADUZIR key -> rótulo (`STAGE_LABELS` em lib/lead-overview.ts, e o badge
//     colorido de lead-detail-modal.tsx). Isto precisa conhecer TODA key que já
//     existiu, senão deal histórico passa a exibir a key crua na tela.
//  2. OFERECER etapas na configuração de cadência. Este uso NÃO pode listar etapa
//     abolida — o dropdown grava a key alvo do gatilho, e uma key que não existe
//     mais em pipeline_stages nunca casa, sem erro visível.
//
// `legacy: true` separa os dois: entra na tradução, fica fora do que se oferece.
// Reunião de 10/09/2026: "Contato", "Proposta" e "Negociação" saíram dos funis;
// "Em conversa" usa a key `respondeu`, que é a que advance_deal_on_reply já procura.
//
// A ordem deste array é a ordem exibida — as legacy ficam no fim, fora do caminho.
export const DEAL_STAGES = [
  { key: "novo", label: "Novo", legacy: false, color: "bg-[#f0d8d8]", dotColor: "#e07a7a", tintColor: "#f6eeee", avatarColor: "#e07a7a" },
  { key: "respondeu", label: "Em conversa", legacy: false, color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "chamado_reposicao", label: "Já chamado (reposição)", legacy: false, color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
  { key: "em_atencao", label: "Em atenção", legacy: false, color: "bg-[#f7d9e4]", dotColor: "#c9457b", tintColor: "#f9eef3", avatarColor: "#c9457b" },
  { key: "proposta_enviada", label: "Proposta Enviada", legacy: false, color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "fechado_ganho", label: "Fechado Ganho", legacy: false, color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#5aad65" },
  { key: "fechado_perdido", label: "Perdido", legacy: false, color: "bg-[#f4f4f0]", dotColor: "#9ca3af", tintColor: "#f2f2f0", avatarColor: "#9ca3af" },
  // Abolidas na reunião de 10/09/2026. Mantidas SÓ para traduzir dado histórico.
  { key: "contato", label: "Contato", legacy: true, color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "proposta", label: "Proposta", legacy: true, color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "negociacao", label: "Negociacao", legacy: true, color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
] as const;

// O que a tela de cadência pode oferecer. Ver o comentário acima: oferecer etapa
// abolida cria gatilho que nunca casa, e falha em silêncio.
export const OFFERABLE_DEAL_STAGES = DEAL_STAGES.filter((s) => !s.legacy);

export const DEAL_CATEGORIES = [
  { key: "atacado", label: "Atacado", color: "#5b8aad" },
  { key: "private_label", label: "Private Label", color: "#9b7abf" },
  { key: "exportacao", label: "Exportacao", color: "#5aad65" },
  { key: "consumo", label: "Consumo", color: "#d4b84a" },
] as const;

export const UNREAD_TAB_KEY = "nao_lidas" as const;

export const CONVERSATION_TABS = [
  { key: "todos", label: "Todos" },
  { key: "atacado", label: "Atacado" },
  { key: "private_label", label: "Private Label" },
  { key: "exportacao", label: "Exportação" },
  { key: "consumo", label: "Consumo" },
  { key: "pessoal", label: "Pessoal" },
] as const;

export const BROADCAST_STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#f4f4f0] text-[#5f6368]",
  scheduled: "bg-[#f0ecd0] text-[#8a7a2a]",
  running: "bg-[#d8f0dc] text-[#2d6a3f]",
  paused: "bg-[#f0ecd0] text-[#8a7a2a]",
  completed: "bg-[#dce8f0] text-[#2a5a8a]",
};

export const CADENCE_TARGET_LABELS: Record<string, string> = {
  manual: "Manual",
  lead_stage: "Stage do Lead",
  deal_stage: "Stage do Deal",
};

export const LEAD_CHANNELS = [
  { key: "evolution", label: "WhatsApp", color: "#5aad65" },
  { key: "campaign", label: "Campanha", color: "#5b8aad" },
  { key: "manual", label: "Manual", color: "#ad9c4a" },
] as const;

export const LP_ORIGINS = [
  { key: "graocafeteria", label: "Grão Cafeteria", color: "#65b5ff" },
  { key: "atacado", label: "Atacado", color: "#0bdf50" },
  { key: "terceirizacao", label: "Terceirização", color: "#fe4c02" },
  { key: "Chat WhatsApp", label: "Chat WhatsApp", color: "#ff2067" },
] as const;

export const ENROLLMENT_STATUS_COLORS: Record<string, { dot: string; bg: string; text: string }> = {
  active: { dot: "#f59e0b", bg: "bg-[#fef3c7]", text: "text-[#92400e]" },
  paused: { dot: "#9ca3af", bg: "bg-[#f4f4f0]", text: "text-[#5f6368]" },
  responded: { dot: "#4ade80", bg: "bg-[#d8f0dc]", text: "text-[#2d6a3f]" },
  exhausted: { dot: "#f87171", bg: "bg-[#fee2e2]", text: "text-[#991b1b]" },
  completed: { dot: "#5b8aad", bg: "bg-[#dce8f0]", text: "text-[#2a5a8a]" },
};

export const ENROLLMENT_STATUS_LABELS: Record<string, string> = {
  active: "Ativo",
  paused: "Pausado",
  responded: "Respondeu",
  exhausted: "Esgotado",
  completed: "Completou",
};

/**
 * Tag fixa de inadimplência. O modal de criação de disparo depende dela para
 * avisar quando há leads com débito vencido entre os selecionados, então o
 * UUID é estável entre ambientes e a API bloqueia rename/exclusão dessa tag.
 *
 * Duplicado em scripts/reativacao/lote_completo.py (TAG_DEBITO_ID) — os dois
 * lados não compartilham runtime. Mudar aqui exige mudar lá.
 */
export const TAG_DEBITO_VENCIDO_ID = "3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210";
