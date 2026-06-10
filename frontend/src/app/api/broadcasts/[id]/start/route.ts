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

  const { count: pendingCount } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id)
    .eq("status", "pending");

  let leadsQueued = pendingCount ?? 0;

  // If broadcast is paused with no pending leads but has failed leads, reset them so the
  // resume acts as a retry — avoids "Nenhum lead pendente" error when user clicks Retomar.
  if (!leadsQueued && broadcast?.status === "paused") {
    const { count: failedCount } = await supabase
      .from("broadcast_leads")
      .select("id", { count: "exact", head: true })
      .eq("broadcast_id", id)
      .eq("status", "failed");

    if (failedCount) {
      await supabase
        .from("broadcast_leads")
        .update({ status: "pending", error_message: null })
        .eq("broadcast_id", id)
        .eq("status", "failed");
      leadsQueued = failedCount;
    }
  }

  if (!leadsQueued) {
    return NextResponse.json({ error: "Nenhum lead pendente" }, { status: 400 });
  }

  await supabase
    .from("broadcasts")
    .update({ status: "running", failed: 0 })
    .eq("id", id);

  return NextResponse.json({ status: "started", leads_queued: leadsQueued });
}
