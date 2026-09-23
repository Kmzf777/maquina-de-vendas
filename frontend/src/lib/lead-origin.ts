import { LP_ORIGINS } from "@/lib/constants";

/**
 * Origem do lead para os painéis de /leads e /conversas.
 *
 * A detecção Google/Meta espelha `derive_channel` de
 * `backend/app/campaigns/traffic_report.py` (click-id > anúncio Meta > utm_source
 * de anúncio), para o que o vendedor vê no painel bater com o relatório do
 * /trafego nesses casos. A regra genérica de pago (`traffic_type='paid'`) segue
 * `derive_traffic_type`, não `derive_channel`: um lead instagram+paid_social
 * aparece aqui como "Pago · Instagram", mas o /trafego conta esse mesmo lead em
 * Orgânico (só Google/Meta contam como pago lá). Spec:
 * docs/superpowers/specs/2026-09-23-origem-do-lead-design.md
 */
export type LeadOriginKind = "pago" | "organico" | "importado" | "sem_rastreio";

export interface LeadOrigin {
  kind: LeadOriginKind;
  channel: string;
  detail: string | null;
  funnel: string | null;
}

export interface LeadOriginInput {
  traffic_type: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  gclid: string | null;
  fbclid: string | null;
  ctwa_clid: string | null;
  meta_ad_id: string | null;
  channel: string | null;
  metadata: Record<string, unknown> | null;
}

export const LEAD_ORIGIN_COLUMNS =
  "traffic_type, utm_source, utm_medium, utm_campaign, gclid, fbclid, ctwa_clid, meta_ad_id, channel, metadata";

// Mesmas listas do backend (traffic_report.py). 'instagram'/'facebook' crus são orgânico.
const META_AD_SOURCES = new Set(["metaads", "meta_ads", "meta-ads", "meta", "facebook_ads", "facebookads", "fb_ads"]);
const GOOGLE_AD_SOURCES = new Set(["google", "googleads", "google_ads", "adwords"]);
const PAID_MEDIUMS = new Set([
  "cpc", "ppc", "pmax", "performance_max", "paid", "paid_search", "paidsearch",
  "display", "cpm", "paid_social", "paidsocial",
]);
// metadata.origem que marca importação, não página de LP.
const IMPORT_ORIGINS = new Set(["reativacao_bling", "bling_webhook"]);
const UNRESOLVED = "Campanha não identificada";

const s = (v: unknown): string => (typeof v === "string" ? v.trim() : "");

function capitalize(v: string): string {
  return v ? v.charAt(0).toUpperCase() + v.slice(1) : v;
}

function lpLabel(origem: string): string {
  return LP_ORIGINS.find((o) => o.key === origem)?.label ?? origem;
}

function lpFunnel(metadata: Record<string, unknown> | null): string | null {
  const origem = s(metadata?.origem);
  return origem && !IMPORT_ORIGINS.has(origem) ? lpLabel(origem) : null;
}

/**
 * Plataforma paga do lead (Google/Meta), mesma ordem de `derive_channel`:
 * gclid > click-ids/anúncio Meta/utm_source Meta > utm_source+utm_medium Google.
 * `null` quando nenhum sinal específico de plataforma bate (pode ainda ser pago
 * genérico via `traffic_type`, tratado à parte em `describeLeadOrigin`).
 */
export function paidPlatform(lead: LeadOriginInput): "google" | "meta" | null {
  const source = s(lead.utm_source).toLowerCase();
  const medium = s(lead.utm_medium).toLowerCase();
  if (s(lead.gclid)) return "google";
  if (s(lead.fbclid) || s(lead.ctwa_clid) || s(lead.meta_ad_id) || META_AD_SOURCES.has(source)) return "meta";
  if (GOOGLE_AD_SOURCES.has(source) && PAID_MEDIUMS.has(medium)) return "google";
  return null;
}

