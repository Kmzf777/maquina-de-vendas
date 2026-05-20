import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const supabase = await getServiceSupabase();

  let periodQuery = supabase.from("sales").select("value");
  if (from) periodQuery = periodQuery.gte("sold_at", from);
  if (to) periodQuery = periodQuery.lte("sold_at", to);

  const { data: periodSales, error } = await periodQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const total_value = periodSales.reduce((sum, s) => sum + Number(s.value), 0);
  const count = periodSales.length;
  const avg_value = count > 0 ? total_value / count : 0;

  const { data: allSales } = await supabase
    .from("sales")
    .select("lead_id, sold_at")
    .order("sold_at", { ascending: true });

  let avg_repurchase_cycle_days: number | null = null;
  if (allSales && allSales.length > 1) {
    const byLead: Record<string, string[]> = {};
    for (const s of allSales) {
      if (!byLead[s.lead_id]) byLead[s.lead_id] = [];
      byLead[s.lead_id].push(s.sold_at);
    }
    const intervals: number[] = [];
    for (const dates of Object.values(byLead)) {
      for (let i = 1; i < dates.length; i++) {
        const days =
          (new Date(dates[i]).getTime() - new Date(dates[i - 1]).getTime()) /
          (1000 * 60 * 60 * 24);
        intervals.push(days);
      }
    }
    if (intervals.length > 0) {
      avg_repurchase_cycle_days = Math.round(
        intervals.reduce((a, b) => a + b, 0) / intervals.length
      );
    }
  }

  return NextResponse.json({ total_value, count, avg_value, avg_repurchase_cycle_days });
}
