import { describe, expect, it } from "vitest";
import type { Message } from "@/lib/types";
import {
  collectUnresolvedWamids,
  enrichWithQuotedMessages,
} from "./messages-window";

function msg(id: string, at: string, extra: Partial<Message> = {}): Message {
  return { id, created_at: at, content: id, role: "user", ...extra } as Message;
}

function reactionMsg(id: string, at: string, targetWamid: string | null, emoji = "👍"): Message {
  return msg(id, at, {
    message_type: "reaction",
    content: emoji,
    metadata: { emoji, target_wamid: targetWamid ?? undefined },
  });
}

describe("enrichWithQuotedMessages — reações", () => {
  it("popula reaction_target e anexa badge quando o alvo está na janela", () => {
    const target = msg("t1", "2026-07-11T10:00:00Z", {
      wamid: "w-target",
      role: "assistant",
      content: "te enviei o catálogo",
    });
    const reaction = reactionMsg("r1", "2026-07-11T10:05:00Z", "w-target");
    const out = enrichWithQuotedMessages([target, reaction]);

    const r = out.find((m) => m.id === "r1")!;
    expect(r.reaction_target).toEqual({
      id: "t1",
      content: "te enviei o catálogo",
      role: "assistant",
      message_type: null,
    });
    expect(r.reaction_attached).toBe(true);

    const t = out.find((m) => m.id === "t1")!;
    expect(t.reactions).toEqual([{ emoji: "👍", role: "user" }]);
  });

  it("alvo ausente: reaction_target null, sem badge, wamid vai para os não resolvidos", () => {
    const reaction = reactionMsg("r2", "2026-07-11T10:05:00Z", "w-gone", "❤️");
    const out = enrichWithQuotedMessages([reaction]);

    const r = out.find((m) => m.id === "r2")!;
    expect(r.reaction_target).toBeNull();
    expect(r.reaction_attached).toBe(false);
    expect(collectUnresolvedWamids(out)).toEqual(["w-gone"]);
  });

  it("alvo resolvido via lookup (fora da janela): reaction_target populado, sem badge", () => {
    const reaction = reactionMsg("r3", "2026-07-11T10:05:00Z", "w-old");
    const lookupRow = msg("old1", "2026-07-01T08:00:00Z", {
      wamid: "w-old",
      role: "assistant",
      content: "foto do classico",
      message_type: "image",
    });
    const out = enrichWithQuotedMessages([reaction], [lookupRow]);

    const r = out.find((m) => m.id === "r3")!;
    expect(r.reaction_target).toEqual({
      id: "old1",
      content: "foto do classico",
      role: "assistant",
      message_type: "image",
    });
    // Alvo não está renderizado na janela → mantém bolha própria, sem badge.
    expect(r.reaction_attached).toBe(false);
    // Lookup não vaza para a thread renderizada.
    expect(out.map((m) => m.id)).toEqual(["r3"]);
    expect(collectUnresolvedWamids(out)).toEqual([]);
  });

  it("reação sem metadata não quebra", () => {
    const reaction = msg("r4", "2026-07-11T10:05:00Z", { message_type: "reaction" });
    const out = enrichWithQuotedMessages([reaction]);
    expect(out[0].reaction_target).toBeNull();
    expect(collectUnresolvedWamids(out)).toEqual([]);
  });
});

describe("enrichWithQuotedMessages — reply via lookup", () => {
  it("resolve quoted_message com linha do lookup quando fora da janela", () => {
    const reply = msg("rep1", "2026-07-11T10:00:00Z", { quoted_wamid: "w-far" });
    const before = enrichWithQuotedMessages([reply]);
    expect(before[0].quoted_message).toBeNull();
    expect(collectUnresolvedWamids(before)).toEqual(["w-far"]);

    const lookupRow = msg("far1", "2026-06-01T08:00:00Z", {
      wamid: "w-far",
      role: "assistant",
      content: "",
      message_type: "image",
    });
    const after = enrichWithQuotedMessages([reply], [lookupRow]);
    expect(after[0].quoted_message).toEqual({
      id: "far1",
      content: "",
      role: "assistant",
      message_type: "image",
    });
    expect(collectUnresolvedWamids(after)).toEqual([]);
  });

  it("é idempotente: re-enriquecer a saída dá o mesmo resultado", () => {
    const target = msg("t1", "2026-07-11T10:00:00Z", { wamid: "w-1" });
    const reaction = reactionMsg("r1", "2026-07-11T10:05:00Z", "w-1");
    const reply = msg("rep", "2026-07-11T10:06:00Z", { quoted_wamid: "w-1" });
    const once = enrichWithQuotedMessages([target, reaction, reply]);
    const twice = enrichWithQuotedMessages(once);
    expect(twice).toEqual(once);
  });

  it("deduplica wamids não resolvidos", () => {
    const a = msg("a", "2026-07-11T10:00:00Z", { quoted_wamid: "w-x" });
    const b = msg("b", "2026-07-11T10:01:00Z", { quoted_wamid: "w-x" });
    const out = enrichWithQuotedMessages([a, b]);
    expect(collectUnresolvedWamids(out)).toEqual(["w-x"]);
  });
});
