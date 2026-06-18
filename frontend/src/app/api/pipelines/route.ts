import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import {
  getCurrentUser,
  resolvePipelineOwnerOnCreate,
  getAllowedPipelineIds,
} from "@/lib/supabase/pipeline-access";

const DEFAULT_STAGES = [
  { label: "Novo",         key: null,              dot_color: "#e07a7a", order_index: 0, is_protected: false },
  { label: "Contato",      key: null,              dot_color: "#d4a04a", order_index: 1, is_protected: false },
  { label: "Proposta",     key: null,              dot_color: "#9b7abf", order_index: 2, is_protected: false },
  { label: "Negociação",   key: null,              dot_color: "#5b8aad", order_index: 3, is_protected: false },
  { label: "Fechado Ganho",key: "fechado_ganho",   dot_color: "#5aad65", order_index: 4, is_protected: false },
  { label: "Perdido",      key: "fechado_perdido", dot_color: "#9ca3af", order_index: 5, is_protected: false },
];

export async function GET() {
  const supabase = await getServiceSupabase();
  let allowed: string[] | null;
  try {
    allowed = await getAllowedPipelineIds(supabase);
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
  let query = supabase.from("pipelines").select("*").order("order_index", { ascending: true });
  if (allowed !== null) query = query.in("id", allowed.length ? allowed : ["00000000-0000-0000-0000-000000000000"]);
  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const { name, owner_user_id } = await request.json();
  if (!name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });

  let user;
  try {
    user = await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
  const ownerToSet = resolvePipelineOwnerOnCreate(user, owner_user_id ?? null);

  const supabase = await getServiceSupabase();

  const { data: pipeline, error: pipelineError } = await supabase
    .from("pipelines")
    .insert({ name: name.trim(), owner_user_id: ownerToSet })
    .select()
    .single();
  if (pipelineError) return NextResponse.json({ error: pipelineError.message }, { status: 500 });

  const stages = DEFAULT_STAGES.map((s) => ({ ...s, pipeline_id: pipeline.id }));
  const { error: stagesError } = await supabase.from("pipeline_stages").insert(stages);
  if (stagesError) {
    await supabase.from("pipelines").delete().eq("id", pipeline.id);
    return NextResponse.json({ error: stagesError.message }, { status: 500 });
  }

  return NextResponse.json(pipeline, { status: 201 });
}
