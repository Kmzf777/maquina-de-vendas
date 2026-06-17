// frontend/src/lib/lead-variables.ts
// Mirrors _LEAD_FIELD_TOKENS in backend/app/broadcast/worker.py
// (extraído de template-dispatch-modal.tsx para reuso nas respostas rápidas)

export type LeadLike = { name?: string | null; phone?: string | null; company?: string | null };

export const LEAD_RESOLVERS: Record<string, (l: LeadLike) => string> = {
  primeiro_nome: (l) => (l.name ?? "").split(" ")[0],
  nome_completo: (l) => l.name ?? "",
  telefone: (l) => l.phone ?? "",
  empresa: (l) => l.company ?? "",
  first_name: (l) => (l.name ?? "").split(" ")[0],
  lead_name: (l) => l.name ?? "",
  phone: (l) => l.phone ?? "",
};

// Resolve {{token}} em texto livre. Token desconhecido OU valor vazio → mantém {{token}}.
export function resolveLeadVariables(text: string, lead: LeadLike): string {
  return text.replace(/\{\{(\w+)\}\}/g, (full, token) => {
    const resolver = LEAD_RESOLVERS[token as string];
    if (!resolver) return full;
    return resolver(lead) || full;
  });
}
