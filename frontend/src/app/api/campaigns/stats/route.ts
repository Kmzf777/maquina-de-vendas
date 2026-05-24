import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const period = request.nextUrl.searchParams.get("period") || "30d";

  const daysMap: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90 };
  const days = daysMap[period] || 30;
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  const [broadcasts, activeCampaigns, enrollments, recentMessages, broadcastLeads] = await Promise.all([
    supabase
      .from("broadcasts")
      .select("id, status")
      .eq("env_tag", APP_ENV)
      .in("status", ["running", "scheduled"]),
    supabase
      .from("campaigns")
      .select("id, status")
      .eq("status", "active")
      .eq("env_tag", APP_ENV),
    supabase
      .from("campaign_enrollments")
      .select("id, status")
      .eq("env_tag", APP_ENV),
    supabase
      .from("messages")
      .select("created_at")
      .eq("sent_by", "cadence")
      .gte("created_at", since)
      .order("created_at"),
    supabase
      .from("broadcast_leads")
      .select("sent_at, first_replied_at")
      .gte("sent_at", since),
  ]);

  const allEnrollments = enrollments.data || [];
  const activeCount = allEnrollments.filter((e) => e.status === "active").length;

  const bLeads = broadcastLeads.data || [];
  const respondedCount = bLeads.filter((l) => l.first_replied_at !== null).length;
  const totalSent = bLeads.filter((l) => l.sent_at !== null).length;
  const responseRate = totalSent > 0 ? Math.round((respondedCount / totalSent) * 100) : 0;

  // Build daily trend data
  const msgs = recentMessages.data || [];
  const dailyMap: Record<string, { sent: number; responded: number }> = {};

  for (const m of msgs) {
    const day = m.created_at.slice(0, 10);
    if (!dailyMap[day]) dailyMap[day] = { sent: 0, responded: 0 };
    dailyMap[day].sent++;
  }

  for (const l of bLeads) {
    if (l.first_replied_at) {
      const day = l.first_replied_at.slice(0, 10);
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
    activeCadences: (activeCampaigns.data || []).length,
    leadsInFollowUp: activeCount,
    responseRate,
    respondedCount,
    trend,
  });
}
