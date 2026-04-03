import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadence_enrollments")
    .update(body)
    .eq("id", enrollId)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("cadence_enrollments").delete().eq("id", enrollId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
