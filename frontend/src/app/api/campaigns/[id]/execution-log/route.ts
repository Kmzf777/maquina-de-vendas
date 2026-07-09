import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const limit = Number(new URL(request.url).searchParams.get("limit") ?? "50");

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaign_execution_log")
    .select("id, enrollment_id, campaign_id, lead_id, node_id, node_type, status, log, created_at")
    .eq("campaign_id", id)
    .order("created_at", { ascending: false })
    .limit(limit);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: data ?? [] });
}
