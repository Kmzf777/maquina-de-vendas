import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { createClient as createServerClient } from "@/lib/supabase/server";
import { APP_ENV } from "@/lib/env";

async function getAllowedChannelIds(supabase: Awaited<ReturnType<typeof getServiceSupabase>>): Promise<string[] | null> {
  try {
    const userClient = await createServerClient();
    const { data: { user } } = await userClient.auth.getUser();
    const role = user?.app_metadata?.role as string | undefined;
    if (user && role !== "admin") {
      const { data: ownedChannels } = await supabase
        .from("channels")
        .select("id")
        .eq("owner_user_id", user.id);
      return (ownedChannels || []).map((c: { id: string }) => c.id);
    }
    return null;
  } catch {
    return [];
  }
}

export async function GET() {
  const supabase = await getServiceSupabase();
  const allowedChannelIds = await getAllowedChannelIds(supabase);

  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    return NextResponse.json([]);
  }

  let dbQuery = supabase
    .from("broadcasts")
    .select("*")
    .eq("env_tag", APP_ENV)
    .order("created_at", { ascending: false });

  if (allowedChannelIds !== null) {
    dbQuery = dbQuery.in("channel_id", allowedChannelIds);
  }

  const { data, error } = await dbQuery;

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const allowedChannelIds = await getAllowedChannelIds(supabase);

  let channelId = body.channel_id || null;
  if (allowedChannelIds !== null) {
    if (allowedChannelIds.length === 0) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }
    if (!channelId || !allowedChannelIds.includes(channelId)) {
      channelId = allowedChannelIds[0];
    }
  }

  const { data, error } = await supabase
    .from("broadcasts")
    .insert({
      name: body.name,
      channel_id: channelId,
      template_name: body.template_name,
      template_language_code: body.template_language_code || "pt_BR",
      template_preset_id: body.template_preset_id || null,
      template_variables: body.template_variables || {},
      send_interval_min: body.send_interval_min || 3,
      send_interval_max: body.send_interval_max || 8,
      cadence_id: body.cadence_id || null,
      agent_profile_id: body.agent_profile_id || null,
      move_to_stage_id: body.move_to_stage_id || null,
      scheduled_at: body.scheduled_at || null,
      status: body.scheduled_at ? "scheduled" : "draft",
      env_tag: APP_ENV,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
