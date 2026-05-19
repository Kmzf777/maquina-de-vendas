import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Fetch pending leads in this broadcast
  const { data: pendingLeads, error: plErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id")
    .eq("broadcast_id", id)
    .eq("status", "pending");

  if (plErr) {
    return NextResponse.json({ error: plErr.message }, { status: 500 });
  }

  if (!pendingLeads || pendingLeads.length === 0) {
    return NextResponse.json({ conflicts: [] });
  }

  const leadIds = pendingLeads.map((r: { lead_id: string }) => r.lead_id);

  // Fetch all sent/delivered broadcast_leads for these leads in OTHER broadcasts.
  // We do time-filtering in JS using sent_at ?? broadcast.created_at as fallback,
  // so that leads whose sent_at is NULL (broadcasts before the sent_at column was
  // populated) are still caught.
  const { data: recentSends, error: rsErr } = await supabase
    .from("broadcast_leads")
    .select(`
      lead_id,
      broadcast_id,
      sent_at,
      leads!inner(name, phone),
      broadcasts!inner(name, created_at)
    `)
    .in("lead_id", leadIds)
    .neq("broadcast_id", id)
    .in("status", ["sent", "delivered"])
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (rsErr) {
    return NextResponse.json({ error: rsErr.message }, { status: 500 });
  }

  const cutoffMs = Date.now() - 48 * 60 * 60 * 1000;

  // Deduplicate: keep most recent conflict per lead_id
  const seen = new Set<string>();
  const conflicts = [];
  for (const row of (recentSends ?? [])) {
    const broadcastData = (row.broadcasts as unknown) as { name: string; created_at: string } | null;
    // Use sent_at if set; fall back to broadcast created_at for older rows
    const effectiveTime = row.sent_at ?? broadcastData?.created_at;
    if (!effectiveTime) continue;
    if (new Date(effectiveTime).getTime() < cutoffMs) continue; // outside 48h window

    if (seen.has(row.lead_id)) continue;
    seen.add(row.lead_id);

    const lead = (row.leads as unknown) as { name: string | null; phone: string } | null;
    conflicts.push({
      lead_id: row.lead_id,
      lead_name: lead?.name ?? null,
      lead_phone: lead?.phone ?? "",
      last_broadcast_id: row.broadcast_id,
      last_broadcast_name: broadcastData?.name ?? "—",
      last_sent_at: row.sent_at ?? broadcastData?.created_at ?? "",
    });
  }

  return NextResponse.json({ conflicts });
}
