import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("pipeline_stages")
    .select("*")
    .eq("pipeline_id", id)
    .order("order_index", { ascending: true });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { label, dot_color } = await request.json();
  if (!label?.trim()) return NextResponse.json({ error: "Label é obrigatório" }, { status: 400 });
  const supabase = await getServiceSupabase();

  // Inserir antes dos stages protegidos (que ficam sempre no final)
  const { data: lastNormal, error: lastNormalError } = await supabase
    .from("pipeline_stages")
    .select("order_index")
    .eq("pipeline_id", id)
    .eq("is_protected", false)
    .order("order_index", { ascending: false })
    .limit(1);

  if (lastNormalError) return NextResponse.json({ error: lastNormalError.message }, { status: 500 });

  const insertAt = (lastNormal?.[0]?.order_index ?? -1) + 1;

  // Shiftar stages protegidos para abrir espaço
  const { error: shiftError } = await supabase.rpc("increment_stage_order", {
    p_pipeline_id: id,
    p_from_order: insertAt,
  });
  if (shiftError) return NextResponse.json({ error: shiftError.message }, { status: 500 });

  const { data, error } = await supabase
    .from("pipeline_stages")
    .insert({
      pipeline_id: id,
      label: label.trim(),
      dot_color: dot_color || "#5b8aad",
      order_index: insertAt,
      is_protected: false,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
