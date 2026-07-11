import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapTopLeads, type TopLeadRow, type LeadInfo } from "@/lib/stats-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const limit = Math.min(Number(sp.get("limit") || 20), 100);

  const sb = await getServiceSupabase();

  const { data, error } = await sb.rpc("stats_costs_top_leads", {
    p_start: startDate,
    p_end: endDate,
    p_limit: limit,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const rows = (Array.isArray(data) ? data : []) as TopLeadRow[];

  // Join com leads (nome/telefone) continua na rota, como hoje.
  let leadInfos: LeadInfo[] = [];
  if (rows.length > 0) {
    const leadIds = rows.map((r) => r.lead_id);
    const { data: leadInfo } = await sb.from("leads").select("id, name, phone").in("id", leadIds);
    leadInfos = (leadInfo || []) as LeadInfo[];
  }

  return NextResponse.json({ data: mapTopLeads(rows, leadInfos) });
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
