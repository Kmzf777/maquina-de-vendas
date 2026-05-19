import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Step 1: pending leads in this broadcast + their phone numbers
  const { data: pendingLeads, error: plErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id, leads!inner(id, phone, name)")
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

  // Extract unique phones and build a map phone → pending lead info
  type LeadInfo = { id: string; phone: string; name: string | null };

  const phoneToLeadId: Record<string, string> = {};
  const phones: string[] = [];
  for (const row of pendingLeads) {
    const lead = row.leads as unknown as LeadInfo;
    if (!lead?.phone) continue;
    if (!phoneToLeadId[lead.phone]) {
      phoneToLeadId[lead.phone] = row.lead_id;
      phones.push(lead.phone);
    }
  }

  console.log("[spam-check] phones:", phones);

  if (phones.length === 0) {
    return NextResponse.json({ conflicts: [] });
  }

  // Step 2: find ALL lead_ids that share these phone numbers (handles duplicate leads)
  const { data: leadsWithPhones, error: lwErr } = await supabase
    .from("leads")
    .select("id, phone, name")
    .in("phone", phones);

  if (lwErr) {
    console.error("[spam-check] Step2 error:", lwErr.message);
    return NextResponse.json({ error: lwErr.message }, { status: 500 });
  }

  const allLeadIds = (leadsWithPhones ?? []).map((l: { id: string }) => l.id);
  const phoneByLeadId: Record<string, string> = {};
  const nameByPhone: Record<string, string | null> = {};
  for (const l of (leadsWithPhones ?? []) as { id: string; phone: string; name: string | null }[]) {
    phoneByLeadId[l.id] = l.phone;
    if (!nameByPhone[l.phone]) nameByPhone[l.phone] = l.name;
  }

  console.log("[spam-check] allLeadIds:", allLeadIds);

  // Step 3: find recent sends to any of these lead_ids in OTHER broadcasts
  const cutoffMs = Date.now() - 48 * 60 * 60 * 1000;
  const { data: recentSends, error: rsErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id, broadcast_id, sent_at, created_at, broadcasts(name)")
    .in("lead_id", allLeadIds)
    .neq("broadcast_id", id)
    .in("status", ["sent", "delivered"])
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (rsErr) {
    console.error("[spam-check] Step3 error:", rsErr.message);
    return NextResponse.json({ error: rsErr.message }, { status: 500 });
  }

  console.log(`[spam-check] recentSends (pre-filter) count=${recentSends?.length ?? 0}`, recentSends);

  // Filter by 48h window in JS — avoids PostgREST .or() edge cases with NULL sent_at
  const withinWindow = (recentSends ?? []).filter((row) => {
    const ts = row.sent_at ?? row.created_at;
    return ts ? new Date(ts).getTime() >= cutoffMs : false;
  });

  console.log(`[spam-check] withinWindow count=${withinWindow.length}`);

  // Deduplicate by phone — one conflict entry per phone number
  const seenPhones = new Set<string>();
  const conflicts = [];

  for (const row of withinWindow) {
    const phone = phoneByLeadId[row.lead_id];
    if (!phone || seenPhones.has(phone)) continue;
    seenPhones.add(phone);

    const broadcast = (row.broadcasts as unknown) as { name: string } | null;
    // Use the lead_id from the PENDING broadcast (current) for display
    const pendingLeadId = phoneToLeadId[phone] ?? row.lead_id;

    conflicts.push({
      lead_id: pendingLeadId,
      lead_name: nameByPhone[phone] ?? null,
      lead_phone: phone,
      last_broadcast_id: row.broadcast_id,
      last_broadcast_name: broadcast?.name ?? "—",
      last_sent_at: row.sent_at ?? row.created_at ?? "",
    });
  }

  console.log(`[spam-check] conflicts=${conflicts.length}`);

  return NextResponse.json({ conflicts });
}
