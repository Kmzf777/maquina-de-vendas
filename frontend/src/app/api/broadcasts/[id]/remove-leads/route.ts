import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = await request.json();
    const lead_ids: string[] = body.lead_ids ?? [];

    if (!lead_ids.length) {
      return NextResponse.json({ error: "lead_ids vazio" }, { status: 400 });
    }

    const supabase = await getServiceSupabase();

    // Verify broadcast exists
    const { data: broadcast, error: broadcastErr } = await supabase
      .from("broadcasts")
      .select("id")
      .eq("id", id)
      .single();

    if (broadcastErr || !broadcast) {
      return NextResponse.json({ error: "Broadcast não encontrado" }, { status: 404 });
    }

    // Delete selected leads
    const { error: deleteErr } = await supabase
      .from("broadcast_leads")
      .delete()
      .eq("broadcast_id", id)
      .in("lead_id", lead_ids);

    if (deleteErr) {
      return NextResponse.json({ error: deleteErr.message }, { status: 500 });
    }

    // Recount remaining leads
    const { count } = await supabase
      .from("broadcast_leads")
      .select("id", { count: "exact", head: true })
      .eq("broadcast_id", id);

    // Update total_leads on broadcast
    await supabase
      .from("broadcasts")
      .update({ total_leads: count ?? 0 })
      .eq("id", id);

    return NextResponse.json({
      removed_count: lead_ids.length,
      new_total: count ?? 0,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
