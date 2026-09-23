# Origem do lead detalhada — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar no painel do lead em /conversas e no modal de /leads a origem detalhada (canal + campanha, ou sub-origem orgânica/importada).

**Architecture:** Função pura `describeLeadOrigin` em `lib/lead-origin.ts`; rota `GET /api/leads/[id]/origin` resolve o nome da campanha (Meta via `meta_ad_campaigns`, Google via `ad_spend`) e aplica a função; hook `useLeadOrigin` + componente `LeadOriginBlock` usados nos dois painéis. Spec: `docs/superpowers/specs/2026-09-23-origem-do-lead-design.md`.

**Tech Stack:** Next.js App Router (route handlers), Supabase JS (service client), React client components, Vitest.

**Execução em paralelo:** Onda 1 = Task 1 ∥ Task 3. Onda 2 = Task 2 ∥ Task 4. Contratos fixados abaixo, então as tarefas de uma onda não dependem uma da outra. Subagentes NÃO commitam — o coordenador commita ao fim de cada onda (evita corrida no index do git).

**Comandos:** rodar de `frontend/`. Teste: `npx vitest run <arquivo>`. Typecheck: `npx tsc --noEmit -p .`.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| Create `frontend/src/lib/lead-origin.ts` | Tipos + regras puras de origem + resolução de nome de campanha Google |
| Create `frontend/src/lib/lead-origin.test.ts` | Testes das regras |
| Create `frontend/src/app/api/leads/[id]/origin/route.ts` | Auth + leitura do lead + lookup de campanha |
| Create `frontend/src/app/api/leads/[id]/origin/route.test.ts` | Testes da rota |
| Create `frontend/src/hooks/use-lead-origin.ts` | Fetch da origem |
| Create `frontend/src/components/leads/lead-origin-block.tsx` | Bloco visual "Origem" |
| Modify `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx:213-231` | Troca os badges pelo bloco |
| Modify `frontend/src/components/leads/lead-detail-modal.tsx:305-306` | Bloco no topo de "Dados Gerais" |

---

### Task 1: Regras puras (`lib/lead-origin.ts`)

**Files:**
- Create: `frontend/src/lib/lead-origin.ts`
- Test: `frontend/src/lib/lead-origin.test.ts`

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/lead-origin.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/lead-origin.test.ts` — Expected: FAIL (módulo não existe).

- [ ] **Step 3: Implement** — `frontend/src/lib/lead-origin.ts`:

```ts
import { LP_ORIGINS } from "@/lib/constants";

/**
 * Origem do lead para os painéis de /leads e /conversas.
 *
 * As regras espelham `derive_channel` de `backend/app/campaigns/traffic_report.py`
 * (click-id > anúncio Meta > utm_source de anúncio > orgânico), para o que o
 * vendedor vê no painel bater com o relatório do /trafego. Spec:
 * docs/superpowers/specs/2026-09-23-origem-do-lead-design.md
 */
export type LeadOriginKind = "pago" | "organico" | "importado" | "sem_rastreio";

