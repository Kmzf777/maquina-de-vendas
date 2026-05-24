import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; stageId: string }> }
) {
  const { stageId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data: existing, error: fetchError } = await supabase
    .from("pipeline_stages")
    .select("is_protected, key")
    .eq("id", stageId)
    .single();
  if (fetchError) return NextResponse.json({ error: fetchError.message }, { status: 500 });
  const TERMINAL_KEYS = ["fechado_ganho", "fechado_perdido", "perdido"];
  if (existing?.is_protected || TERMINAL_KEYS.includes(existing?.key ?? "")) {
    return NextResponse.json({ error: "Stages protegidos não podem ser editados." }, { status: 409 });
  }

  const updates: Record<string, unknown> = {};
  if (body.label !== undefined) {
    if (!body.label?.trim()) return NextResponse.json({ error: "Label não pode ser vazio." }, { status: 400 });
    updates.label = body.label.trim();
  }
  if (body.dot_color !== undefined) updates.dot_color = body.dot_color;
  if (body.order_index !== undefined) updates.order_index = body.order_index;
  const { data, error } = await supabase
    .from("pipeline_stages")
    .update(updates)
    .eq("id", stageId)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; stageId: string }> }
) {
  const { stageId } = await params;
  const supabase = await getServiceSupabase();

  const { data: stage, error: stageError } = await supabase
    .from("pipeline_stages")
    .select("is_protected, key")
    .eq("id", stageId)
    .single();
  if (stageError) return NextResponse.json({ error: stageError.message }, { status: 500 });
  const TERMINAL_KEYS = ["fechado_ganho", "fechado_perdido", "perdido"];
  if (stage?.is_protected || TERMINAL_KEYS.includes(stage?.key ?? "")) {
    return NextResponse.json({ error: "Stages protegidos não podem ser removidos." }, { status: 409 });
  }

  const { count, error: countError } = await supabase
    .from("deals")
    .select("*", { count: "exact", head: true })
    .eq("stage_id", stageId);
  if (countError) return NextResponse.json({ error: countError.message }, { status: 500 });
  if (count && count > 0) {
    return NextResponse.json(
      { error: `Stage tem ${count} deal(s). Mova os deals antes de remover.` },
      { status: 409 }
    );
  }

  const { error } = await supabase.from("pipeline_stages").delete().eq("id", stageId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
