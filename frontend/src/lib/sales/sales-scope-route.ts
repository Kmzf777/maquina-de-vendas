import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { salesScopeFilter, scopeAtivo, SalesScopeError } from "@/lib/sales/sales-scope";

/**
 * Resolve o escopo de vendas para uma rota, ou devolve a resposta 401 pronta.
 *
 * Existe para que as rotas que listam vendas nao carreguem tres copias byte a
 * byte iguais desta decisao: se um motivo de bypass novo aparecer, ele entra
 * aqui e vale nos tres pontos. O `guardaDeVenda` de /api/sales/[id] NAO usa
 * isto de proposito — la a decisao e sobre uma linha ja carregada, e tem outro
 * formato de resposta (404, nao 401).
 */
export type EscopoResolvido =
  | { ok: true; escopo: string | null }
  | { ok: false; resposta: NextResponse };

export async function resolverEscopoDeVendas(): Promise<EscopoResolvido> {
  if (!scopeAtivo()) return { ok: true, escopo: null };

  try {
    const user = await getCurrentUser();
    return {
      ok: true,
      escopo: salesScopeFilter(
        { userId: user.userId, email: user.email, role: user.role },
        true,
      ),
    };
  } catch (err) {
    const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }
}