export interface LeadOrigin {
  kind: LeadOriginKind;
  channel: string;
  detail: string | null;
  page: string | null;
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

function lpPage(metadata: Record<string, unknown> | null): string | null {
  const origem = s(metadata?.origem);
  return origem && !IMPORT_ORIGINS.has(origem) ? lpLabel(origem) : null;
}

export function describeLeadOrigin(lead: LeadOriginInput, campaignName: string | null): LeadOrigin {
  const source = s(lead.utm_source).toLowerCase();
  const medium = s(lead.utm_medium).toLowerCase();
  const utmCampaign = s(lead.utm_campaign) || null;
  const metadata = lead.metadata;
  const origem = s(metadata?.origem);
  const channel = s(lead.channel).toLowerCase();
  const page = lpPage(metadata);
  const paidDetail = s(campaignName) || utmCampaign || UNRESOLVED;

  if (s(lead.gclid) || (GOOGLE_AD_SOURCES.has(source) && PAID_MEDIUMS.has(medium))) {
    return { kind: "pago", channel: "Google Ads", detail: paidDetail, page };
  }
  if (s(lead.fbclid) || s(lead.ctwa_clid) || s(lead.meta_ad_id) || META_AD_SOURCES.has(source)) {
    return { kind: "pago", channel: "Meta Ads", detail: paidDetail, page };
  }
  if (s(lead.traffic_type).toLowerCase() === "paid") {
    return { kind: "pago", channel: capitalize(source) || "Anúncio", detail: utmCampaign || UNRESOLVED, page };
  }

  const referral = metadata?.referral as Record<string, unknown> | undefined;
  const referrer = s(referral?.nome);
  if (referrer) return { kind: "organico", channel: "Indicação", detail: `de ${referrer}`, page: null };

  if (origem === "reativacao_bling") {
    const lote = metadata?.lote;
    const hasLote = lote !== undefined && lote !== null && String(lote).trim() !== "";
    return { kind: "importado", channel: "Reativação Bling", detail: hasLote ? `Lote ${lote}` : null, page: null };
  }
  if (channel === "bling" || origem === "bling_webhook") {
    return { kind: "importado", channel: "Bling", detail: null, page: null };
  }

  if (source === "instagram" || source === "facebook") {
    return { kind: "organico", channel: capitalize(source), detail: utmCampaign || s(lead.utm_medium) || null, page };
  }
  if (source) return { kind: "organico", channel: capitalize(source), detail: utmCampaign, page };

  if (page) return { kind: "organico", channel: "Landing page", detail: page, page: null };

  if (channel === "manual") return { kind: "importado", channel: "Cadastro manual", detail: null, page: null };
  if (channel === "campaign") return { kind: "importado", channel: "Importação de campanha", detail: null, page: null };
  if (channel === "whatsapp" || channel === "evolution") {
    return { kind: "organico", channel: "WhatsApp direto", detail: null, page: null };
  }
  return { kind: "sem_rastreio", channel: "Sem rastreio", detail: null, page: null };
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
```


- [ ] **Step 4: Run test** — `npx vitest run src/lib/lead-origin.test.ts` — Expected: PASS (todos).

- [ ] **Step 5: Commit** (coordenador): `git add frontend/src/lib/lead-origin.ts frontend/src/lib/lead-origin.test.ts && git commit -m "feat(leads): regras puras de origem detalhada do lead"`

---

### Task 2: Rota `GET /api/leads/[id]/origin`

**Files:**
- Create: `frontend/src/app/api/leads/[id]/origin/route.ts`
- Test: `frontend/src/app/api/leads/[id]/origin/route.test.ts`

Depende do contrato de `lib/lead-origin.ts` (Task 1): `describeLeadOrigin`, `resolveGoogleCampaignName`, `LEAD_ORIGIN_COLUMNS`, `LeadOriginInput`.

- [ ] **Step 1: Write the failing test** — `route.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({ getCurrentUser: vi.fn() }));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { getServiceSupabase } from "@/lib/supabase/api";

type Result = { data: unknown; error: { message: string } | null };

/** Fake mínimo do query builder: cada tabela devolve um Result fixo. */
function fakeSupabase(tables: Record<string, Result>) {
  return {
    from(table: string) {
      const result = tables[table] ?? { data: null, error: null };
      const builder: Record<string, unknown> = {};
      for (const m of ["select", "eq", "in", "order", "limit"]) builder[m] = () => builder;
      builder.maybeSingle = async () => result;
      builder.then = (resolve: (r: Result) => unknown) => Promise.resolve(result).then(resolve);
      return builder;
    },
  };
}

const call = (id = "lead-1") =>
  GET(new Request(`http://localhost/api/leads/${id}/origin`) as never, { params: Promise.resolve({ id }) });

const leadRow = (p: Record<string, unknown>) => ({
  traffic_type: null, utm_source: null, utm_medium: null, utm_campaign: null, gclid: null,
  fbclid: null, ctwa_clid: null, meta_ad_id: null, channel: null, metadata: null, ...p,
});

describe("GET /api/leads/[id]/origin", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u1", role: "vendedor" } as never);
  });

  it("401 sem sessão", async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new Error("no session"));
    expect((await call()).status).toBe(401);
  });

  it("404 lead inexistente", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({ leads: { data: null, error: null } }) as never);
    expect((await call()).status).toBe(404);
  });

  it("Meta: resolve nome da campanha pelo meta_ad_id", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({
      leads: { data: leadRow({ meta_ad_id: "ad-9", channel: "whatsapp" }), error: null },
      meta_ad_campaigns: { data: { campaign_name: "CTWA Atacado" }, error: null },
    }) as never);
    const res = await call();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ kind: "pago", channel: "Meta Ads", detail: "CTWA Atacado", page: null });
  });

  it("Meta: falha no lookup não derruba — Campanha não identificada", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({
      leads: { data: leadRow({ meta_ad_id: "ad-9" }), error: null },
      meta_ad_campaigns: { data: null, error: { message: "boom" } },
    }) as never);
    const res = await call();
    expect(res.status).toBe(200);
    expect((await res.json()).detail).toBe("Campanha não identificada");
  });

  it("Google: resolve pelo ad_spend", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({
      leads: { data: leadRow({ gclid: "g", utm_campaign: "marca_propria" }), error: null },
      ad_spend: { data: [{ campaign_name: "Search | Marca Própria" }, { campaign_name: "PMAX | Atacado" }], error: null },
    }) as never);
    expect((await (await call()).json()).detail).toBe("Search | Marca Própria");
  });

  it("500 se a leitura do lead falhar", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({ leads: { data: null, error: { message: "db" } } }) as never);
    expect((await call()).status).toBe(500);
  });
});
```

- [ ] **Step 2: Run** — `npx vitest run "src/app/api/leads/[id]/origin/route.test.ts"` — Expected: FAIL (route não existe).

- [ ] **Step 3: Implement** — `route.ts`:

```ts
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import {
  LEAD_ORIGIN_COLUMNS,
  describeLeadOrigin,
  resolveGoogleCampaignName,
  type LeadOriginInput,
} from "@/lib/lead-origin";

