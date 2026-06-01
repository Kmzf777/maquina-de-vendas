import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const body = await request.json();

  // Sanitize phone if being updated
  if (body.phone !== undefined) {
    const digits = (body.phone ?? "").replace(/\D/g, "");
    if (digits.length < 8 || digits.length > 15) {
      return NextResponse.json(
        { error: `Telefone inválido: ${digits.length} dígito(s) (esperado: 8–15)` },
        { status: 422 }
      );
    }
    body.phone = digits;
  }

  const { data: currentLead } = await supabase
    .from("leads")
    .select("stage")
    .eq("id", id)
    .single();

  const { data, error } = await supabase
    .from("leads")
    .update(body)
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  if (currentLead) {
    const events = [];
    if (body.stage && body.stage !== currentLead.stage) {
      events.push({
        lead_id: id,
        event_type: "stage_change",
        old_value: currentLead.stage,
        new_value: body.stage,
      });
    }
    if (events.length > 0) {
      await supabase.from("lead_events").insert(events);
    }

    // Fire automation trigger for stage_enter (fire-and-forget)
    if (body.stage && body.stage !== currentLead.stage) {
      const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
      void fetch(`${backendUrl}/api/automation/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type: "stage_enter",
          lead_id: id,
          data: { stage: body.stage },
        }),
      }).catch(() => {});
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

  const { data: lead } = await supabase.from("leads").select("id").eq("id", id).single();
  if (!lead) return NextResponse.json({ error: "Lead not found" }, { status: 404 });

  await supabase.from("follow_up_jobs").delete().eq("lead_id", id);
  await supabase.from("campaign_enrollments").delete().eq("lead_id", id);
  await supabase.from("broadcast_leads").delete().eq("lead_id", id);
  await supabase.from("deals").delete().eq("lead_id", id);
  await supabase.from("lead_tags").delete().eq("lead_id", id);
  await supabase.from("token_usage").delete().eq("lead_id", id);
  await supabase.from("messages").delete().eq("lead_id", id);
  await supabase.from("conversations").delete().eq("lead_id", id);
  await supabase.from("leads").delete().eq("id", id);

  return NextResponse.json({ deleted: true, lead_id: id });
}
