import { describe, it, expect, vi } from "vitest";
import {
  getActiveConversation, setActiveConversation, subscribeActiveConversation,
} from "./active-conversation";

describe("active-conversation store", () => {
  it("começa vazio", () => {
    expect(getActiveConversation()).toEqual({ conversationId: null, leadId: null });
  });

  it("set notifica os inscritos e o get devolve o valor novo", () => {
    const cb = vi.fn();
    const unsub = subscribeActiveConversation(cb);
    setActiveConversation({ conversationId: "c1", leadId: "l1" });
    expect(cb).toHaveBeenCalledTimes(1);
    expect(getActiveConversation()).toEqual({ conversationId: "c1", leadId: "l1" });
    unsub();
    setActiveConversation({ conversationId: null, leadId: null });
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("set com o mesmo valor não notifica (snapshot estável)", () => {
    setActiveConversation({ conversationId: "c9", leadId: "l9" });
    const snap = getActiveConversation();
    const cb = vi.fn();
    const unsub = subscribeActiveConversation(cb);
    setActiveConversation({ conversationId: "c9", leadId: "l9" });
    expect(cb).not.toHaveBeenCalled();
    expect(getActiveConversation()).toBe(snap);
    unsub();
  });
});
