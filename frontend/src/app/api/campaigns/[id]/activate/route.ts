import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  const trigger = nodes?.find((n) => n.type === "trigger");
  if (!trigger?.next_node_id) {
    return NextResponse.json({ error: "Configure o fluxo antes de ativar" }, { status: 400 });
  }
  await supabase.from("campaigns").update({ status: "active", updated_at: new Date().toISOString() }).eq("id", id);
  return NextResponse.json({ status: "active" });
}
