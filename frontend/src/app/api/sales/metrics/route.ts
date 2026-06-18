import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const supabase = await getServiceSupabase();

  let periodQuery = supabase.from("sales").select("value");
  if (from) periodQuery = periodQuery.gte("sold_at", from.length === 10 ? `${from}T00:00:00.000Z` : from);
  if (to) periodQuery = periodQuery.lte("sold_at", to.length === 10 ? `${to}T23:59:59.999Z` : to);

  const { data: periodSales, error } = await periodQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const total_value = periodSales.reduce((sum, s) => sum + Number(s.value), 0);
  const count = periodSales.length;
  const avg_value = count > 0 ? total_value / count : 0;

  // Recompra agregada no banco via RPC (não carrega a tabela inteira no Node).
  const { data: rpcValue } = await supabase.rpc("get_avg_repurchase_cycle_days");
  const avg_repurchase_cycle_days: number | null = rpcValue == null ? null : Number(rpcValue);

  return NextResponse.json({ total_value, count, avg_value, avg_repurchase_cycle_days });
}
