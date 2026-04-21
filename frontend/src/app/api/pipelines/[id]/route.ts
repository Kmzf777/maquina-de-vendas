import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { name } = await request.json();
  if (!name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("pipelines")
    .update({ name: name.trim(), updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { count: pipelineCount } = await supabase
    .from("pipelines")
    .select("*", { count: "exact", head: true });
  if ((pipelineCount ?? 0) <= 1) {
    return NextResponse.json({ error: "O último funil não pode ser excluído." }, { status: 409 });
  }
  const { count, error: countError } = await supabase
    .from("deals")
    .select("*", { count: "exact", head: true })
    .eq("pipeline_id", id);
  if (countError) return NextResponse.json({ error: countError.message }, { status: 500 });
  if (count && count > 0) {
    return NextResponse.json(
      { error: `Funil tem ${count} deal(s). Mova ou remova os deals antes de excluir.` },
      { status: 409 }
    );
  }
  const { error } = await supabase.from("pipelines").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
