import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

// Vinculo e-mail do usuario do CRM -> vendedor do Bling (tabela bling_seller_map).
// Lido pelo backend em _seller_id_for() na hora de montar o pedido; sem vinculo,
// o pedido vai sem vendedor (nao bloqueia a venda).

async function requireAdmin(): Promise<Response | null> {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return NextResponse.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return null;
}

export async function GET() {
  const denied = await requireAdmin();
  if (denied) return denied;

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("bling_seller_map")
    .select("user_email, bling_seller_id");
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: data ?? [] });
}

export async function PUT(request: NextRequest) {
  const denied = await requireAdmin();
  if (denied) return denied;

  const body = await request.json().catch(() => ({}));
  const email = typeof body.user_email === "string" ? body.user_email.trim() : "";
  if (!email) return NextResponse.json({ error: "user_email é obrigatório" }, { status: 400 });

  const supabase = await getServiceSupabase();

  // Vendedor vazio significa desvincular — a linha some em vez de guardar null,
  // porque bling_seller_id é NOT NULL na tabela.
  if (body.bling_seller_id === null || body.bling_seller_id === "" || body.bling_seller_id === undefined) {
    const { error } = await supabase.from("bling_seller_map").delete().eq("user_email", email);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json({ ok: true, user_email: email, bling_seller_id: null });
  }

  const sellerId = Number(body.bling_seller_id);
  if (!Number.isFinite(sellerId) || sellerId <= 0) {
    return NextResponse.json({ error: "bling_seller_id inválido" }, { status: 400 });
  }

  const { error } = await supabase
    .from("bling_seller_map")
    .upsert(
      { user_email: email, bling_seller_id: sellerId, updated_at: new Date().toISOString() },
      { onConflict: "user_email" }
    );
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true, user_email: email, bling_seller_id: sellerId });
}
