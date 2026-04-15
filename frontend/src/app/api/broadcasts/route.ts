import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("broadcasts")
    .select("*, cadences(id, name)")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("broadcasts")
    .insert({
      name: body.name,
      channel_id: body.channel_id || null,
      template_name: body.template_name,
      template_preset_id: body.template_preset_id || null,
      template_variables: body.template_variables || {},
      send_interval_min: body.send_interval_min || 3,
      send_interval_max: body.send_interval_max || 8,
      cadence_id: body.cadence_id || null,
      scheduled_at: body.scheduled_at || null,
      status: body.scheduled_at ? "scheduled" : "draft",
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
