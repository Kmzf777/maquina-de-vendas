import { describe, it, expect } from "vitest";
import {
  mapKpis,
  mapConversion,
  mapOutbound,
  mapFollowups,
} from "@/lib/dashboard-mappers";

describe("mapKpis", () => {
  it("mapeia linha da RPC com numerics como string (PostgREST)", () => {
    const r = mapKpis({
      leads_new: "17", leads_prev: "29",
      active_with_ai: 13, active_awaiting_lead: 13,
      conversations_attended: "73", handoffs: 43,
      qualification_rate: "0.0137",
      sla_median_minutes: "38.5", sla_p95_minutes: "190.2", sla_samples: 12,
      cost_per_handoff_usd: "0.1531", cost_per_atendimento_usd: "0.0682",
    });
    expect(r.leads_new).toBe(17);
    expect(r.leads_trend_pct).toBe(-41.4); // (17-29)/29 = -41,4%
    expect(r.qualification_rate).toBe(0.0137);
    expect(r.sla_median_minutes).toBe(38.5);
    expect(r.cost_per_handoff_usd).toBe(0.1531);
  });

  it("período anterior vazio -> tendência null (não Infinity/NaN)", () => {
    const r = mapKpis({
      leads_new: 5, leads_prev: 0,
      active_with_ai: 0, active_awaiting_lead: 0,
      conversations_attended: 0, handoffs: 0, qualification_rate: 0,
      sla_median_minutes: null, sla_p95_minutes: null, sla_samples: 0,
      cost_per_handoff_usd: null, cost_per_atendimento_usd: null,
    });
    expect(r.leads_trend_pct).toBeNull();
    expect(r.sla_median_minutes).toBeNull();
    expect(r.cost_per_handoff_usd).toBeNull();
  });

  it("linha ausente -> zeros/nulls (não 500)", () => {
    const r = mapKpis(undefined);
    expect(r.leads_new).toBe(0);
    expect(r.sla_samples).toBe(0);
    expect(r.sla_median_minutes).toBeNull();
  });
});

describe("mapConversion", () => {
  it("calcula taxas da coorte (validado contra prod 30d: 590/85/3)", () => {
    const r = mapConversion({ leads_total: "590", with_handoff: "85", won: "3" });
    expect(r.handoff_rate).toBe(0.1441);
    expect(r.win_rate).toBe(0.0051);
  });

  it("coorte vazia -> taxas 0", () => {
    const r = mapConversion({ leads_total: 0, with_handoff: 0, won: 0 });
    expect(r.handoff_rate).toBe(0);
    expect(r.win_rate).toBe(0);
  });
});

describe("mapOutbound", () => {
  it("funil do disparo frio (validado contra prod 30d: 1129/916/196)", () => {
    const r = mapOutbound({ sent: "1129", delivered: "916", replied: "196" });
    expect(r.delivery_rate).toBe(0.8113);
    expect(r.reply_rate).toBe(0.1736);
  });

  it("sem disparos -> taxas 0", () => {
    expect(mapOutbound(undefined).delivery_rate).toBe(0);
  });
});

describe("mapFollowups", () => {
  it("mapeia jsonb by_type e retorno pendente", () => {
    const r = mapFollowups({
      scheduled_today: "9", sent_today: "3", overdue_pending: 0,
      by_type: [{ job_type: "lp_welcome", scheduled: "9", sent: "3" }],
      returns_pending: 2, next_return_at: "2026-07-13T12:00:00+00:00",
    });
    expect(r.by_type).toEqual([{ job_type: "lp_welcome", scheduled: 9, sent: 3 }]);
    expect(r.returns_pending).toBe(2);
    expect(r.next_return_at).toBe("2026-07-13T12:00:00+00:00");
  });

  it("by_type não-array (defensivo) -> lista vazia", () => {
    const r = mapFollowups({
      scheduled_today: 0, sent_today: 0, overdue_pending: 0,
      by_type: null, returns_pending: 0, next_return_at: null,
    });
    expect(r.by_type).toEqual([]);
    expect(r.next_return_at).toBeNull();
  });
});
