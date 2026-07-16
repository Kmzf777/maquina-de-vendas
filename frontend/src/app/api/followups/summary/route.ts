import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

/** Início do dia atual em BRT (UTC-3 fixo — mesmo pragmatismo do _FOLLOWUP_TZ_BR do motor). */
function todayStartBRTAsUTC(): string {
  const now = new Date();
  const brtNow = new Date(now.getTime() - 3 * 3600_000);
  const dayStartBRT = Date.UTC(
    brtNow.getUTCFullYear(), brtNow.getUTCMonth(), brtNow.getUTCDate(), 0, 0, 0,
  );
  return new Date(dayStartBRT + 3 * 3600_000).toISOString();
}

async function countJobs(
  supabase: Awaited<ReturnType<typeof getServiceSupabase>>,
  status: string,
  sentSince?: string,
): Promise<number> {
  let q = supabase
    .from("follow_up_jobs")
    .select("id", { count: "exact", head: true })
    .eq("env_tag", APP_ENV)
    .eq("status", status);
  if (sentSince) q = q.gte("sent_at", sentSince);
  const { count, error } = await q;
  if (error) throw new Error(error.message);
  return count ?? 0;
}

export async function GET() {
  const supabase = await getServiceSupabase();
  try {
    const todayStart = todayStartBRTAsUTC();
    const [pending, awaitingReopen, sentToday, sentWeek] = await Promise.all([
      countJobs(supabase, "pending"),
      countJobs(supabase, "awaiting_reopen"),
      countJobs(supabase, "sent", todayStart),
      countJobs(
        supabase,
        "sent",
        new Date(Date.now() - 7 * 24 * 3600_000).toISOString(),
      ),
    ]);
    return NextResponse.json({
      pending,
      awaiting_reopen: awaitingReopen,
      sent_today: sentToday,
      sent_week: sentWeek,
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
