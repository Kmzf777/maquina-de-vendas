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
    .select(`
      id,
      broadcast_id,
      status,
      sent_at,
      first_replied_at,
      broadcasts!inner(name, status)
    `)
    .eq("lead_id", id)
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const result = (data ?? []).map((row: Record<string, unknown>) => {
    const b = row.broadcasts as { name: string; status: string } | null;
    return {
      id: row.id,
      broadcast_id: row.broadcast_id,
      broadcast_name: b?.name ?? "—",
      broadcast_status: b?.status ?? "unknown",
      message_status: row.status,
      sent_at: row.sent_at,
      first_replied_at: row.first_replied_at,
    };
  });

  return NextResponse.json(result);
}
