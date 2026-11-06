import { describe, expect, it } from "vitest";
import { resolveSendTarget, LEAD_SEND_FIELDS } from "./send-target";

const carolaine = {
  phone: "5537932140027",
  wa_id: "553732140027",
  wa_id_confirmed_at: "2026-09-23T14:29:31Z",
  last_customer_message_at: null,
  bsuid: null,
};

describe("resolveSendTarget", () => {
  it("prefere o wa_id real (número fixo sem o 9) ao phone normalizado", () => {
    expect(resolveSendTarget(carolaine)).toBe("553732140027");
  });
  it("sem wa_id usa o phone", () => {
    expect(resolveSendTarget({ ...carolaine, wa_id: null })).toBe("5537932140027");
  });
  it("sem wa_id e sem phone usa o bsuid", () => {
    expect(resolveSendTarget({ phone: null, wa_id: null, bsuid: "BR.123" })).toBe("BR.123");
  });
  it("caminho frio: wa_id sem procedência é ignorado", () => {
    const semProc = { ...carolaine, wa_id_confirmed_at: null, last_customer_message_at: null };
    expect(resolveSendTarget(semProc, { requireInboundProvenance: true })).toBe("5537932140027");
  });
  it("caminho frio: wa_id com procedência é usado", () => {
    expect(resolveSendTarget(carolaine, { requireInboundProvenance: true })).toBe("553732140027");
    const viaInbound = { ...carolaine, wa_id_confirmed_at: null, last_customer_message_at: "2026-11-06T17:58:12Z" };
    expect(resolveSendTarget(viaInbound, { requireInboundProvenance: true })).toBe("553732140027");
  });
  it("lead nulo devolve string vazia", () => {
    expect(resolveSendTarget(null)).toBe("");
  });
  it("LEAD_SEND_FIELDS traz as colunas que o helper lê", () => {
    for (const c of ["phone", "wa_id", "wa_id_confirmed_at", "last_customer_message_at", "bsuid"]) {
      expect(LEAD_SEND_FIELDS).toContain(c);
    }
  });
});
