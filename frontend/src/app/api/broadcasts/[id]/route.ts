import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { createClient as createServerClient } from "@/lib/supabase/server";

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

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const allowedChannelIds = await getAllowedChannelIds(supabase);

  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  let dbQuery = supabase
    .from("broadcasts")
    .select("*, move_to_stage:pipeline_stages!move_to_stage_id(id, label, pipeline_id, pipelines(name))")
    .eq("id", id);

  if (allowedChannelIds !== null) {
    dbQuery = dbQuery.in("channel_id", allowedChannelIds);
  }

  const { data, error } = await dbQuery.single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const allowedChannelIds = await getAllowedChannelIds(supabase);

  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  let dbQuery = supabase
    .from("broadcasts")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id);

  if (allowedChannelIds !== null) {
    dbQuery = dbQuery.in("channel_id", allowedChannelIds);
  }

  const { data, error } = await dbQuery.select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const allowedChannelIds = await getAllowedChannelIds(supabase);

  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  let dbQuery = supabase.from("broadcasts").delete().eq("id", id);

  if (allowedChannelIds !== null) {
    dbQuery = dbQuery.in("channel_id", allowedChannelIds);
  }

  const { error } = await dbQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
