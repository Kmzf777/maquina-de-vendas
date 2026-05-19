import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Step 1: pending leads in this broadcast
  const { data: pendingLeads, error: plErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id")
    .eq("broadcast_id", id)
    .eq("status", "pending");

  if (plErr) {
    console.error("[spam-check] Step1 error:", plErr.message);
    return NextResponse.json({ error: plErr.message }, { status: 500 });
  }

  console.log(`[spam-check] broadcast=${id} pendingLeads=${pendingLeads?.length ?? 0}`);

  if (!pendingLeads || pendingLeads.length === 0) {
    return NextResponse.json({ conflicts: [] });
  }

  const leadIds = pendingLeads.map((r: { lead_id: string }) => r.lead_id);
  console.log("[spam-check] leadIds:", leadIds);

  const cutoffMs = Date.now() - 48 * 60 * 60 * 1000;
  const cutoff = new Date(cutoffMs).toISOString();
  console.log("[spam-check] cutoff:", cutoff);

  // Step 2: OTHER broadcast_leads for these leads with status sent/delivered.
  // We fetch without a time filter in the DB (avoids PostgREST .or() edge cases
  // with NULL sent_at) and apply the 48h window in JS using sent_at ?? created_at.
  const { data: recentSends, error: rsErr } = await supabase
    .from("broadcast_leads")
    .select(`
      lead_id,
      broadcast_id,
      sent_at,
      created_at,
      leads!inner(name, phone),
      broadcasts(name)
    `)
    .in("lead_id", leadIds)
    .neq("broadcast_id", id)
    .in("status", ["sent", "delivered"])
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (rsErr) {
    console.error("[spam-check] Step2 error:", rsErr.message);
    return NextResponse.json({ error: rsErr.message }, { status: 500 });
  }

  console.log(`[spam-check] recentSends (pre-filter) count=${recentSends?.length ?? 0}`, recentSends);

  // Apply 48h window in JavaScript: sent_at takes priority, fall back to created_at
  const withinWindow = (recentSends ?? []).filter((row) => {
    const ts = row.sent_at ?? row.created_at;
    return ts ? new Date(ts).getTime() >= cutoffMs : false;
  });

  console.log(`[spam-check] withinWindow count=${withinWindow.length}`);

  // Deduplicate: keep the most recent conflict per lead_id
  const seen = new Set<string>();
  const conflicts = [];
  for (const row of withinWindow) {
    if (seen.has(row.lead_id)) continue;
    seen.add(row.lead_id);

    const lead = (row.leads as unknown) as { name: string | null; phone: string } | null;
    const broadcast = (row.broadcasts as unknown) as { name: string } | null;

    conflicts.push({
      lead_id: row.lead_id,
      lead_name: lead?.name ?? null,
      lead_phone: lead?.phone ?? "",
      last_broadcast_id: row.broadcast_id,
      last_broadcast_name: broadcast?.name ?? "—",
      last_sent_at: row.sent_at ?? row.created_at ?? "",
    });
  }

  console.log(`[spam-check] conflicts=${conflicts.length}`);

  return NextResponse.json({ conflicts });
}
