import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: broadcast } = await supabase
    .from("broadcasts")
    .select("status")
    .eq("id", id)
    .single();

  if (broadcast?.status === "running") {
    return NextResponse.json({ error: "Disparo ja esta rodando" }, { status: 400 });
  }

  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id)
    .eq("status", "pending");

  if (!count) {
    return NextResponse.json({ error: "Nenhum lead pendente" }, { status: 400 });
  }

  await supabase
    .from("broadcasts")
    .update({ status: "running" })
    .eq("id", id);

  return NextResponse.json({ status: "started", leads_queued: count });
}
