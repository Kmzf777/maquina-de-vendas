import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("broadcast_leads")
    .select("*, leads(id, name, phone, company)")
    .eq("broadcast_id", id)
    .order("sent_at", { ascending: false, nullsFirst: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const leadIds: string[] = body.lead_ids || [];
  let assigned = 0;

  for (const leadId of leadIds) {
    const { error } = await supabase
      .from("broadcast_leads")
      .insert({ broadcast_id: id, lead_id: leadId });
    if (!error) assigned++;
  }

  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id);

  await supabase
    .from("broadcasts")
    .update({ total_leads: count || 0 })
    .eq("id", id);

  return NextResponse.json({ assigned });
}
