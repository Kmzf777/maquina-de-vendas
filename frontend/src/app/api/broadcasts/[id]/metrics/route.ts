import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase.rpc("get_broadcast_reply_metrics", {
    p_broadcast_id: id,
  });

  if (error) {
    console.error("[broadcast-metrics] RPC error:", error.message);
    return NextResponse.json(
      { replied_count: 0, reply_rate: 0, avg_reply_secs: null, median_reply_secs: null },
      { status: 200 }
    );
  }

  const row = Array.isArray(data) ? data[0] : data;
  return NextResponse.json({
    replied_count: Number(row?.replied_count ?? 0),
    reply_rate: Number(row?.reply_rate ?? 0),
    avg_reply_secs: row?.avg_reply_secs != null ? Number(row.avg_reply_secs) : null,
    median_reply_secs: row?.median_reply_secs != null ? Number(row.median_reply_secs) : null,
  });
}
