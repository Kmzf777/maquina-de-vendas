import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();
  const stage = sp.get("stage");
  const model = sp.get("model");

  const sb = await getServiceSupabase();

  let query = sb
    .from("token_usage")
    .select("total_cost, created_at")
    .gte("created_at", startDate)
    .lt("created_at", endDate)
    .limit(10000);

  if (stage) query = query.eq("stage", stage);
  if (model) query = query.eq("model", model);

  const { data: rows, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const daily: Record<string, number> = {};
  for (const row of rows || []) {
    const day = row.created_at.slice(0, 10);
    daily[day] = (daily[day] || 0) + Number(row.total_cost);
  }

  // Fill gaps
  const data: { date: string; cost: number }[] = [];
  const current = new Date(startDate + "T00:00:00");
  const end = new Date(endDate + "T00:00:00");
  while (current < end) {
    const dayStr = current.toISOString().slice(0, 10);
    data.push({ date: dayStr, cost: Math.round((daily[dayStr] || 0) * 1e6) / 1e6 });
    current.setDate(current.getDate() + 1);
  }

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
