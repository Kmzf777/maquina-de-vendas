import type { Conversation } from "@/lib/types";

/**
 * Diferenciação Inbound/Outbound da IA no card.
 *
 * Fonte de verdade: `conv.agent_persona` — a persona EFETIVA que o backend realmente rodou
 * no último turno (denormalizada por turno). Isso elimina a "mentira visual" em que o card
 * lia o pin estático `agent_profile_id` (escolha do broadcast) e mostrava outbound enquanto
 * o backend executava inbound. Fallback (só quando ainda não houve resposta da IA, agent_persona
 * NULL): o pin da conversa → agent_profile default do canal.
 *
 * Só renderiza quando a IA é a responsável: canal em modo "human" ou lead com
 * ai_enabled === false significam atendimento humano — nesse caso retorna null
 * (o card "mantém como está", sem tag de persona).
 */
export function getAgentPersona(
  conv: Conversation,
): { label: string; direction: "inbound" | "outbound"; color: string } | null {
  const aiResponsible =
    conv.channels?.mode !== "human" && (conv.leads?.ai_enabled ?? true) !== false;
  if (!aiResponsible) return null;

  // Persona efetiva (backend) tem prioridade; pin estático é só fallback pré-1ª-resposta.
  const promptKey =
    conv.agent_persona ??
    conv.agent_profiles?.prompt_key ??
    conv.channels?.agent_profiles?.prompt_key;
  if (!promptKey) return null;

  const name =
    conv.agent_profiles?.name ?? conv.channels?.agent_profiles?.name ?? "Valéria";
  const direction = promptKey.endsWith("outbound") ? "outbound" : "inbound";
  return direction === "outbound"
    ? { label: `${name} (Outbound)`, direction, color: "#b45309" }
    : { label: `${name} (Inbound)`, direction, color: "#5b8aad" };
}
