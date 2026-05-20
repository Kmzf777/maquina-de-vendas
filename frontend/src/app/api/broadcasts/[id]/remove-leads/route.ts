import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  let body: { lead_ids?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Body JSON inválido" }, { status: 400 });
  }

  const lead_ids = body.lead_ids;

  if (
    !Array.isArray(lead_ids) ||
    lead_ids.length === 0 ||
    !lead_ids.every((id) => typeof id === "string" && id.length > 0)
  ) {
    return NextResponse.json(
      { error: "lead_ids deve ser um array de strings não-vazias" },
      { status: 400 }
    );
  }

  try {
    const { id } = await params;
    const supabase = await getServiceSupabase();

    const { data: broadcast, error: broadcastErr } = await supabase
      .from("broadcasts")
      .select("id")
      .eq("id", id)
      .single();

    if (broadcastErr || !broadcast) {
      return NextResponse.json({ error: "Broadcast não encontrado" }, { status: 404 });
    }

    const { count: deletedCount, error: deleteErr } = await supabase
      .from("broadcast_leads")
      .delete({ count: "exact" })
      .eq("broadcast_id", id)
      .in("lead_id", lead_ids as string[]);

    if (deleteErr) {
      return NextResponse.json({ error: deleteErr.message }, { status: 500 });
    }

    const { count, error: countErr } = await supabase
      .from("broadcast_leads")
      .select("id", { count: "exact", head: true })
      .eq("broadcast_id", id);

    if (countErr) {
      return NextResponse.json({ error: countErr.message }, { status: 500 });
    }

    const { error: updateErr } = await supabase
      .from("broadcasts")
      .update({ total_leads: count ?? 0 })
      .eq("id", id);

    if (updateErr) {
      return NextResponse.json({ error: updateErr.message }, { status: 500 });
    }

    return NextResponse.json({
      removed_count: deletedCount ?? 0,
      new_total: count ?? 0,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
