import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_seller_config")
    .select("*")
    .order("display_name");
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const body = await req.json();
  const {
    user_id,
    channel_id,
    display_name,
    window_start_minute,
    window_end_minute,
    active_weekdays,
    active,
  } = body;

  if (!user_id || !channel_id) {
    return NextResponse.json({ error: "user_id e channel_id obrigatórios" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_seller_config")
    .upsert(
      {
        user_id,
        channel_id,
        display_name: display_name ?? "",
        window_start_minute: window_start_minute ?? 600,
        window_end_minute: window_end_minute ?? 960,
        active_weekdays: active_weekdays ?? [1, 2, 3, 4, 5],
        active: active ?? true,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" }
    )
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data, { status: 201 });
}