export function describeLeadOrigin(lead: LeadOriginInput, campaignName: string | null): LeadOrigin {
  const source = s(lead.utm_source).toLowerCase();
  const utmCampaign = s(lead.utm_campaign) || null;
  const metadata = lead.metadata;
  const origem = s(metadata?.origem);
  const channel = s(lead.channel).toLowerCase();
  const funnel = lpFunnel(metadata);
  const paidDetail = s(campaignName) || utmCampaign || UNRESOLVED;

  const platform = paidPlatform(lead);
  if (platform === "google") return { kind: "pago", channel: "Google Ads", detail: paidDetail, funnel };
  if (platform === "meta") return { kind: "pago", channel: "Meta Ads", detail: paidDetail, funnel };
  if (s(lead.traffic_type).toLowerCase() === "paid") {
    return { kind: "pago", channel: capitalize(source) || "Anúncio", detail: utmCampaign || UNRESOLVED, funnel };
  }

  if (origem === "reativacao_bling") {
    const lote = metadata?.lote;
    const hasLote = lote !== undefined && lote !== null && String(lote).trim() !== "";
    return { kind: "importado", channel: "Reativação Bling", detail: hasLote ? `Lote ${lote}` : null, funnel: null };
  }
  if (channel === "bling" || origem === "bling_webhook") {
    return { kind: "importado", channel: "Bling", detail: null, funnel: null };
  }

  if (source === "instagram" || source === "facebook") {
    return { kind: "organico", channel: capitalize(source), detail: utmCampaign || s(lead.utm_medium) || null, funnel };
  }
  if (source) return { kind: "organico", channel: capitalize(source), detail: utmCampaign, funnel };

  if (funnel) return { kind: "organico", channel: "Landing page", detail: funnel, funnel: null };

  if (channel === "manual") return { kind: "importado", channel: "Cadastro manual", detail: null, funnel: null };
  if (channel === "campaign") return { kind: "importado", channel: "Importação de campanha", detail: null, funnel: null };
  if (channel === "whatsapp") {
    return { kind: "organico", channel: "WhatsApp direto", detail: null, funnel: null };
  }
  return { kind: "sem_rastreio", channel: "Sem rastreio", detail: null, funnel: null };
}

// ── Resolução do nome da campanha Google a partir do utm_campaign ─────────────
// Porte simplificado de `resolve_campaign_id` (traffic_report.py): sem chute —
// se não houver vencedor único, devolve null e a UI mostra o utm_campaign cru.
const STOP_WORDS = new Set(["sitelink"]); // = _UTM_STOP_WORDS do backend

function tokens(value: string): Set<string> {
  const norm = value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[|.\-\s_/]+/g, " ");
  return new Set(norm.split(" ").filter((t) => t && !/^\d+$/.test(t) && !STOP_WORDS.has(t)));
}

const subset = (a: Set<string>, b: Set<string>) => [...a].every((t) => b.has(t));

export function resolveGoogleCampaignName(
  utmCampaign: string | null,
  utmMedium: string | null,
  campaignNames: string[],
): string | null {
  const slug = s(utmCampaign).toLowerCase();
  if (!slug || campaignNames.length === 0) return null;
  const exact = campaignNames.find((n) => n.trim().toLowerCase() === slug);
  if (exact) return exact;
  const utm = tokens(slug);
  if (utm.size === 0) return null;
  let candidates = campaignNames.filter((n) => {
    const t = tokens(n);
    return t.size > 0 && (subset(utm, t) || subset(t, utm));
  });
  if (candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0];
  const med = tokens(s(utmMedium));
  if (med.size > 0) {
    const byMedium = candidates.filter((n) => [...med].some((t) => tokens(n).has(t)));
    if (byMedium.length === 1) return byMedium[0];
    if (byMedium.length > 0) candidates = byMedium;
  }
  const extra = candidates.map((n) => {
    const t = tokens(n);
    return [...t].filter((x) => !utm.has(x)).length + [...utm].filter((x) => !t.has(x)).length;
  });
  const best = Math.min(...extra);
  const winners = candidates.filter((_, i) => extra[i] === best);
  return winners.length === 1 ? winners[0] : null;
}
