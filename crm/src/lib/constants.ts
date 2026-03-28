export const AGENT_STAGES = [
  { key: "secretaria", label: "Secretaria", color: "bg-[#f4f4f0]", dotColor: "#c8cc8e", tintColor: "#f2f3eb", avatarColor: "#c8cc8e" },
  { key: "atacado", label: "Atacado", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5aad65" },
  { key: "private_label", label: "Private Label", color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "exportacao", label: "Exportacao", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#e8d44d" },
  { key: "consumo", label: "Consumo", color: "bg-[#f0ecd0]", dotColor: "#d4b84a", tintColor: "#f4f2ea", avatarColor: "#d4b84a" },
] as const;

export const SELLER_STAGES = [
  { key: "novo", label: "Novo", color: "bg-[#f0d8d8]", dotColor: "#e07a7a", tintColor: "#f6eeee", avatarColor: "#e07a7a" },
  { key: "em_contato", label: "Em Contato", color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "negociacao", label: "Negociacao", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
  { key: "fechado", label: "Fechado", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#5aad65" },
  { key: "perdido", label: "Perdido", color: "bg-[#f4f4f0]", dotColor: "#9ca3af", tintColor: "#f2f2f0", avatarColor: "#9ca3af" },
] as const;

export const CONVERSATION_TABS = [
  { key: "todos", label: "Todos" },
  { key: "atacado", label: "Atacado" },
  { key: "private_label", label: "Private Label" },
  { key: "exportacao", label: "Exportação" },
  { key: "consumo", label: "Consumo" },
  { key: "pessoal", label: "Pessoal" },
] as const;

export const CAMPAIGN_STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#f4f4f0] text-[#5f6368]",
  running: "bg-[#d8f0dc] text-[#2d6a3f]",
  paused: "bg-[#f0ecd0] text-[#8a7a2a]",
  completed: "bg-[#dce8f0] text-[#2a5a8a]",
};

export const LEAD_CHANNELS = [
  { key: "evolution", label: "WhatsApp", color: "#5aad65" },
  { key: "campaign", label: "Campanha", color: "#5b8aad" },
  { key: "manual", label: "Manual", color: "#ad9c4a" },
] as const;

export const CADENCE_STATUS_COLORS: Record<string, { dot: string; bg: string; text: string }> = {
  active: { dot: "#f59e0b", bg: "bg-[#fef3c7]", text: "text-[#92400e]" },
  responded: { dot: "#4ade80", bg: "bg-[#d8f0dc]", text: "text-[#2d6a3f]" },
  exhausted: { dot: "#f87171", bg: "bg-[#fee2e2]", text: "text-[#991b1b]" },
  cooled: { dot: "#9ca3af", bg: "bg-[#f4f4f0]", text: "text-[#5f6368]" },
};

export const CADENCE_STATUS_LABELS: Record<string, string> = {
  active: "Ativo",
  responded: "Respondeu",
  exhausted: "Esgotado",
  cooled: "Esfriado",
};
