import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

const MARKETING_PRICE = 0.0617;
const UTILITY_PRICE = 0.0067;

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();

  const sb = await getServiceSupabase();

  const { data: rows, error } = await sb
    .from("meta_webhook_logs")
    .select("payload, received_at")
    .eq("direction", "outbound")
    .eq("request_type", "send_template")
    .eq("success", true)
    .gte("received_at", startDate)
    .lt("received_at", endDate)
    .limit(10000);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const safeRows = rows || [];
  const truncated = safeRows.length === 10000;

  const templateNames = new Set<string>();
  for (const row of safeRows) {
    const name = (row.payload as any)?.template?.name;
    if (name) templateNames.add(name as string);
  }

  const categoryMap: Record<string, string> = {};
  if (templateNames.size > 0) {
    const { data: tplData } = await sb
      .from("message_templates")
      .select("name, category")
      .in("name", Array.from(templateNames));
    for (const t of tplData || []) {
      categoryMap[t.name] = (t.category as string).trim().toUpperCase();
    }
  }

  const daily: Record<string, { marketingCost: number; utilityCost: number }> = {};
  for (const row of safeRows) {
    const day = (row.received_at as string).slice(0, 10);
    const name = (row.payload as any)?.template?.name;
    const category = categoryMap[name] ?? "MARKETING";
    if (!daily[day]) daily[day] = { marketingCost: 0, utilityCost: 0 };
    if (category === "UTILITY") daily[day].utilityCost += UTILITY_PRICE;
    else daily[day].marketingCost += MARKETING_PRICE;
  }

  const data: { date: string; marketing_cost: number; utility_cost: number; total: number }[] = [];
  const current = new Date(startDate + "T00:00:00");
  const end = new Date(endDate + "T00:00:00");
  while (current < end) {
    const dayStr = current.toISOString().slice(0, 10);
    const d = daily[dayStr] ?? { marketingCost: 0, utilityCost: 0 };
    data.push({
      date: dayStr,
      marketing_cost: Math.round(d.marketingCost * 1e4) / 1e4,
      utility_cost: Math.round(d.utilityCost * 1e4) / 1e4,
      total: Math.round((d.marketingCost + d.utilityCost) * 1e4) / 1e4,
    });
    current.setDate(current.getDate() + 1);
  }

  return NextResponse.json({ data, truncated });
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
