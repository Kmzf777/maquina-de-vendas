import { describe, it, expect } from "vitest";
import {
  mergeConversationRow,
  sortByLastMsgDesc,
  previewFromMessage,
} from "./conversations-live";
import type { Conversation, Lead } from "./types";

function conv(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "conv-1",
    lead_id: "lead-1",
    channel_id: "ch-1",
    stage: "novo",
    status: "open",
    last_msg_at: "2026-07-03T10:00:00+00:00",
    created_at: "2026-07-01T10:00:00+00:00",
    agent_profile_id: null,
    last_message_text: "IA: olá",
    unread_count: 2,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    deal_pipeline_name: "Funil",
    deal_stage_label: "Novo",
    deal_stage_dot_color: "#fff",
    first_seller_response_at: null,
    last_seller_response_at: null,
    leads: { id: "lead-1", name: "Maria", phone: "5534999999999" } as Lead,
    channels: { id: "ch-1", name: "Canal", phone: "x", provider: "meta_cloud", agent_profile_id: null },
    agent_profiles: { id: "ap-1", name: "Valéria" },
    last_message_direction: "outbound",
    ...overrides,
  };
}

describe("mergeConversationRow", () => {
  it("aplica colunas escalares do payload e PRESERVA joins e campos computados", () => {
    const existing = conv();
    const merged = mergeConversationRow(existing, {
      id: "conv-1",
      last_msg_at: "2026-07-03T12:00:00+00:00",
      unread_count: 5,
      agent_persona: "valeria_outbound",
    });

    expect(merged.last_msg_at).toBe("2026-07-03T12:00:00+00:00");
    expect(merged.unread_count).toBe(5);
    expect(merged.agent_persona).toBe("valeria_outbound");
    // O payload cru não carrega joins/computados — um spread ingênuo os apagaria.
    expect(merged.leads).toBe(existing.leads);
    expect(merged.channels).toBe(existing.channels);
    expect(merged.agent_profiles).toBe(existing.agent_profiles);
    expect(merged.last_message_text).toBe("IA: olá");
    expect(merged.last_message_direction).toBe("outbound");
    expect(merged.deal_pipeline_name).toBe("Funil");
  });

  it("forceUnreadZero vence o unread_count do payload (mark-read otimista)", () => {
    const merged = mergeConversationRow(conv(), { id: "conv-1", unread_count: 7 }, { forceUnreadZero: true });
    expect(merged.unread_count).toBe(0);
  });

  it("pendingFollowup vence o followup_enabled do payload (toggle em voo)", () => {
    const merged = mergeConversationRow(
      conv(),
      { id: "conv-1", followup_enabled: true },
      { pendingFollowup: false },
    );
    expect(merged.followup_enabled).toBe(false);
  });
});

describe("sortByLastMsgDesc", () => {
  it("ordena por last_msg_at desc com nulls por último (paridade com a API)", () => {
    const a = conv({ id: "a", last_msg_at: "2026-07-03T10:00:00+00:00" });
    const b = conv({ id: "b", last_msg_at: "2026-07-03T12:00:00+00:00" });
    const c = conv({ id: "c", last_msg_at: null });
    expect(sortByLastMsgDesc([a, c, b]).map((x) => x.id)).toEqual(["b", "a", "c"]);
  });

  it("não muta a lista original", () => {
    const list = [conv({ id: "a" }), conv({ id: "b", last_msg_at: "2026-07-04T00:00:00+00:00" })];
    sortByLastMsgDesc(list);
    expect(list[0].id).toBe("a");
  });
});

describe("previewFromMessage", () => {
  // Paridade com a montagem server-side do /api/conversations (prefixos + direção).
  it("lead (role=user) → sem prefixo, inbound", () => {
    expect(previewFromMessage({ role: "user", sent_by: "user", content: "oi" })).toEqual({
      text: "oi",
      direction: "inbound",
    });
  });

  it("vendedor → prefixo 'Vendedor: ', outbound", () => {
    expect(previewFromMessage({ role: "assistant", sent_by: "seller", content: "bom dia" })).toEqual({
      text: "Vendedor: bom dia",
      direction: "outbound",
    });
  });

  it("disparos (broadcast/campaign/automation/followup/cadence) → 'Disparo: '", () => {
    for (const sentBy of ["broadcast", "campaign", "automation", "followup", "cadence"]) {
      expect(previewFromMessage({ role: "assistant", sent_by: sentBy, content: "msg" }).text).toBe("Disparo: msg");
    }
  });

  it("IA (role=assistant, sent_by=agent) → 'IA: ', outbound", () => {
    expect(previewFromMessage({ role: "assistant", sent_by: "agent", content: "posso ajudar?" })).toEqual({
      text: "IA: posso ajudar?",
      direction: "outbound",
    });
  });

  it("content nulo (mídia) não vira 'null' no preview", () => {
    expect(previewFromMessage({ role: "user", sent_by: "user", content: null }).text).toBe("");
  });
});
