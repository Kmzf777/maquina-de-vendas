import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { fillDailyCosts, type DailyCostRow } from "@/lib/stats-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const stage = sp.get("stage");
  const model = sp.get("model");

  const sb = await getServiceSupabase();

  const { data, error } = await sb.rpc("stats_costs_daily", {
    p_start: startDate,
    p_end: endDate,
    p_stage: stage || null,
    p_model: model || null,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const rows = (Array.isArray(data) ? data : []) as DailyCostRow[];
  // Gap-fill (dias zerados) continua aqui — a RPC só devolve dias com dados.
  return NextResponse.json({ data: fillDailyCosts(rows, startDate, endDate) });
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
