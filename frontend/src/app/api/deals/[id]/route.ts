import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { assertCanWriteDealsInPipeline } from "@/lib/supabase/pipeline-access";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const updates: Record<string, unknown> = { ...body, updated_at: new Date().toISOString() };

  // Capture current stage_id before update to detect stage changes
  const { data: currentDeal } = await supabase
    .from("deals")
    .select("stage_id, lead_id, pipeline_id")
    .eq("id", id)
    .single();
  if (!currentDeal) return NextResponse.json({ error: "Deal não encontrado." }, { status: 404 });
  const oldStageId = currentDeal.stage_id ?? null;

  // Guarda: precisa poder escrever no funil de origem
  if (currentDeal.pipeline_id) {
    const guardSrc = await assertCanWriteDealsInPipeline(supabase, currentDeal.pipeline_id);
    if (!guardSrc.ok) return NextResponse.json({ error: guardSrc.error }, { status: guardSrc.status });
  }
  // Movimentação entre funis: precisa poder escrever também no destino
  if (body.pipeline_id && body.pipeline_id !== currentDeal.pipeline_id) {
    const guardDst = await assertCanWriteDealsInPipeline(supabase, body.pipeline_id);
    if (!guardDst.ok) return NextResponse.json({ error: guardDst.error }, { status: guardDst.status });
  }

  // Se stage_id foi fornecido, detectar se é stage protegido para setar closed_at
  let newStageKey: string | null = null;
  if (body.stage_id) {
    const { data: stage } = await supabase
      .from("pipeline_stages")
      .select("key")
      .eq("id", body.stage_id)
      .single();
    newStageKey = stage?.key ?? null;
    if (stage?.key === "fechado_ganho" || stage?.key === "fechado_perdido") {
      updates.closed_at = new Date().toISOString();
    }
  }

  const { data, error } = await supabase
    .from("deals")
    .update(updates)
    .eq("id", id)
    .select("*, leads(id, name, company, phone, nome_fantasia, notes), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fire automation triggers if stage changed (fire-and-forget)
  if (body.stage_id && body.stage_id !== oldStageId && newStageKey) {
    const leadId = currentDeal?.lead_id ?? data?.lead_id;
    if (leadId) {
      const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
      const triggerPromises: Promise<Response>[] = [
        fetch(`${backendUrl}/api/automation/trigger`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            event_type: "deal_stage_enter",
            lead_id: leadId,
            data: { stage: newStageKey, deal_id: id },
          }),
        }),
      ];
      if (newStageKey === "fechado_perdido") {
        triggerPromises.push(
          fetch(`${backendUrl}/api/automation/trigger`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              event_type: "deal_closed_lost",
              lead_id: leadId,
              data: { deal_id: id },
            }),
          })
        );
      }
      void Promise.allSettled(triggerPromises);
    }
  }

  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: deal } = await supabase
    .from("deals")
    .select("pipeline_id")
    .eq("id", id)
    .single();
  if (deal?.pipeline_id) {
    const guard = await assertCanWriteDealsInPipeline(supabase, deal.pipeline_id);
    if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  }

  const { error } = await supabase.from("deals").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
