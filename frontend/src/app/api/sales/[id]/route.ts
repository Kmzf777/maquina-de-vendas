import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser, type CurrentUser } from "@/lib/supabase/pipeline-access";
import { podeVerVenda, scopeAtivo, SalesScopeError } from "@/lib/sales/sales-scope";

type Guarda = { ok: true } | { ok: false; resposta: NextResponse };

/**
 * Venda fora do escopo responde 404, nao 403: 403 confirmaria que ela existe.
 *
 * A sessao e resolvida ANTES de tocar a linha: se checassemos a linha
 * primeiro, um chamador sem sessao receberia 404 para id inexistente e 401
 * para id existente, o que confirma existencia de UUID sem exigir sessao
 * valida. Na pratica o `proxy.ts` ja barra requisicao sem sessao antes da
 * rota, mas a ordem aqui e defesa em profundidade, nao um furo aberto.
 */
async function guardaDeVenda(
  supabase: Awaited<ReturnType<typeof getServiceSupabase>>,
  id: string,
): Promise<Guarda> {
  if (!scopeAtivo()) return { ok: true };

  let user: CurrentUser;
  try {
    user = await getCurrentUser();
  } catch (err) {
    const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }

  const { data: linha, error } = await supabase
    .from("sales")
    .select("sold_by, origin")
    .eq("id", id)
    .maybeSingle();
  if (error) {
    return { ok: false, resposta: NextResponse.json({ error: error.message }, { status: 500 }) };
  }
  if (!linha) {
    return { ok: false, resposta: NextResponse.json({ error: "Venda não encontrada." }, { status: 404 }) };
  }

  try {
    const pode = podeVerVenda(linha, { userId: user.userId, email: user.email, role: user.role }, true);
    if (!pode) {
      return { ok: false, resposta: NextResponse.json({ error: "Venda não encontrada." }, { status: 404 }) };
    }
    return { ok: true };
  } catch (err) {
    const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const guarda = await guardaDeVenda(supabase, id);
  if (!guarda.ok) return guarda.resposta;
  const { data, error } = await supabase
    .from("sales")
    // sale_items embutido: ver comentário equivalente em /api/sales — este é o
    // caminho do deep-link (/painel-vendas?sale_id=), que também abre o modal
    // de edição e precisa dos itens já preenchidos.
    .select("*, leads(id, name, phone, company), deals(id, title), sale_items(*)")
    .order("ordem", { foreignTable: "sale_items", ascending: true })
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
  const guarda = await guardaDeVenda(supabase, id);
  if (!guarda.ok) return guarda.resposta;

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
  const guarda = await guardaDeVenda(supabase, id);
  if (!guarda.ok) return guarda.resposta;
  const { error } = await supabase.from("sales").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
