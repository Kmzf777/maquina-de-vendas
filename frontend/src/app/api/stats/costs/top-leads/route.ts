import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const limit = Math.min(Number(sp.get("limit") || 20), 100);

  const sb = await getServiceSupabase();

  const { data: rows, error } = await sb
    .from("token_usage")
    .select("total_cost, prompt_tokens, completion_tokens, lead_id, stage")
    .gte("created_at", startDate)
    .lt("created_at", endDate)
    .limit(10000);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const leadsData: Record<string, { lead_id: string; cost: number; calls: number; tokens: number; stage: string }> = {};
  for (const row of rows || []) {
    if (!row.lead_id) continue;
    if (!leadsData[row.lead_id]) {
      leadsData[row.lead_id] = { lead_id: row.lead_id, cost: 0, calls: 0, tokens: 0, stage: row.stage };
    }
    leadsData[row.lead_id].cost += Number(row.total_cost);
    leadsData[row.lead_id].calls += 1;
    leadsData[row.lead_id].tokens += row.prompt_tokens + row.completion_tokens;
    leadsData[row.lead_id].stage = row.stage;
  }

  const sortedLeads = Object.values(leadsData)
    .sort((a, b) => b.cost - a.cost)
    .slice(0, limit);

  // Fetch lead names
  if (sortedLeads.length > 0) {
    const leadIds = sortedLeads.map((l) => l.lead_id);
    const { data: leadInfo } = await sb.from("leads").select("id, name, phone").in("id", leadIds);
    const leadMap = Object.fromEntries((leadInfo || []).map((l) => [l.id, l]));

    for (const item of sortedLeads) {
      const info = leadMap[item.lead_id] || {};
      (item as Record<string, unknown>).name = info.name || info.phone || "Desconhecido";
      (item as Record<string, unknown>).phone = info.phone || "";
      item.cost = Math.round(item.cost * 1e6) / 1e6;
    }
  }

  return NextResponse.json({ data: sortedLeads });
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
