export const AGENT_STAGES = [
  { key: "secretaria", label: "Secretaria", color: "bg-[#f4f4f0]" },
  { key: "atacado", label: "Atacado", color: "bg-[#dce8f0]" },
  { key: "private_label", label: "Private Label", color: "bg-[#e8dff0]" },
  { key: "exportacao", label: "Exportacao", color: "bg-[#d8f0dc]" },
  { key: "consumo", label: "Consumo", color: "bg-[#f0ecd0]" },
] as const;

export const SELLER_STAGES = [
  { key: "novo", label: "Novo", color: "bg-[#f0d8d8]" },
  { key: "em_contato", label: "Em Contato", color: "bg-[#f0e4d0]" },
  { key: "negociacao", label: "Negociacao", color: "bg-[#dce8f0]" },
  { key: "fechado", label: "Fechado", color: "bg-[#d8f0dc]" },
  { key: "perdido", label: "Perdido", color: "bg-[#f4f4f0]" },
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
