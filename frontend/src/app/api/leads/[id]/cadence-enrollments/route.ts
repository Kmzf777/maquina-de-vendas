import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: leadId } = await params;
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status");
  const limit = Math.min(Math.max(1, parseInt(searchParams.get("limit") || "10", 10) || 10), 100);

  const supabase = await getServiceSupabase();

  let query = supabase
    .from("cadence_enrollments")
    .select("*, cadences(id, name)")
    .eq("lead_id", leadId)
    .eq("env_tag", APP_ENV)
    .order("enrolled_at", { ascending: false })
    .limit(limit);

  if (status) query = query.eq("status", status);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
