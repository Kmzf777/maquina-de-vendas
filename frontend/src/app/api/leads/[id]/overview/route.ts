// Painel lateral do lead no drill-down de /trafego/campanha.
//
// Por que uma rota agregadora em vez de reusar as sete rotas /api/leads/[id]/*:
// o painel abre a cada clique numa linha da tabela e precisa do conjunto INTEIRO
// para desenhar a trilha do funil. Sete round-trips do browser fariam o painel
// montar aos pedaços — e a trilha piscaria entre estados incoerentes ("comprou"
// antes de "conversou" carregar). Aqui as consultas correm em paralelo no
// servidor e o painel recebe uma foto consistente.
//
// Admin-only: /trafego inteiro é admin-only e esta rota usa a service key, que
// ignora RLS. Sem o portão, qualquer sessão autenticada leria qualquer lead.
//
// A tradução linha → payload mora em lead-overview-rows.ts, que é testado. Aqui
// ficam só as consultas.

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import type { LeadOverview } from "@/lib/lead-overview";
import {
  mapBroadcast,
  mapCadence,
  mapDeal,
  mapEvent,
  mapFollowup,
  mapLead,
  mapNote,
  mapSale,
  str,
  type Row,
} from "@/lib/lead-overview-rows";

/** Trilhas longas não cabem na tela nem no orçamento de payload. */
const MAX_EVENTS = 100;
const MAX_NOTES = 50;
const MAX_ROWS = 100;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") {
      return NextResponse.json({ error: "forbidden" }, { status: 403 });
    }
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const sb = await getServiceSupabase();

  const { data: leadRaw, error: leadError } = await sb
    .from("leads")
    .select(
      "id, name, phone, company, email, stage, status, channel, assigned_to, created_at, " +
        "last_msg_at, last_customer_message_at, first_response_at, entered_stage_at, " +
        "utm_source, utm_medium, utm_campaign, traffic_type, notes",
    )
    .eq("id", id)
    .maybeSingle();

  if (leadError) {
    return NextResponse.json({ error: leadError.message }, { status: 500 });
  }
  if (!leadRaw) {
    return NextResponse.json({ error: "lead_not_found" }, { status: 404 });
  }

  // Seções falham de forma independente. Uma tabela indisponível vira um aviso
  // nomeado em `partial` — nunca um array vazio silencioso, que leria como
  // "este lead não tem vendas" quando na verdade a consulta caiu.
  const partial: string[] = [];

  async function section<T>(name: string, run: () => Promise<T>, fallback: T): Promise<T> {
    try {
      return await run();
    } catch {
      partial.push(name);
      return fallback;
    }
  }

  // O client Supabase é destipado neste projeto (sem `Database` gerado), então o
  // select montado por concatenação volta como `GenericStringError`. O cast é
  // para `Row`, e cada campo passa pelos mapeadores testados de
  // lead-overview-rows.ts — o dado nunca é consumido às cegas.
  function unwrap(res: { data: unknown; error: { message: string } | null }): Row[] {
    if (res.error) throw new Error(res.error.message);
    return (res.data ?? []) as Row[];
  }

  const [deals, sales, events, notes, messages, cadences, broadcasts, followups] = await Promise.all([
    section(
      "oportunidades",
      async () =>
        unwrap(
          await sb
            .from("deals")
            .select(
              "id, title, value, created_at, updated_at, lost_reason, " +
                "pipeline_stages(key, label, dot_color), pipelines(name)",
            )
            .eq("lead_id", id)
            .order("created_at", { ascending: false })
            .limit(MAX_ROWS),
        ).map(mapDeal),
      [],
    ),

    // Sem o filtro de escopo de vendedor de /api/leads/[id]/sales: o portão
    // acima já garante admin, e admin enxerga a receita inteira do lead.
    section(
      "vendas",
      async () =>
        unwrap(
          await sb
            .from("sales")
            .select("id, value, product, sold_at, sold_by, origin, status")
            .eq("lead_id", id)
            .order("sold_at", { ascending: false })
            .limit(MAX_ROWS),
        ).map(mapSale),
      [],
    ),

    section(
      "eventos",
      async () =>
        unwrap(
          await sb
            .from("lead_events")
            .select("id, event_type, old_value, new_value, created_at")
            .eq("lead_id", id)
            .order("created_at", { ascending: false })
            .limit(MAX_EVENTS),
        ).map(mapEvent),
      [],
    ),

    section(
      "notas",
      async () =>
        unwrap(
          await sb
            .from("lead_notes")
            .select("id, author, content, created_at")
            .eq("lead_id", id)
            .order("created_at", { ascending: false })
            .limit(MAX_NOTES),
        ).map(mapNote),
      [],
    ),

    // Contagem por `head: true`: o PostgREST corta listas em 1.000 linhas, e uma
    // conversa longa passa disso. Contar no banco é o único jeito de o número
    // não mentir para baixo.
    section<LeadOverview["messages"]>(
      "mensagens",
      async () => {
        const countOf = async (role?: string) => {
          let q = sb.from("messages").select("id", { count: "exact", head: true }).eq("lead_id", id);
          if (role) q = q.eq("role", role);
          const { count, error } = await q;
          if (error) throw new Error(error.message);
          return count ?? 0;
        };
        const edgeAt = async (role: string | null, ascending: boolean) => {
          let q = sb.from("messages").select("created_at").eq("lead_id", id);
          if (role) q = q.eq("role", role);
          const { data, error } = await q.order("created_at", { ascending }).limit(1);
          if (error) throw new Error(error.message);
          return str(((data ?? []) as Row[])[0]?.created_at);
        };
        const [total, inbound, outbound, firstInbound, last] = await Promise.all([
          countOf(),
          countOf("user"),
          countOf("assistant"),
          edgeAt("user", true),
          edgeAt(null, false),
        ]);
        return { total, inbound, outbound, first_inbound_at: firstInbound, last_at: last };
      },
      { total: 0, inbound: 0, outbound: 0, first_inbound_at: null, last_at: null },
    ),

    section(
      "cadências",
      async () =>
        unwrap(
          await sb
            .from("campaign_enrollments")
            .select("id, status, enrolled_at, campaigns:campaign_id(name)")
            .eq("lead_id", id)
            .order("enrolled_at", { ascending: false })
            .limit(MAX_ROWS),
        ).map(mapCadence),
      [],
    ),

    section(
      "disparos",
      async () =>
        unwrap(
          await sb
            .from("broadcast_leads")
            .select("id, status, sent_at, first_replied_at, broadcasts(name)")
            .eq("lead_id", id)
            .order("sent_at", { ascending: false, nullsFirst: false })
            .limit(MAX_ROWS),
        ).map(mapBroadcast),
      [],
    ),

    section(
      "follow-ups",
      async () =>
        unwrap(
          await sb
            .from("follow_up_jobs")
            .select("sequence, job_type, status, fire_at, sent_at, metadata")
            .eq("lead_id", id)
            .order("fire_at", { ascending: false })
            .limit(MAX_ROWS),
        ).map(mapFollowup),
      [],
    ),
  ]);

  const payload: LeadOverview & { partial: string[] } = {
    lead: mapLead(leadRaw as unknown as Row),
    deals,
    sales,
    events,
    notes,
    messages,
    cadences,
    broadcasts,
    followups,
    partial,
  };

  return NextResponse.json(payload);
}
