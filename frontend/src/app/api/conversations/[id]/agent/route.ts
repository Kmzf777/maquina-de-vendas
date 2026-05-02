import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  // Resolve lead_id for this conversation
  const { data: conv, error: convErr } = await supabase
    .from("conversations")
    .select("lead_id")
    .eq("id", id)
    .single();

  if (convErr || !conv?.lead_id) {
    return NextResponse.json({ error: "conversation not found" }, { status: 404 });
  }

  const patch: Record<string, unknown> = {};
  if (body.ai_enabled !== undefined) patch.ai_enabled = body.ai_enabled;
  if (body.agent_profile_id !== undefined) patch.agent_profile_id = body.agent_profile_id;

  const { data: lead, error: leadErr } = await supabase
    .from("leads")
    .update(patch)
    .eq("id", conv.lead_id)
    .select("id, ai_enabled")
    .single();

  if (leadErr) {
    return NextResponse.json({ error: leadErr.message }, { status: 500 });
  }

  return NextResponse.json({ id, leads: lead });
}
