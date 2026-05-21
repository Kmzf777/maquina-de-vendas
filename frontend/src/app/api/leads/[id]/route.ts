import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const body = await request.json();

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
