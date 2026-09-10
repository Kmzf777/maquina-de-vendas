import type { AgentKind, AgentProfile } from "@/lib/types";

/**
 * Que agente pode ser escolhido num disparo, dado o `mode` do canal.
 *
 * O wizard escondia o bloco inteiro de agente quando o canal era `mode='human'`
 * (create-broadcast-modal.tsx:693, mais o reset em :263-266). Fazia sentido enquanto
 * "agente" só queria dizer ValerIA generativa: um canal humano é do vendedor, não da IA.
 * Deixou de fazer quando nasceu o agente de fluxo de botões — ele roda JUSTAMENTE no
 * número do João (`553491461669`, `mode='human'`), porque a troca de número no handoff
 * é o maior vazamento medido do funil (26% dos leads não migram).
 *
 * A regra nova, então, não é "esconder" nem "mostrar tudo": em canal humano só o que é
 * roteiro fechado — `kind='button_flow'`, todo texto declarado em
 * backend/app/button_flow/flows.py. E ali NÃO se oferece "agente padrão do canal": o
 * default do número do João é a ValerIA LLM (`valeria_inbound`), que nunca deve atender
 * no número do vendedor.
 */

/** Recorte que `GET /api/agent-profiles` devolve — o wizard nunca vê o perfil inteiro. */
export type AgentProfileOption = Pick<AgentProfile, "id" | "name"> & {
  kind?: AgentKind | string | null;
};

export type AgentMode = "none" | "channel_default" | "specific";

export type AgentSelection = {
  mode: AgentMode;
  profileId: string;
};

export function isButtonFlowProfile(profile: AgentProfileOption): boolean {
  return profile.kind === "button_flow";
}

/** Canal humano: só fluxo de botões. Canal de IA: tudo, como sempre foi. */
export function selectableAgentProfiles<T extends AgentProfileOption>(
  profiles: T[],
  channelMode: string | null | undefined
): T[] {
  if (channelMode !== "human") return profiles;
  return profiles.filter(isButtonFlowProfile);
}

/** Rótulos dos modos. Em canal humano "padrão do canal" some — apontaria para a ValerIA LLM. */
export function agentModeOptions(
  channelMode: string | null | undefined
): { value: AgentMode; label: string }[] {
  if (channelMode === "human") {
    return [
      { value: "none", label: "Sem agente" },
      { value: "specific", label: "Escolher agente de fluxo de botões" },
    ];
  }
  return [
    { value: "none", label: "Sem agente" },
    { value: "channel_default", label: "Agente padrão do canal" },
    { value: "specific", label: "Escolher agente específico" },
  ];
}

/**
 * Seleção que sobrevive à troca de canal.
 *
 * Trocar para um canal humano depois de já ter escolhido a ValerIA não pode deixar o id
 * antigo pendurado: o `handleCreate` grava `agent_profile_id` sem reconferir o canal, e o
 * disparo sairia fixando um agente generativo no número do vendedor. Só sobrevive um perfil
 * `button_flow` que ainda esteja na lista.
 */
export function reconcileAgentSelection(
  selection: AgentSelection,
  profiles: AgentProfileOption[],
  channelMode: string | null | undefined
): AgentSelection {
  if (channelMode !== "human") return selection;
  if (selection.mode !== "specific") return { mode: "none", profileId: "" };

  const escolhido = profiles.find((p) => p.id === selection.profileId);
  return {
    mode: "specific",
    profileId: escolhido && isButtonFlowProfile(escolhido) ? selection.profileId : "",
  };
}

/**
 * O que falta para a escolha de agente estar completa. `null` = pode avançar.
 *
 * Beco aberto pelo próprio caminho novo do canal humano (revisão de 09/09/2026):
 * `canGoToStep2` (create-broadcast-modal.tsx:558) só exigia nome + canal, e o
 * `handleCreate` (:482-496) resolvia `agentProfileId = specificAgentId = ""` e gravava
 * `agent_profile_id: null`. Enquanto o bloco de agente ficava ESCONDIDO em `mode='human'`
 * isso era inofensivo — "sem agente" era o único desfecho possível. Depois que o wizard
 * passou a OFERECER o agente de fluxo de botões, o operador podia marcar "Escolher agente
 * de fluxo de botões", ver o empty-state vermelho (ou nem abrir o select) e disparar assim
 * mesmo: campanha de botões que não responde a botão nenhum.
 *
 * E não existe rede no servidor: backend/app/templates/preflight.py:308 faz
 * `if not agent_profile_id: return None` — fail-open de propósito — então a checagem de
 * rótulos nunca roda com id nulo. A trava tem que ser aqui.
 */
export function agentSelectionError(
  selection: AgentSelection,
  profiles: AgentProfileOption[],
  channelMode: string | null | undefined
): string | null {
  if (selection.mode !== "specific") return null;

  const disponiveis = selectableAgentProfiles(profiles, channelMode);
  if (disponiveis.length === 0) {
    return channelMode === "human"
      ? 'Nenhum agente de fluxo de botões cadastrado. Escolha "Sem agente" para continuar.'
      : 'Nenhum agente cadastrado. Escolha "Sem agente" para continuar.';
  }

  // Vale o id que ainda está na lista OFERECIDA: um id de ValerIA sobrevivente à troca de
  // canal não pode passar por "escolhido" num canal humano.
  if (!disponiveis.some((p) => p.id === selection.profileId)) {
    return channelMode === "human"
      ? "Selecione o agente de fluxo de botões que vai responder aos cliques."
      : "Selecione um agente para continuar.";
  }

  return null;
}
