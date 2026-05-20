import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

type Params = { params: Promise<{ id: string; nodeId: string }> };

export async function PATCH(request: NextRequest, { params }: Params) {
  const { nodeId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase.from("campaign_nodes").update(body).eq("id", nodeId).select().single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const { nodeId } = await params;
  const supabase = await getServiceSupabase();
  await supabase.from("campaign_nodes").delete().eq("id", nodeId);
  return NextResponse.json({ ok: true });
}
