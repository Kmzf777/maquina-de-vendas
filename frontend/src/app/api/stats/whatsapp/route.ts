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

  let marketingCount = 0;
  let utilityCount = 0;
  for (const row of safeRows) {
    const name = (row.payload as any)?.template?.name;
    const category = categoryMap[name] ?? "MARKETING";
    if (category === "UTILITY") utilityCount++;
    else marketingCount++;
  }

  return NextResponse.json({
    marketing_count: marketingCount,
    marketing_cost: Math.round(marketingCount * MARKETING_PRICE * 1e4) / 1e4,
    utility_count: utilityCount,
    utility_cost: Math.round(utilityCount * UTILITY_PRICE * 1e4) / 1e4,
    total_whatsapp_cost:
      Math.round((marketingCount * MARKETING_PRICE + utilityCount * UTILITY_PRICE) * 1e4) / 1e4,
    truncated,
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
