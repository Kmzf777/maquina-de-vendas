import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapKpis, type KpisRow } from "@/lib/dashboard-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start") || defaultStart();
  const endDate = sp.get("end") || defaultEnd();

  const sb = await getServiceSupabase();
  const { data, error } = await sb.rpc("dashboard_kpis", { p_start: startDate, p_end: endDate });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const row = (Array.isArray(data) ? data[0] : data) as KpisRow | undefined;
  return NextResponse.json(mapKpis(row));
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
