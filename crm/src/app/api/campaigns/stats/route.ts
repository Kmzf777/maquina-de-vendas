import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const period = request.nextUrl.searchParams.get("period") || "30d";

  const daysMap: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90 };
  const days = daysMap[period] || 30;
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  const [broadcasts, cadences, enrollments, recentMessages] = await Promise.all([
    supabase.from("broadcasts").select("id, status").in("status", ["running", "scheduled"]),
    supabase.from("cadences").select("id, status").eq("status", "active"),
    supabase.from("cadence_enrollments").select("id, status, responded_at, enrolled_at"),
    supabase
      .from("messages")
      .select("created_at")
      .eq("sent_by", "cadence")
      .gte("created_at", since)
      .order("created_at"),
  ]);

  const allEnrollments = enrollments.data || [];
  const activeCount = allEnrollments.filter((e) => e.status === "active").length;
  const respondedCount = allEnrollments.filter((e) => e.status === "responded").length;
  const exhaustedCount = allEnrollments.filter((e) => e.status === "exhausted").length;
  const completedCount = allEnrollments.filter((e) => e.status === "completed").length;
  const totalFinished = respondedCount + exhaustedCount + completedCount;
  const responseRate = totalFinished > 0 ? Math.round((respondedCount / totalFinished) * 100) : 0;

  // Build daily trend data
  const msgs = recentMessages.data || [];
  const dailyMap: Record<string, { sent: number; responded: number }> = {};

  for (const m of msgs) {
    const day = m.created_at.slice(0, 10);
    if (!dailyMap[day]) dailyMap[day] = { sent: 0, responded: 0 };
    dailyMap[day].sent++;
  }

  for (const e of allEnrollments) {
    if (e.responded_at) {
      const day = e.responded_at.slice(0, 10);
      if (day >= since.slice(0, 10)) {
        if (!dailyMap[day]) dailyMap[day] = { sent: 0, responded: 0 };
        dailyMap[day].responded++;
      }
    }
  }

  const trend = Object.entries(dailyMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, data]) => ({ date, ...data }));

  return NextResponse.json({
    activeBroadcasts: (broadcasts.data || []).length,
    activeCadences: (cadences.data || []).length,
    leadsInFollowUp: activeCount,
    responseRate,
    respondedCount,
    trend,
  });
}
