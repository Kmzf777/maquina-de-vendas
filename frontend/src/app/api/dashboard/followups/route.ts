import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapFollowups, type FollowupsRow } from "@/lib/dashboard-mappers";

export async function GET(_req: NextRequest) {
  const sb = await getServiceSupabase();
  const { data, error } = await sb.rpc("dashboard_followups", {});
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const row = (Array.isArray(data) ? data[0] : data) as FollowupsRow | undefined;
  return NextResponse.json(mapFollowups(row));
}