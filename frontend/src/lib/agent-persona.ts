import type { Conversation } from "@/lib/types";

/**
 * Direção Inbound/Outbound da Valéria no card — resiliente, nunca-nula em contexto Valéria.
 *
 * Cascata de fontes (D2): persona efetiva (`agent_persona`, denormalizada por turno pelo
 * backend) → pin da conversa (`agent_profiles.prompt_key`) → default do canal
 * (`channels.agent_profiles.prompt_key`) → direção da última mensagem
 * (`last_message_direction`) → default `inbound`. Isso elimina o card mudo em conversas
 * outbound recém-disparadas (persona ainda NULL, sem pin/canal).
 *
 * Handoff (`ai_enabled === false`): a IA apenas DESLIGA — o card CONTINUA sendo da Valéria
 * e mantém a persona (Inbound/Outbound). NÃO vira "Humano": o atendimento humano acontece
 * em outro número/canal, gerando um card separado.
 *
 * Canal humano (`channels.mode === "human"`, ex.: número do João): esse card é do vendedor,
 * não da Valéria — retorna `null` (sem badge de persona).
 */
type PersonaState = {
  label: string;
  direction: "inbound" | "outbound";
  color: string;
};

export function getAgentPersona(conv: Conversation): PersonaState | null {
  // Card de canal humano não é atendimento da Valéria — sem badge de persona.
  if (conv.channels?.mode === "human") return null;

  const promptKey =
    conv.agent_persona ??
    conv.agent_profiles?.prompt_key ??
    conv.channels?.agent_profiles?.prompt_key;

  const name =
    conv.agent_profiles?.name ?? conv.channels?.agent_profiles?.name ?? "Valéria";

  let direction: "inbound" | "outbound";
  if (promptKey) {
    direction = promptKey.endsWith("outbound") ? "outbound" : "inbound";
  } else if (conv.last_message_direction) {
    direction = conv.last_message_direction;
  } else {
    direction = "inbound"; // default documentado — garante que nenhum card da Valéria fique mudo
  }

  return direction === "outbound"
    ? { label: `${name} (Outbound)`, direction, color: "#b45309" }
    : { label: `${name} (Inbound)`, direction, color: "#5b8aad" };
}
