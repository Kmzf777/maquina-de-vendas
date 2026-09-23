import { describe, expect, it } from "vitest";
import { describeLeadOrigin, resolveGoogleCampaignName, type LeadOriginInput } from "./lead-origin";

const base: LeadOriginInput = {
  traffic_type: null, utm_source: null, utm_medium: null, utm_campaign: null,
  gclid: null, fbclid: null, ctwa_clid: null, meta_ad_id: null, channel: null, metadata: null,
};
const lead = (p: Partial<LeadOriginInput>): LeadOriginInput => ({ ...base, ...p });

describe("describeLeadOrigin", () => {
  it("gclid → Google Ads com campanha resolvida", () => {
    expect(describeLeadOrigin(lead({ gclid: "abc", utm_campaign: "atacado" }), "Search | Atacado"))
      .toEqual({ kind: "pago", channel: "Google Ads", detail: "Search | Atacado", page: null });
  });
  it("google + cpc sem gclid → Google Ads, cai no utm_campaign", () => {
    expect(describeLeadOrigin(lead({ utm_source: "google", utm_medium: "cpc", utm_campaign: "marca" }), null))
      .toMatchObject({ kind: "pago", channel: "Google Ads", detail: "marca" });
  });
  it("google orgânico (sem meio pago) não é Google Ads", () => {
    expect(describeLeadOrigin(lead({ utm_source: "google", utm_medium: "organic" }), null))
      .toMatchObject({ kind: "organico", channel: "Google" });
  });
  it("meta_ad_id → Meta Ads com nome da campanha", () => {
    expect(describeLeadOrigin(lead({ meta_ad_id: "123", channel: "whatsapp" }), "CTWA Atacado Set"))
      .toEqual({ kind: "pago", channel: "Meta Ads", detail: "CTWA Atacado Set", page: null });
  });
  it("Meta sem campanha resolvida → Campanha não identificada", () => {
    expect(describeLeadOrigin(lead({ ctwa_clid: "x" }), null).detail).toBe("Campanha não identificada");
  });
  it("utm_source metaads → Meta Ads", () => {
    expect(describeLeadOrigin(lead({ utm_source: "metaads", utm_campaign: "lp-atacado" }), null))
      .toMatchObject({ kind: "pago", channel: "Meta Ads", detail: "lp-atacado" });
  });
  it("gclid vence meta_ad_id", () => {
    expect(describeLeadOrigin(lead({ gclid: "g", meta_ad_id: "m" }), null).channel).toBe("Google Ads");
  });
  it("meta_ad_id vence utm google+cpc sem gclid (como derive_channel)", () => {
    expect(describeLeadOrigin(lead({ meta_ad_id: "m", utm_source: "google", utm_medium: "cpc" }), null).channel)
      .toBe("Meta Ads");
  });
  it("traffic_type paid genérico → canal pela utm_source", () => {
    expect(describeLeadOrigin(lead({ traffic_type: "paid", utm_source: "tiktok", utm_medium: "cpc" }), null))
      .toMatchObject({ kind: "pago", channel: "Tiktok", detail: "Campanha não identificada" });
  });
  it("lead pago que passou por LP leva page", () => {
    expect(describeLeadOrigin(lead({ fbclid: "f", metadata: { origem: "graocafeteria" } }), "Cafeterias").page)
      .toBe("Grão Cafeteria");
  });
  it("indicação vence LP", () => {
    expect(describeLeadOrigin(lead({ metadata: { origem: "atacado", referral: { nome: "Maria" } } }), null))
      .toEqual({ kind: "organico", channel: "Indicação", detail: "de Maria", page: null });
  });
  it("reativação Bling com lote", () => {
    expect(describeLeadOrigin(lead({ channel: "bling", metadata: { origem: "reativacao_bling", lote: 3 } }), null))
      .toEqual({ kind: "importado", channel: "Reativação Bling", detail: "Lote 3", page: null });
  });
  it("Bling webhook", () => {
    expect(describeLeadOrigin(lead({ channel: "bling", metadata: { origem: "bling_webhook" } }), null))
      .toEqual({ kind: "importado", channel: "Bling", detail: null, page: null });
  });
  it("instagram orgânico (bio)", () => {
    expect(describeLeadOrigin(lead({ traffic_type: "organic", utm_source: "instagram", utm_medium: "bio" }), null))
      .toEqual({ kind: "organico", channel: "Instagram", detail: "bio", page: null });
  });
  it("instagram orgânico via LP leva page", () => {
    expect(describeLeadOrigin(lead({ utm_source: "facebook", metadata: { origem: "atacado" } }), null))
      .toMatchObject({ channel: "Facebook", page: "Atacado" });
  });
  it("LP sem utm → Landing page com label", () => {
    expect(describeLeadOrigin(lead({ channel: "whatsapp", metadata: { origem: "terceirizacao" } }), null))
      .toEqual({ kind: "organico", channel: "Landing page", detail: "Terceirização", page: null });
  });
  it("LP desconhecida usa o próprio valor", () => {
    expect(describeLeadOrigin(lead({ metadata: { origem: "nova-lp" } }), null).detail).toBe("nova-lp");
  });
  it("manual", () => {
    expect(describeLeadOrigin(lead({ channel: "manual" }), null))
      .toEqual({ kind: "importado", channel: "Cadastro manual", detail: null, page: null });
  });
  it("campaign", () => {
    expect(describeLeadOrigin(lead({ channel: "campaign" }), null).channel).toBe("Importação de campanha");
  });
  it("whatsapp sem sinal → WhatsApp direto", () => {
    expect(describeLeadOrigin(lead({ channel: "whatsapp" }), null))
      .toEqual({ kind: "organico", channel: "WhatsApp direto", detail: null, page: null });
  });
  it("nada → Sem rastreio", () => {
    expect(describeLeadOrigin(base, null))
      .toEqual({ kind: "sem_rastreio", channel: "Sem rastreio", detail: null, page: null });
  });
});

describe("resolveGoogleCampaignName", () => {
  const names = ["Search | Atacado", "PMAX | Atacado", "Search | Marca Própria"];
  it("nome idêntico normalizado", () => {
    expect(resolveGoogleCampaignName("search | atacado", null, names)).toBe("Search | Atacado");
  });
  it("candidato único por tokens", () => {
    expect(resolveGoogleCampaignName("marca_propria", null, names)).toBe("Search | Marca Própria");
  });
  it("empate desfeito por utm_medium", () => {
    expect(resolveGoogleCampaignName("atacado", "pmax", names)).toBe("PMAX | Atacado");
  });
  it("empate sem desempate → null", () => {
    expect(resolveGoogleCampaignName("atacado", null, names)).toBeNull();
  });
  it("vazio → null", () => {
    expect(resolveGoogleCampaignName(null, null, names)).toBeNull();
    expect(resolveGoogleCampaignName("atacado", null, [])).toBeNull();
  });
});
