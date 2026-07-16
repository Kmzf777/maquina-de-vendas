import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { fillWhatsappDaily, type WhatsappDailyRow } from "@/lib/stats-mappers";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const startDate = sp.get("start_date") || defaultStart();
  const endDate = sp.get("end_date") || defaultEnd();

  const sb = await getServiceSupabase();

  const { data, error } = await sb.rpc("stats_whatsapp_daily", {
    p_start: startDate,
    p_end: endDate,
  });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const rows = (Array.isArray(data) ? data : []) as WhatsappDailyRow[];
  // Gap-fill + preços continuam na rota; agregação no servidor não trunca.
  return NextResponse.json({ data: fillWhatsappDaily(rows, startDate, endDate), truncated: false });
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
