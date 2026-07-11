import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapCostsSummary, type CostsSummaryRow } from "@/lib/stats-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const stage = sp.get("stage");
  const model = sp.get("model");
  const leadId = sp.get("lead_id");

  const sb = await getServiceSupabase();

  const { data, error } = await sb.rpc("stats_costs_summary", {
    p_start: startDate,
    p_end: endDate,
    p_stage: stage || null,
    p_model: model || null,
    p_lead_id: leadId || null,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const row = (Array.isArray(data) ? data[0] : data) as CostsSummaryRow | undefined;
  return NextResponse.json(mapCostsSummary(row));
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
