import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const groupBy = sp.get("group_by") || "stage";

  const sb = await getServiceSupabase();

  const { data: rows, error } = await sb
    .from("token_usage")
    .select("total_cost, prompt_tokens, completion_tokens, stage, model, lead_id")
    .gte("created_at", startDate)
    .lt("created_at", endDate)
    .limit(10000);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const groups: Record<string, { key: string; cost: number; calls: number; tokens: number }> = {};
  for (const row of rows || []) {
    const key = groupBy === "lead" ? (row.lead_id || "unknown") : row[groupBy as "stage" | "model"];
    if (!groups[key]) groups[key] = { key, cost: 0, calls: 0, tokens: 0 };
    groups[key].cost += Number(row.total_cost);
    groups[key].calls += 1;
    groups[key].tokens += row.prompt_tokens + row.completion_tokens;
  }

  const data = Object.values(groups)
    .sort((a, b) => b.cost - a.cost)
    .map((item) => ({ ...item, cost: Math.round(item.cost * 1e6) / 1e6 }));

  return NextResponse.json({ data });
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
