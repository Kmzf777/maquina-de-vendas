import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("campaign_enrollments")
    .select("*, campaigns:campaign_id(id, name, status, created_at)")
    .eq("lead_id", id)
    .order("enrolled_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
