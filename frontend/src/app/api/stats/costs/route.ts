import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const stage = sp.get("stage");
  const model = sp.get("model");
  const leadId = sp.get("lead_id");

  const sb = await getServiceSupabase();

  let query = sb
    .from("token_usage")
    .select("total_cost, prompt_tokens, completion_tokens, lead_id")
    .gte("created_at", startDate)
    .lt("created_at", endDate)
    .limit(10000);

  if (stage) query = query.eq("stage", stage);
  if (model) query = query.eq("model", model);
  if (leadId) query = query.eq("lead_id", leadId);

  const { data: rows, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const safeRows = rows || [];
  const totalCost = safeRows.reduce((s, r) => s + Number(r.total_cost), 0);
  const totalCalls = safeRows.length;
  const totalPrompt = safeRows.reduce((s, r) => s + r.prompt_tokens, 0);
  const totalCompletion = safeRows.reduce((s, r) => s + r.completion_tokens, 0);
  const uniqueLeads = new Set(safeRows.map((r) => r.lead_id).filter(Boolean)).size;
  const avgCostPerLead = uniqueLeads > 0 ? totalCost / uniqueLeads : 0;

  return NextResponse.json({
    total_cost: Math.round(totalCost * 1e6) / 1e6,
    total_calls: totalCalls,
    total_prompt_tokens: totalPrompt,
    total_completion_tokens: totalCompletion,
    total_tokens: totalPrompt + totalCompletion,
    unique_leads: uniqueLeads,
    avg_cost_per_lead: Math.round(avgCostPerLead * 1e6) / 1e6,
  });
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
