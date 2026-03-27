export const AGENT_STAGES = [
  { key: "secretaria", label: "Secretaria", color: "bg-gray-100" },
  { key: "atacado", label: "Atacado", color: "bg-blue-100" },
  { key: "private_label", label: "Private Label", color: "bg-purple-100" },
  { key: "exportacao", label: "Exportacao", color: "bg-green-100" },
  { key: "consumo", label: "Consumo", color: "bg-yellow-100" },
] as const;

export const SELLER_STAGES = [
  { key: "novo", label: "Novo", color: "bg-red-100" },
  { key: "em_contato", label: "Em Contato", color: "bg-orange-100" },
  { key: "negociacao", label: "Negociacao", color: "bg-blue-100" },
  { key: "fechado", label: "Fechado", color: "bg-green-100" },
  { key: "perdido", label: "Perdido", color: "bg-gray-100" },
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
  draft: "bg-gray-200 text-gray-700",
  running: "bg-green-200 text-green-700",
  paused: "bg-yellow-200 text-yellow-700",
  completed: "bg-blue-200 text-blue-700",
};