/**
 * Origem detalhada do lead (canal + campanha) para os painéis de /leads e
 * /conversas. Qualquer usuário autenticado — o vendedor usa /conversas.
 * O lookup da campanha é best-effort: se falhar, a origem sai sem o nome.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const sb = await getServiceSupabase();

  const { data, error } = await sb.from("leads").select(LEAD_ORIGIN_COLUMNS).eq("id", id).maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "not found" }, { status: 404 });
  const lead = data as unknown as LeadOriginInput;

  let campaignName: string | null = null;
  try {
    if (lead.meta_ad_id) {
      const { data: mac } = await sb
        .from("meta_ad_campaigns")
        .select("campaign_name")
        .eq("ad_id", lead.meta_ad_id)
        .maybeSingle();
      campaignName = (mac as { campaign_name?: string | null } | null)?.campaign_name ?? null;
    } else if (lead.gclid || lead.utm_campaign) {
      const { data: rows } = await sb.from("ad_spend").select("campaign_name").eq("platform", "google");
      const names = [
        ...new Set(((rows ?? []) as { campaign_name: string | null }[]).map((r) => r.campaign_name ?? "").filter(Boolean)),
      ];
      campaignName = resolveGoogleCampaignName(lead.utm_campaign, lead.utm_medium, names);
    }
  } catch {
    campaignName = null;
  }

  return NextResponse.json(describeLeadOrigin(lead, campaignName));
}
```

Nota: para o ramo Google, o nome resolvido só é usado quando a origem for Google Ads (em outros casos `describeLeadOrigin` ignora `campaignName`). (`ad_spend.platform` tem default `'google'` — `supabase/migrations/20260805_ad_spend.sql:5`.)

- [ ] **Step 4: Run** — mesmo comando — Expected: PASS.

- [ ] **Step 5: Commit** (coordenador): `git commit -m "feat(leads): GET /api/leads/[id]/origin resolve campanha do lead"`

---

### Task 3: Hook + componente `LeadOriginBlock`

**Files:**
- Create: `frontend/src/hooks/use-lead-origin.ts`
- Create: `frontend/src/components/leads/lead-origin-block.tsx`

Depende só do tipo `LeadOrigin` de `@/lib/lead-origin` (Task 1). Sem teste de componente: `@testing-library`/`jsdom` não estão no node_modules do repo (os `.test.tsx` existentes não rodam). Verificação = typecheck.

- [ ] **Step 1: Hook** — `frontend/src/hooks/use-lead-origin.ts`:

```ts
"use client";

import { useEffect, useState } from "react";
import type { LeadOrigin } from "@/lib/lead-origin";

/** Origem detalhada do lead (GET /api/leads/[id]/origin). `error` = fetch falhou. */
export function useLeadOrigin(leadId: string | null | undefined) {
  const [origin, setOrigin] = useState<LeadOrigin | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!leadId) {
      setOrigin(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetch(`/api/leads/${encodeURIComponent(leadId)}/origin`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body: LeadOrigin) => {
        if (!cancelled) setOrigin(body);
      })
      .catch(() => {
        if (!cancelled) {
          setOrigin(null);
          setError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  return { origin, loading, error };
}
```

- [ ] **Step 2: Componente** — `frontend/src/components/leads/lead-origin-block.tsx` (segue o visual dos badges atuais de `crm-perfil-tab.tsx:216-230`):

```tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { useLeadOrigin } from "@/hooks/use-lead-origin";
import type { LeadOriginKind } from "@/lib/lead-origin";

const KIND_LABEL: Record<LeadOriginKind, string> = {
  pago: "Pago",
  organico: "Orgânico",
  importado: "Importado",
  sem_rastreio: "",
};

const KIND_CLASS: Record<LeadOriginKind, string> = {
  pago: "border-0 bg-[#111111] text-white font-medium",
  organico: "border-[#0bdf50]/30 bg-[#0bdf50]/10 text-[#0f9d43] font-normal",
  importado: "border-[#dedbd6] bg-[#f4f4f0] text-[#5f6368] font-normal",
  sem_rastreio: "border-[#dedbd6] text-[#7b7b78] font-normal",
};

/** Bloco "Origem" do lead: tipo · canal, e a campanha/página/indicador embaixo. */
export function LeadOriginBlock({ leadId }: { leadId: string }) {
  const { origin, loading, error } = useLeadOrigin(leadId);

  return (
    <div>
      <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Origem</span>
      {loading && !origin && <p className="text-[12px] text-[#7b7b78] px-2">Carregando origem…</p>}
      {error && <p className="text-[12px] text-[#7b7b78] px-2">Origem indisponível</p>}
      {origin && (
        <div className="px-2 space-y-0.5">
          <Badge
            variant="outline"
            className={`h-[18px] px-1.5 text-[10px] rounded-[4px] ${KIND_CLASS[origin.kind]}`}
          >
            {KIND_LABEL[origin.kind] ? `${KIND_LABEL[origin.kind]} · ${origin.channel}` : origin.channel}
          </Badge>
          {origin.detail && (
            <p className="text-[13px] text-[#111111] break-words" title={origin.detail}>
              {origin.detail}
            </p>
          )}
          {origin.page && <p className="text-[11px] text-[#7b7b78]">via página {origin.page}</p>}
        </div>
      )}
    </div>
  );
}
```

Confirme que `@/components/ui/badge` existe e aceita `variant="outline"` (já é usado assim em `crm-perfil-tab.tsx`).

- [ ] **Step 3: Typecheck** — `npx tsc --noEmit -p .` — Expected: nenhum erro nos arquivos novos (erros pré-existentes em outros arquivos: anotar, não corrigir).

- [ ] **Step 4: Commit** (coordenador): `git commit -m "feat(leads): hook useLeadOrigin e bloco LeadOriginBlock"`

---

### Task 4: Integração nos dois painéis

**Files:**
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx:213-231`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx:305-306`

Depende só da assinatura `LeadOriginBlock({ leadId: string })` de `@/components/leads/lead-origin-block` (Task 3).

- [ ] **Step 1: /conversas** — em `crm-perfil-tab.tsx`, substituir o bloco de cabeçalho de Identificação:

```tsx
        <div className="flex items-center gap-2">
          <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Identificacao</h4>
          {lead.traffic_type === "paid" && ( ...Badge Pago... )}
          {lead.traffic_type === "organic" && ( ...Badge Orgânico... )}
        </div>
```

por:

```tsx
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Identificacao</h4>
        <LeadOriginBlock leadId={lead.id} />
```

Adicionar `import { LeadOriginBlock } from "@/components/leads/lead-origin-block";`. Se `Badge` ficar sem uso no arquivo, remover o import.

- [ ] **Step 2: /leads** — em `lead-detail-modal.tsx`, logo dentro de `{activeTab === "dados" && (<div>`, antes de `<div className="grid grid-cols-2 gap-5">`, inserir:

```tsx
              <div className="mb-5 pb-5 border-b border-[#dedbd6]">
                <LeadOriginBlock leadId={lead.id} />
              </div>
```

Adicionar o import. Confirme que a variável do lead no modal chama `lead` e tem `id` (ajuste o nome se for outro).

- [ ] **Step 3: Typecheck** — `npx tsc --noEmit -p .` — Expected: sem erros novos.

- [ ] **Step 4: Commit** (coordenador): `git commit -m "feat(leads): origem detalhada no painel de /conversas e no modal de /leads"`

---

### Task 5: Verificação final (coordenador)

- [ ] `npx vitest run` (suíte toda do frontend) — todos verdes, ou só falhas pré-existentes documentadas.
- [ ] `npx tsc --noEmit -p .` — sem erros novos.
- [ ] `npx next lint` nos arquivos alterados, se o projeto tiver lint configurado.
- [ ] Code review do diff inteiro.
