import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Step 1: pending lead_ids in this broadcast (simple query, no joins)
  const { data: pendingRows, error: plErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id")
    .eq("broadcast_id", id)
    .eq("status", "pending");

  if (plErr) {
    return NextResponse.json({ error: plErr.message }, { status: 500 });
  }
  if (!pendingRows?.length) {
    return NextResponse.json({ conflicts: [] });
  }

  const pendingLeadIds = pendingRows.map((r: { lead_id: string }) => r.lead_id);

  // Step 2: get phone numbers for these leads
  const { data: pendingLeadData, error: pldErr } = await supabase
    .from("leads")
    .select("id, phone, name")
    .in("id", pendingLeadIds);

  if (pldErr) {
    return NextResponse.json({ error: pldErr.message }, { status: 500 });
  }

  const phones = [
    ...new Set(
      (pendingLeadData ?? [])
        .map((l: { id: string; phone: string; name: string | null }) => l.phone)
        .filter(Boolean)
    ),
  ] as string[];

  if (!phones.length) {
    return NextResponse.json({ conflicts: [] });
  }

  // Step 3: find ALL lead_ids that share these phones (handles duplicate lead records)
  const { data: leadsWithPhones, error: lwErr } = await supabase
    .from("leads")
    .select("id, phone, name")
    .in("phone", phones);

  if (lwErr) {
    return NextResponse.json({ error: lwErr.message }, { status: 500 });
  }

  type LeadRow = { id: string; phone: string; name: string | null };
  const allLeadIds = (leadsWithPhones ?? []).map((l: LeadRow) => l.id);
  const phoneByLeadId: Record<string, string> = {};
  const nameByPhone: Record<string, string | null> = {};
  for (const l of (leadsWithPhones ?? []) as LeadRow[]) {
    phoneByLeadId[l.id] = l.phone;
    if (!(l.phone in nameByPhone)) nameByPhone[l.phone] = l.name;
  }

  // Build map: phone → pending lead_id (for the conflict result)
  const phoneToLeadId: Record<string, string> = {};
  for (const l of (pendingLeadData ?? []) as LeadRow[]) {
    if (l.phone && !(l.phone in phoneToLeadId)) {
      phoneToLeadId[l.phone] = l.id;
    }
  }

  const cutoffMs = Date.now() - 48 * 60 * 60 * 1000;

  // Step 4: recent sends in OTHER broadcasts for any of these lead_ids (no joins)
  const { data: recentSends, error: rsErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id, broadcast_id, sent_at, created_at")
    .in("lead_id", allLeadIds)
    .neq("broadcast_id", id)
    .in("status", ["sent", "delivered"])
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (rsErr) {
    return NextResponse.json({ error: rsErr.message }, { status: 500 });
  }

  // Filter by 48h window in JS
  type BlRow = { lead_id: string; broadcast_id: string; sent_at: string | null; created_at: string | null };
  const withinWindow = (recentSends ?? []).filter((row: BlRow) => {
    const ts = row.sent_at ?? row.created_at;
    return ts ? new Date(ts).getTime() >= cutoffMs : false;
  });

  if (!withinWindow.length) {
    return NextResponse.json({ conflicts: [] });
  }

  // Step 5: fetch broadcast names for display (separate query)
  const conflictBroadcastIds = [...new Set(withinWindow.map((r: BlRow) => r.broadcast_id))];
  const { data: broadcastNames } = await supabase
    .from("broadcasts")
    .select("id, name")
    .in("id", conflictBroadcastIds);

  const broadcastNameById: Record<string, string> = {};
  for (const b of (broadcastNames ?? []) as { id: string; name: string }[]) {
    broadcastNameById[b.id] = b.name;
  }

  // Deduplicate by phone — one conflict entry per phone
  const seenPhones = new Set<string>();
  const conflicts = [];
  for (const row of withinWindow as BlRow[]) {
    const phone = phoneByLeadId[row.lead_id];
    if (!phone || seenPhones.has(phone)) continue;
    seenPhones.add(phone);

    conflicts.push({
      lead_id: phoneToLeadId[phone] ?? row.lead_id,
      lead_name: nameByPhone[phone] ?? null,
      lead_phone: phone,
      last_broadcast_id: row.broadcast_id,
      last_broadcast_name: broadcastNameById[row.broadcast_id] ?? "—",
      last_sent_at: row.sent_at ?? row.created_at ?? "",
    });
  }

  return NextResponse.json({ conflicts });
}
