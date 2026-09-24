import { describe, it, expect } from "vitest";
import { buildReminderQueue, formatWindowHour, SLA_REMINDER_MINUTES } from "./sla-reminder";

const none = { conversationId: null, leadId: null };
const lead = (conversationId: string, leadId: string, elapsedMinutes: number) => ({
  conversationId, leadId, elapsedMinutes,
});

describe("buildReminderQueue", () => {
  it("ordena pela maior espera primeiro", () => {
    const q = buildReminderQueue([lead("c1", "l1", 45), lead("c2", "l2", 90)], new Set(), none);
    expect(q.map((l) => l.conversationId)).toEqual(["c2", "c1"]);
  });

  it("ignora quem está em até 40 min", () => {
    const q = buildReminderQueue([lead("c1", "l1", SLA_REMINDER_MINUTES), lead("c2", "l2", 41)], new Set(), none);
    expect(q.map((l) => l.conversationId)).toEqual(["c2"]);
  });

  it("remove os dispensados nesta página", () => {
    const q = buildReminderQueue([lead("c1", "l1", 50), lead("c2", "l2", 60)], new Set(["c2"]), none);
    expect(q.map((l) => l.conversationId)).toEqual(["c1"]);
  });

  it("remove a conversa aberta, por conversa ou por lead", () => {
    const leads = [lead("c1", "l1", 50), lead("c2", "l2", 60), lead("c3", "l3", 70)];
    expect(buildReminderQueue(leads, new Set(), { conversationId: "c1", leadId: null }).map((l) => l.conversationId))
      .toEqual(["c3", "c2"]);
    expect(buildReminderQueue(leads, new Set(), { conversationId: null, leadId: "l3" }).map((l) => l.conversationId))
      .toEqual(["c2", "c1"]);
  });

  it("não muta a entrada", () => {
    const leads = [lead("c1", "l1", 45), lead("c2", "l2", 90)];
    buildReminderQueue(leads, new Set(), none);
    expect(leads.map((l) => l.conversationId)).toEqual(["c1", "c2"]);
  });
});

describe("formatWindowHour", () => {
  it("formata hora cheia e quebrada", () => {
    expect(formatWindowHour(600)).toBe("10h");
    expect(formatWindowHour(960)).toBe("16h");
    expect(formatWindowHour(630)).toBe("10h30");
    expect(formatWindowHour(545)).toBe("9h05");
  });
});
