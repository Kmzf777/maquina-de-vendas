import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");
  const status = searchParams.get("status");

  let query = supabase
    .from("conversations")
    .select("*, leads(id, phone, name, company), channels(id, name, phone, provider)");

  if (channelId) query = query.eq("channel_id", channelId);
  if (status) query = query.eq("status", status);

  const { data, error } = await query
    .order("last_msg_at", { ascending: false, nullsFirst: false })
    .limit(100);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
