import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { blockedLeadIds } from "@/lib/supabase/lead-blocked";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("broadcast_leads")
    .select("*, leads(id, name, phone, company)")
    .eq("broadcast_id", id)
    .order("sent_at", { ascending: false, nullsFirst: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const leadIds: string[] = body.lead_ids || [];
  let assigned = 0;

  // CAMADA 1 — filtro de origem, espelhando `assign_leads` em
  // `backend/app/broadcast/router.py:121`. O CRM insere em `broadcast_leads` com
  // service-role por ESTA rota (quick-send-modal, create-broadcast-modal e
  // broadcast-detail), sem passar pelo FastAPI — sem o filtro aqui, a camada 1 inteira
  // do broadcast é contornada e quem pediu para sair volta para a fila de disparo.
  // Em lote de propósito: um check por lead custaria 2 idas ao Supabase por lead e a
  // rota estouraria o tempo com algumas centenas de leads.
  const bloqueados = await blockedLeadIds(supabase, leadIds);
  let skipped_blacklist = 0;

  for (const leadId of leadIds) {
    // Filtro SILENCIOSO, não erro: o disparo prossegue com os demais leads. O contador
    // volta na resposta para a UI poder avisar quantos ficaram de fora.
    if (bloqueados.has(leadId)) {
      skipped_blacklist++;
      continue;
    }
    const { error } = await supabase
      .from("broadcast_leads")
      .insert({ broadcast_id: id, lead_id: leadId });
    if (!error) assigned++;
  }

  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id);

  await supabase
    .from("broadcasts")
    .update({ total_leads: count || 0 })
    .eq("id", id);

  // `skipped_blacklist` tem o mesmo nome e formato do contrato do FastAPI
  // (`backend/app/broadcast/router.py:147`), para a UI tratar as duas origens igual.
  return NextResponse.json({ assigned, skipped_blacklist });
}
