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
    return NextResponse.json({ error: plErr.message }, { status: 500 });
  }

  if (!pendingLeads || pendingLeads.length === 0) {
    return NextResponse.json({ conflicts: [] });
  }

  const leadIds = pendingLeads.map((r: { lead_id: string }) => r.lead_id);

  // 48 h window — pushed to the DB so it filters on BOTH sent_at and created_at.
  // This handles broadcast_leads where sent_at is NULL (dispatched before the
  // sent_at column was populated) by falling back to the row's own created_at.
  const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();

  // Step 2: OTHER broadcast_leads for these leads sent within the last 48 h.
  // Use outer join for broadcasts (just for display name — don't let a broken
  // FK resolution kill the whole query the way !inner would).
  const { data: recentSends, error: rsErr } = await supabase
    .from("broadcast_leads")
    .select(`
      lead_id,
      broadcast_id,
      sent_at,
      leads!inner(name, phone),
      broadcasts(name)
    `)
    .in("lead_id", leadIds)
    .neq("broadcast_id", id)
    .in("status", ["sent", "delivered"])
    .or(`sent_at.gte.${cutoff},created_at.gte.${cutoff}`)
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (rsErr) {
    return NextResponse.json({ error: rsErr.message }, { status: 500 });
  }

  // Deduplicate: keep the most recent conflict per lead_id
  const seen = new Set<string>();
  const conflicts = [];
  for (const row of (recentSends ?? [])) {
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
      last_sent_at: row.sent_at ?? "",
    });
  }

  return NextResponse.json({ conflicts });
}
