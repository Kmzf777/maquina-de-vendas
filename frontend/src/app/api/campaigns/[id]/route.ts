import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: campaign, error } = await supabase.from("campaigns").select("*").eq("id", id).single();
  if (error) return NextResponse.json({ error: error.message }, { status: 404 });
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  return NextResponse.json({ ...campaign, nodes: nodes ?? [] });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: camp } = await supabase.from("campaigns").select("status").eq("id", id).single();
  if (camp && !["draft", "archived"].includes(camp.status)) {
    return NextResponse.json({ error: "Apenas drafts e arquivadas podem ser excluídas" }, { status: 400 });
  }
  await supabase.from("campaigns").delete().eq("id", id);
  return NextResponse.json({ ok: true });
}
