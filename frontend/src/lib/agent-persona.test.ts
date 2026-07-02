import { describe, it, expect } from "vitest";
import { getAgentPersona } from "@/lib/agent-persona";
import type { Conversation } from "@/lib/types";

function makeConv(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "conv-1",
    lead_id: "lead-1",
    channel_id: "ch-1",
    stage: "atacado",
    status: "open",
    last_msg_at: null,
    created_at: "2026-01-01T00:00:00Z",
    agent_profile_id: null,
    last_message_text: null,
    unread_count: 0,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: false,
    first_seller_response_at: null,
    last_seller_response_at: null,
    ...overrides,
  };
}

const aiChannel = {
  id: "ch-1",
  name: "Numero Valeria",
  phone: "5511999990001",
  provider: "meta_cloud",
  agent_profile_id: null,
  mode: "ai" as const,
};

describe("getAgentPersona", () => {
  it("outbound persona → outbound label and amber color", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: aiChannel,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("outbound");
    expect(result!.label).toBe("Valéria (Outbound)");
    expect(result!.color).toBe("#b45309");
  });

  it("inbound persona → inbound label and blue color", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_inbound",
        channels: aiChannel,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("inbound");
    expect(result!.label).toBe("Valéria (Inbound)");
    expect(result!.color).toBe("#5b8aad");
  });

  it("ai_enabled === false (handoff) → mantém persona da Valéria, não vira Humano", () => {
    // Handoff apenas DESLIGA a IA; o card segue sendo da Valéria e mantém a persona.
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: aiChannel,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: false } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("outbound");
    expect(result!.label).toBe("Valéria (Outbound)");
  });

  it("handoff (ai_enabled=false) sem persona/pin/canal → fallback pela última mensagem", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel,
        last_message_direction: "inbound",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: false } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("inbound");
    expect(result!.label).toBe("Valéria (Inbound)");
  });

  it("null quando o canal é humano (card do vendedor, ex.: João — não é card da Valéria)", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: { ...aiChannel, mode: "human" },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).toBeNull();
  });

  it("fallback to channel agent_profiles.prompt_key when agent_persona is null", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: {
          ...aiChannel,
          agent_profile_id: "ap-1",
          agent_profiles: { id: "ap-1", name: "Valéria", prompt_key: "valeria_outbound" },
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("outbound");
    expect(result!.label).toBe("Valéria (Outbound)");
  });

  it("fallback: sem persona/pin/canal, usa last_message_direction outbound", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel, // sem agent_profiles default
        last_message_direction: "outbound",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result!.direction).toBe("outbound");
    expect(result!.label).toBe("Valéria (Outbound)");
  });

  it("fallback: last_message_direction inbound", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel,
        last_message_direction: "inbound",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result!.direction).toBe("inbound");
  });

  it("default inbound quando não há nenhuma fonte (nunca card mudo)", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel,
        last_message_direction: null,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("inbound");
  });

  it("persona tem prioridade sobre last_message_direction", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: aiChannel,
        last_message_direction: "inbound", // deve ser ignorado
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result!.direction).toBe("outbound");
  });
});
