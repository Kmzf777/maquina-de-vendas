import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  agentModeOptions,
  agentSelectionError,
  isButtonFlowProfile,
  reconcileAgentSelection,
  selectableAgentProfiles,
  type AgentProfileOption,
} from "@/lib/agent-profile-choices";

const valeria: AgentProfileOption = { id: "b9930820", name: "ValerIA - Outbound", kind: "llm" };
const inbound: AgentProfileOption = { id: "674beb13", name: "Agente Canastra", kind: "llm" };
const botao: AgentProfileOption = { id: "bot-1", name: "Bot Reativação", kind: "button_flow" };
const legado: AgentProfileOption = { id: "legado-1", name: "Perfil sem kind" };

const todos = [valeria, inbound, botao, legado];

describe("selectableAgentProfiles", () => {
  it("canal humano oferece SÓ fluxo de botões", () => {
    expect(selectableAgentProfiles(todos, "human")).toEqual([botao]);
  });

  it("canal de IA continua oferecendo todos", () => {
    expect(selectableAgentProfiles(todos, "ai")).toEqual(todos);
  });

  it("canal sem mode definido é tratado como IA (comportamento de hoje)", () => {
    expect(selectableAgentProfiles(todos, undefined)).toEqual(todos);
  });

  it("perfil sem kind (banco pré-migration 20260820) nunca passa por fluxo de botões", () => {
    expect(isButtonFlowProfile(legado)).toBe(false);
    expect(selectableAgentProfiles([legado], "human")).toEqual([]);
  });
});

describe("agentModeOptions", () => {
  it("canal humano não oferece 'padrão do canal' — o default do João é a ValerIA LLM", () => {
    expect(agentModeOptions("human").map((o) => o.value)).toEqual(["none", "specific"]);
  });

  it("canal de IA mantém os três modos", () => {
    expect(agentModeOptions("ai").map((o) => o.value)).toEqual([
      "none",
      "channel_default",
      "specific",
    ]);
  });
});

describe("reconcileAgentSelection", () => {
  it("trocar para canal humano derruba 'padrão do canal'", () => {
    expect(
      reconcileAgentSelection({ mode: "channel_default", profileId: "" }, todos, "human")
    ).toEqual({ mode: "none", profileId: "" });
  });

  it("trocar para canal humano derruba um perfil LLM já escolhido", () => {
    // O handleCreate grava agent_profile_id sem reconferir o canal: um id de ValerIA
    // pendurado fixaria IA generativa no número do vendedor.
    expect(
      reconcileAgentSelection({ mode: "specific", profileId: valeria.id }, todos, "human")
    ).toEqual({ mode: "specific", profileId: "" });
  });

  it("perfil de fluxo de botões sobrevive ao canal humano", () => {
    expect(
      reconcileAgentSelection({ mode: "specific", profileId: botao.id }, todos, "human")
    ).toEqual({ mode: "specific", profileId: botao.id });
  });

  it("id que não está mais na lista é descartado", () => {
    expect(
      reconcileAgentSelection({ mode: "specific", profileId: "fantasma" }, todos, "human")
    ).toEqual({ mode: "specific", profileId: "" });
  });

  it("canal de IA não mexe em nada", () => {
    const selecao = { mode: "specific" as const, profileId: valeria.id };
    expect(reconcileAgentSelection(selecao, todos, "ai")).toEqual(selecao);
  });
});

describe("agentSelectionError", () => {
  it("REPRO: canal humano, 'escolher agente de fluxo de botões' e nada escolhido não passa", () => {
    // Beco do caminho novo: o operador marca o modo, o reconcile zera o profileId e o
    // wizard deixava avançar — handleCreate gravava agent_profile_id: null e nascia uma
    // campanha de botões sem ninguém para responder aos cliques.
    expect(
      agentSelectionError({ mode: "specific", profileId: "" }, todos, "human")
    ).toBe("Selecione o agente de fluxo de botões que vai responder aos cliques.");
  });

  it("REPRO: nenhum perfil button_flow cadastrado — empty-state vermelho não pode disparar", () => {
    expect(
      agentSelectionError({ mode: "specific", profileId: "" }, [valeria, inbound], "human")
    ).toBe('Nenhum agente de fluxo de botões cadastrado. Escolha "Sem agente" para continuar.');
  });

  it("id de ValerIA sobrevivente à troca de canal não conta como escolhido em canal humano", () => {
    expect(
      agentSelectionError({ mode: "specific", profileId: valeria.id }, todos, "human")
    ).toBe("Selecione o agente de fluxo de botões que vai responder aos cliques.");
  });

  it("perfil de fluxo de botões escolhido libera o avanço", () => {
    expect(
      agentSelectionError({ mode: "specific", profileId: botao.id }, todos, "human")
    ).toBeNull();
  });

  it("canal de IA: 'específico' sem escolha também não passa", () => {
    expect(agentSelectionError({ mode: "specific", profileId: "" }, todos, "ai")).toBe(
      "Selecione um agente para continuar."
    );
  });

  it("canal de IA: perfil qualquer da lista libera", () => {
    expect(
      agentSelectionError({ mode: "specific", profileId: valeria.id }, todos, "ai")
    ).toBeNull();
  });

  it("'sem agente' e 'padrão do canal' nunca travam o wizard", () => {
    expect(agentSelectionError({ mode: "none", profileId: "" }, [], "human")).toBeNull();
    expect(
      agentSelectionError({ mode: "channel_default", profileId: "" }, [], "ai")
    ).toBeNull();
  });
});

// vitest roda com cwd = frontend/ (mesma premissa de src/lib/auth/proxy-coverage.test.ts).
const MODAL = path.resolve(
  process.cwd(),
  "src/components/campaigns/create-broadcast-modal.tsx"
);

describe("wizard de disparo: a trava chega até o botão", () => {
  const fonte = fs.readFileSync(MODAL, "utf8");

  it("canGoToStep2 depende do erro de agente, não só de nome + canal", () => {
    // Sem isto o "Próximo" do passo 1 fica habilitado com agentMode='specific' e
    // specificAgentId='' — o beco exato que a revisão de 09/09/2026 reproduziu.
    const linha = fonte.match(/const canGoToStep2 = [\s\S]*?;/)?.[0] ?? "";
    expect(linha).toContain("agentError === null");
  });

  it("handleCreate tem backstop próprio — preflight.py:308 é fail-open com id nulo", () => {
    expect(fonte).toContain("if (agentError)");
  });
});
