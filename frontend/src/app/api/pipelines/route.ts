import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

const DEFAULT_STAGES = [
  { label: "Novo",         key: null,              dot_color: "#e07a7a", order_index: 0, is_protected: false },
  { label: "Contato",      key: null,              dot_color: "#d4a04a", order_index: 1, is_protected: false },
  { label: "Proposta",     key: null,              dot_color: "#9b7abf", order_index: 2, is_protected: false },
  { label: "Negociação",   key: null,              dot_color: "#5b8aad", order_index: 3, is_protected: false },
  { label: "Fechado Ganho",key: "fechado_ganho",   dot_color: "#5aad65", order_index: 4, is_protected: true  },
  { label: "Perdido",      key: "fechado_perdido", dot_color: "#9ca3af", order_index: 5, is_protected: true  },
];

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("pipelines")
    .select("*")
    .order("order_index", { ascending: true });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const { name } = await request.json();
  if (!name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });
  const supabase = await getServiceSupabase();

  const { data: pipeline, error: pipelineError } = await supabase
    .from("pipelines")
    .insert({ name: name.trim() })
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
