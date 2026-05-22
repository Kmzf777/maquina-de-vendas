import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const body = await req.json();
  const action = body.action as "pause" | "resume";
  const newStatus = action === "pause" ? "paused" : "active";
  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("campaign_enrollments")
    .update({ status: newStatus })
    .eq("id", enrollId)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const sb = await getServiceSupabase();
  const { error } = await sb
    .from("campaign_enrollments")
    .delete()
    .eq("id", enrollId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
