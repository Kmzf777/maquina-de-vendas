import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapOutbound, type OutboundRow } from "@/lib/dashboard-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start") || defaultStart();
  const endDate = sp.get("end") || defaultEnd();

  const sb = await getServiceSupabase();
  const { data, error } = await sb.rpc("dashboard_outbound_frio", { p_start: startDate, p_end: endDate });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const row = (Array.isArray(data) ? data[0] : data) as OutboundRow | undefined;
  return NextResponse.json(mapOutbound(row));
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
