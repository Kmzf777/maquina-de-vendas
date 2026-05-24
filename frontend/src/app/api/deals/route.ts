import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const pipelineId = searchParams.get("pipeline_id");
  const supabase = await getServiceSupabase();

  let query = supabase
    .from("deals")
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .order("updated_at", { ascending: false });

  if (pipelineId) query = query.eq("pipeline_id", pipelineId);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  if (!body.pipeline_id) return NextResponse.json({ error: "pipeline_id é obrigatório" }, { status: 400 });
  if (!body.lead_id || !body.title?.trim()) return NextResponse.json({ error: "lead_id e title são obrigatórios" }, { status: 400 });

  let stageId: string | null = null;

  if (body.stage_id) {
    // Validar que o stage pertence ao pipeline informado e não é protegido
    const { data: providedStage } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("id", body.stage_id)
      .eq("pipeline_id", body.pipeline_id)
      .eq("is_protected", false)
      .maybeSingle();
    if (providedStage) stageId = providedStage.id;
  }

  if (!stageId) {
    // Fallback: usar o primeiro stage não-protegido do pipeline
    const { data: firstStage, error: stageError } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("pipeline_id", body.pipeline_id)
      .eq("is_protected", false)
      .order("order_index", { ascending: true })
      .limit(1)
      .maybeSingle();
    if (stageError) return NextResponse.json({ error: stageError.message }, { status: 500 });
    if (!firstStage) return NextResponse.json({ error: "Funil não tem stages disponíveis." }, { status: 422 });
    stageId = firstStage.id;
  }

  const { data, error } = await supabase
    .from("deals")
    .insert({
      lead_id: body.lead_id,
      title: body.title,
      value: body.value || 0,
      pipeline_id: body.pipeline_id,
      stage_id: stageId,
      stage: "novo",
      category: body.category || null,
      expected_close_date: body.expected_close_date || null,
      assigned_to: body.assigned_to || null,
    })
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
