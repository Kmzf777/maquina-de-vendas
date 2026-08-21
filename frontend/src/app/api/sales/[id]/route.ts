import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sales")
    .select("*, leads(id, name, phone, company), deals(id, title)")
    .eq("id", id)
    .maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "Venda não encontrada." }, { status: 404 });
  return NextResponse.json(data);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  // `bling_divergent`/`bling_divergence` entram aqui a partir da edicao em modo
  // Bling (Fase E): o CRM grava a alteracao mesmo quando o Bling recusa, e essas
  // colunas tornam a divergencia auditavel em vez de silenciosa.
  const ALLOWED = [
    "product",
    "value",
    "sold_at",
    "sold_by",
    "notes",
    "deal_id",
    "conversation_id",
    "bling_divergent",
    "bling_divergence",
  ];
  const updates = Object.fromEntries(
    Object.entries(body).filter(([k]) => ALLOWED.includes(k))
  );

  const { data, error } = await supabase
    .from("sales")
    .update(updates)
    .eq("id", id)
    .select("*, leads(id, name, phone, company), deals(id, title)")
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
  const { error } = await supabase.from("sales").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
