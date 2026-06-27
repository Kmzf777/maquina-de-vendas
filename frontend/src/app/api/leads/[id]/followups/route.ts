import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("follow_up_jobs")
    .select("sequence, job_type, status, fire_at, sent_at, cancel_reason, metadata")
    .eq("lead_id", id)
    .order("fire_at", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = (data ?? []).map((j) => {
    const md = (j.metadata ?? {}) as Record<string, unknown>;
    return {
      sequence: j.sequence,
      job_type: j.job_type,
      status: j.status,
      fire_at: j.fire_at,
      sent_at: j.sent_at,
      cancel_reason: j.cancel_reason,
      objetivo: (md.objetivo as string | undefined) ?? null,
    };
  });

  return NextResponse.json(rows);
}
