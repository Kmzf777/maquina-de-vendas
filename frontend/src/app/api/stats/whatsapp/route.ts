import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { mapWhatsappSummary, type WhatsappSummaryRow } from "@/lib/stats-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();

  const sb = await getServiceSupabase();

  const { data, error } = await sb.rpc("stats_whatsapp_summary", {
    p_start: startDate,
    p_end: endDate,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const row = (Array.isArray(data) ? data[0] : data) as WhatsappSummaryRow | undefined;
  return NextResponse.json(mapWhatsappSummary(row));
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
