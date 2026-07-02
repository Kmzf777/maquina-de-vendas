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
 * Handoff/canal humano (D1): não some — retorna estado neutro `human` ("Humano"),
 * comunicando explicitamente que a Valéria não é a responsável no momento.
 */
type PersonaState = {
  label: string;
  direction: "inbound" | "outbound" | "human";
  color: string;
};

const HUMAN_COLOR = "#7b7b78";

export function getAgentPersona(conv: Conversation): PersonaState | null {
  const isHumanChannel = conv.channels?.mode === "human";
  const aiDisabled = (conv.leads?.ai_enabled ?? true) === false;
  if (isHumanChannel || aiDisabled) {
    return { label: "Humano", direction: "human", color: HUMAN_COLOR };
  }

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
    direction = "inbound"; // default documentado — garante que nenhum card fique mudo
  }

  return direction === "outbound"
    ? { label: `${name} (Outbound)`, direction, color: "#b45309" }
    : { label: `${name} (Inbound)`, direction, color: "#5b8aad" };
}
