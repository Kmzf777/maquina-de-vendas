import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapCostsBreakdown, type BreakdownRow } from "@/lib/stats-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const groupBy = sp.get("group_by") || "stage";

  const sb = await getServiceSupabase();

  const { data, error } = await sb.rpc("stats_costs_breakdown", {
    p_start: startDate,
    p_end: endDate,
    p_group_by: groupBy,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const rows = (Array.isArray(data) ? data : []) as BreakdownRow[];
  return NextResponse.json({ data: mapCostsBreakdown(rows) });
}

function defaultStart() {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return d.toISOString().slice(0, 10);
}

function defaultEnd() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}
