import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

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
    .select("stage_id, lead_id")
    .eq("id", id)
    .single();
  const oldStageId = currentDeal?.stage_id ?? null;

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
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fire automation triggers if stage changed
  if (body.stage_id && body.stage_id !== oldStageId && newStageKey) {
    const leadId = currentDeal?.lead_id ?? data?.lead_id;
    if (leadId) {
      try {
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
        await Promise.allSettled(triggerPromises);
      } catch {
        // Hook failed — do not interrupt the deal update response
      }
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
  const { error } = await supabase.from("deals").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
