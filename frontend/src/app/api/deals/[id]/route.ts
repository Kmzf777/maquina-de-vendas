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

  if (body.stage === "fechado_ganho" || body.stage === "fechado_perdido") {
    updates.closed_at = new Date().toISOString();
  }

  const { data, error } = await supabase
    .from("deals")
    .update(updates)
    .eq("id", id)
    .select("*, leads(id, name, company, phone, nome_fantasia)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
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
