import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { isSystemCampaign } from "@/lib/system-campaign";

type Params = { params: Promise<{ id: string }> };

// Mesma lista fechada do POST (src/app/api/campaigns/route.ts) — sem ela, dava pra
// criar uma cadência com o público certo mas não dava pra corrigir depois (PATCH
// fazia spread cego de `body` sem validar nada).
const AUDIENCIAS = ["ia", "humano", "ambos"];

// Mesma validação do POST (src/app/api/campaigns/route.ts) para send_start_hour /
// send_end_hour / skip_weekends — sem ela o PATCH fazia spread cego de `body` e um
// horário fora de 0-23 (ou uma janela invertida) ia direto pro banco.
function isValidHour(v: unknown): v is number {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 23;
}

function systemCampaignBlock() {
  return NextResponse.json(
    { error: "Cadência de sistema (espelho do motor da Valéria) — somente leitura" },
    { status: 409 },
  );
}

export async function GET(_req: NextRequest, { params }: Params) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: campaign, error } = await supabase.from("campaigns").select("*").eq("id", id).single();
  if (error) return NextResponse.json({ error: error.message }, { status: 404 });
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  return NextResponse.json({ ...campaign, nodes: nodes ?? [] });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  if (isSystemCampaign(id)) return systemCampaignBlock();
  const body = await request.json();

  // `status` só muda por /activate (12 regras de validação, hoje só no FastAPI) ou
  // /pause. Este PATCH faz `.update({ ...body })` — spread cego — logo abaixo: sem
  // esta trava, `{ status: "active" }` chegava direto aqui e contornava a validação
  // inteira que o /activate acabou de ganhar. É a porta dos fundos da trava.
  if (body.status !== undefined) {
    return NextResponse.json(
      { error: "status não pode ser alterado por aqui — use /activate ou /pause" },
      { status: 400 },
    );
  }

  if (body.audience !== undefined && !AUDIENCIAS.includes(body.audience)) {
    return NextResponse.json({ error: "audience inválido — use ia, humano ou ambos" }, { status: 400 });
  }
  const hasStart = body.send_start_hour !== undefined;
  const hasEnd = body.send_end_hour !== undefined;
  if (hasStart && !isValidHour(body.send_start_hour)) {
    return NextResponse.json({ error: "send_start_hour inválido — use um inteiro entre 0 e 23" }, { status: 400 });
  }
  if (hasEnd && !isValidHour(body.send_end_hour)) {
    return NextResponse.json({ error: "send_end_hour inválido — use um inteiro entre 0 e 23" }, { status: 400 });
  }
  if (body.skip_weekends !== undefined && typeof body.skip_weekends !== "boolean") {
    return NextResponse.json({ error: "skip_weekends inválido — use true ou false" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // Janela invertida é erro do chamador mesmo quando o PATCH só move um dos dois
  // lados (ex.: só send_start_hour, deixando send_end_hour como já estava salvo) —
  // por isso o lado ausente é lido do banco antes de comparar.
  if (hasStart || hasEnd) {
    let current: { send_start_hour: number; send_end_hour: number } | null = null;
    if (!hasStart || !hasEnd) {
      const res = await supabase
        .from("campaigns")
        .select("send_start_hour, send_end_hour")
        .eq("id", id)
        .single();
      current = res.data;
    }
    const startCmp: number = hasStart ? body.send_start_hour : (current?.send_start_hour ?? 7);
    const endCmp: number = hasEnd ? body.send_end_hour : (current?.send_end_hour ?? 18);
    if (startCmp >= endCmp) {
      return NextResponse.json({ error: "janela invertida — send_start_hour deve ser menor que send_end_hour" }, { status: 400 });
    }
  }

  const { data, error } = await supabase
    .from("campaigns")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const { id } = await params;
  if (isSystemCampaign(id)) return systemCampaignBlock();
  const supabase = await getServiceSupabase();
  const { data: camp } = await supabase.from("campaigns").select("status").eq("id", id).single();
  if (camp && !["draft", "archived"].includes(camp.status)) {
    return NextResponse.json({ error: "Apenas drafts e arquivadas podem ser excluídas" }, { status: 400 });
  }
  await supabase.from("campaigns").delete().eq("id", id);
  return NextResponse.json({ ok: true });
}
