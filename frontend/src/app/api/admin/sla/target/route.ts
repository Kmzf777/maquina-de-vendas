import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_settings")
    .select("target_minutes")
    .eq("id", 1)
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function PUT(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const { target_minutes } = await req.json();
  if (typeof target_minutes !== "number" || target_minutes <= 0) {
    return NextResponse.json({ error: "target_minutes inválido" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_settings")
    .upsert({ id: 1, target_minutes, updated_at: new Date().toISOString() }, { onConflict: "id" })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}
