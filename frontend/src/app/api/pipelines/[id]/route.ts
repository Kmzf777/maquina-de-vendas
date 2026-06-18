import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { assertCanManagePipeline } from "@/lib/supabase/pipeline-access";
import { requireAdmin } from "@/lib/admin-auth";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const guard = await assertCanManagePipeline(supabase, id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const updates: Record<string, unknown> = { updated_at: new Date().toISOString() };

  if (body.name !== undefined) {
    if (!body.name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });
    updates.name = body.name.trim();
  }

  // Trocar dono / marcar universal: só admin
  if (body.owner_user_id !== undefined || body.is_universal !== undefined) {
    const admin = await requireAdmin();
    if (!admin.ok) return NextResponse.json({ error: admin.error }, { status: admin.status });
    if (body.owner_user_id !== undefined) updates.owner_user_id = body.owner_user_id; // string | null
    if (body.is_universal !== undefined) updates.is_universal = !!body.is_universal;
  }

  const { data, error } = await supabase
    .from("pipelines")
    .update(updates)
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

  const guard = await assertCanManagePipeline(supabase, id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

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
