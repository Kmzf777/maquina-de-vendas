import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

const VALID_STATUSES = new Set(["pending", "awaiting_reopen", "sent", "cancelled"]);
const MAX_LIMIT = 200;

type Supabase = Awaited<ReturnType<typeof getServiceSupabase>>;

/** String não-vazia do metadata, ou null (o metadata é `Record<string, unknown>` cru). */
function texto(valor: unknown): string | null {
  return typeof valor === "string" && valor.trim() !== "" ? valor : null;
}

/** `metadata.toque` é int no motor; qualquer outra coisa vira null em vez de NaN na tela. */
function numero(valor: unknown): number | null {
  return typeof valor === "number" && Number.isFinite(valor) ? valor : null;
}

/**
 * Rótulo da etapa em que cada card está AGORA — UMA consulta para a página inteira.
 *
 * A etapa sai do `deals`, NÃO de `metadata.stage_id`: o metadata guarda a etapa de
 * quando o lead foi matriculado, e desde 25/09 um card que mudou de coluna tem a
 * esteira CANCELADA no próximo toque. Mostrar a etapa da matrícula esconderia
 * exatamente o que o operador precisa ver — o job pendente que vai morrer sem enviar.
 *
 * O embed `pipeline_stages(label)` faz o join no PostgREST: uma requisição, nunca uma
 * por job. E falhar aqui é **fail-soft** — mapa vazio, `etapa_atual: null`, a resposta
 * sai inteira. Um painel de observação não pode quebrar por causa de uma coluna.
 */
async function etapasAtuaisPorDeal(supabase: Supabase, dealIds: string[]): Promise<Map<string, string>> {
  const mapa = new Map<string, string>();
  if (dealIds.length === 0) return mapa;

  let linhas: unknown[];
  try {
    const { data, error } = await supabase
      .from("deals")
      .select("id, pipeline_stages(label)")
      .in("id", dealIds);
    if (error) return mapa;
    linhas = (data ?? []) as unknown[];
  } catch {
    return mapa;
  }

  for (const linha of linhas) {
    const deal = (linha ?? {}) as { id?: unknown; pipeline_stages?: unknown };
    const id = texto(deal.id);
    if (!id) continue;
    // Join singular: supabase-js tipa o embed como array | objeto dependendo do FK.
    const bruto = deal.pipeline_stages;
    const etapa = (Array.isArray(bruto) ? bruto[0] : bruto) as { label?: unknown } | null | undefined;
    const label = texto(etapa?.label);
    if (label) mapa.set(id, label);
  }
  return mapa;
}

/** Lista global de follow_up_jobs para o painel do motor (aba Follow-up).
 *  pending/awaiting_reopen: próximos primeiro (fire_at asc);
 *  sent/cancelled: mais recentes primeiro. */
export async function GET(request: NextRequest) {
  const status = request.nextUrl.searchParams.get("status") ?? "pending";
  if (!VALID_STATUSES.has(status)) {
    return NextResponse.json({ error: `status inválido: ${status}` }, { status: 400 });
  }
  const rawLimit = Number(request.nextUrl.searchParams.get("limit") ?? 100);
  const limit = Math.min(Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : 100, MAX_LIMIT);

  const supabase = await getServiceSupabase();
  const ascending = status === "pending" || status === "awaiting_reopen";
  const orderColumn = status === "sent" ? "sent_at" : "fire_at";

  const { data, error } = await supabase
    .from("follow_up_jobs")
    .select("id, sequence, job_type, status, fire_at, sent_at, cancel_reason, metadata, lead_id, conversation_id, leads(name, phone)")
    .eq("env_tag", APP_ENV)
    .eq("status", status)
    .order(orderColumn, { ascending, nullsFirst: false })
    .limit(limit);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const jobs = data ?? [];
  // O metadata é lido uma vez só: a lista de deal_id sai daqui e volta ao `map` abaixo.
  const metadados = jobs.map((j) => (j.metadata ?? {}) as Record<string, unknown>);
  const dealIds = [...new Set(metadados.map((md) => texto(md.deal_id)).filter((id): id is string => id !== null))];
  // Job sem deal_id (todos os da ValerIA) não entra na lista — sem deal_id, sem consulta.
  const etapas = await etapasAtuaisPorDeal(supabase, dealIds);

  const rows = jobs.map((j, i) => {
    const md = metadados[i];
    // Join singular: supabase-js tipa embed como array | objeto dependendo do FK — normaliza.
    const lead = (Array.isArray(j.leads) ? j.leads[0] : j.leads) as
      | { name: string | null; phone: string | null }
      | null
      | undefined;
    const dealId = texto(md.deal_id);
    return {
      id: j.id,
      sequence: j.sequence,
      job_type: j.job_type,
      status: j.status,
      fire_at: j.fire_at,
      sent_at: j.sent_at,
      cancel_reason: j.cancel_reason,
      // Intocado de propósito: é campo da ValerIA e não faz parte desta entrega.
      objetivo: (md.objetivo as string | undefined) ?? null,
      lead_id: j.lead_id,
      conversation_id: j.conversation_id,
      lead_name: lead?.name ?? null,
      lead_phone: lead?.phone ?? null,
      // --- contexto das esteiras do João (BoardJob; a tela não traduz key nenhuma) ---
      cadencia: texto(md.cadencia),
      funil: texto(md.funil),
      toque: numero(md.toque),
      acao: texto(md.acao),
      etapa_atual: dealId ? (etapas.get(dealId) ?? null) : null,
    };
  });

  return NextResponse.json(rows);
}
