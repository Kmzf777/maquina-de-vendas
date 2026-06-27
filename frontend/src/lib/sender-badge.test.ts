import { describe, it, expect } from "vitest";
import { senderBadge } from "@/lib/sender-badge";

describe("senderBadge", () => {
  it("user → null", () => {
    expect(senderBadge({ role: "user", sent_by: "user" })).toBeNull();
  });
  it("agent → IA", () => {
    expect(senderBadge({ role: "assistant", sent_by: "agent" })).toBe("IA");
  });
  it("seller → Vendedor", () => {
    expect(senderBadge({ role: "assistant", sent_by: "seller" })).toBe("Vendedor");
  });
  it("followup → Cadência (distinct from IA)", () => {
    expect(senderBadge({ role: "assistant", sent_by: "followup" })).toBe("Cadência");
  });
  it("unknown sent_by → null", () => {
    expect(senderBadge({ role: "assistant", sent_by: "handoff_context" })).toBeNull();
  });
});
