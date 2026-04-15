import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("cadences")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadences")
    .insert({
      name: body.name,
      description: body.description || null,
      target_type: body.target_type || "manual",
      target_stage: body.target_stage || null,
      stagnation_days: body.stagnation_days || null,
      send_start_hour: body.send_start_hour ?? 7,
      send_end_hour: body.send_end_hour ?? 18,
      cooldown_hours: body.cooldown_hours ?? 48,
      max_messages: body.max_messages ?? 5,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
