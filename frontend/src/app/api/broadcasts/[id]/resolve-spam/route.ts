import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { conflict_lead_ids }: { conflict_lead_ids: string[] } = await request.json();

  if (!conflict_lead_ids || conflict_lead_ids.length === 0) {
    return NextResponse.json({ error: "conflict_lead_ids vazio" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // 1. Fetch original broadcast for copying fields
  const { data: orig, error: origErr } = await supabase
    .from("broadcasts")
    .select("*")
    .eq("id", id)
    .single();

  if (origErr || !orig) {
    return NextResponse.json({ error: "Broadcast não encontrado" }, { status: 404 });
  }

  // 2. Create new draft broadcast
  const { data: newBroadcast, error: createErr } = await supabase
    .from("broadcasts")
    .insert({
      name: `Rascunho - ${orig.name}`,
      channel_id: orig.channel_id,
      template_name: orig.template_name,
      template_language_code: orig.template_language_code,
      template_preset_id: orig.template_preset_id,
      template_variables: orig.template_variables,
      send_interval_min: orig.send_interval_min,
      send_interval_max: orig.send_interval_max,
      cadence_id: orig.cadence_id,
      agent_profile_id: orig.agent_profile_id,
      move_to_stage_id: orig.move_to_stage_id,
      env_tag: orig.env_tag,
      status: "draft",
      scheduled_at: null,
      total_leads: conflict_lead_ids.length,
    })
    .select("id, name")
    .single();

  if (createErr || !newBroadcast) {
    return NextResponse.json({ error: "Falha ao criar rascunho" }, { status: 500 });
  }

  // 3. Remove conflicting leads from original broadcast
  const { error: deleteErr } = await supabase
    .from("broadcast_leads")
    .delete()
    .eq("broadcast_id", id)
    .in("lead_id", conflict_lead_ids);

  if (deleteErr) {
    return NextResponse.json({ error: "Falha ao remover leads" }, { status: 500 });
  }

  // 4. Update total_leads count on original broadcast
  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id);

  await supabase
    .from("broadcasts")
    .update({ total_leads: count ?? 0 })
    .eq("id", id);

  // 5. Insert conflict leads into new draft broadcast
  const inserts = conflict_lead_ids.map((lead_id) => ({
    broadcast_id: newBroadcast.id,
    lead_id,
    status: "pending",
  }));

  const { error: insertErr } = await supabase
    .from("broadcast_leads")
    .insert(inserts);

  if (insertErr) {
    return NextResponse.json({ error: "Falha ao adicionar leads ao rascunho" }, { status: 500 });
  }

  return NextResponse.json({
    new_broadcast_id: newBroadcast.id,
    new_broadcast_name: newBroadcast.name,
    removed_count: conflict_lead_ids.length,
  });
}
