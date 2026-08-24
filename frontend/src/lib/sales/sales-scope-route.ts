import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import {
  salesScopeFilter,
  scopeAtivo,
  SalesScopeError,
  type SalesScopeUser,
} from "@/lib/sales/sales-scope";

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
  | { ok: true; escopo: string | null; user: SalesScopeUser | null }
  | { ok: false; resposta: NextResponse };

/**
 * `user` vem junto porque nem tudo se resolve com o filtro `or`. A RPC de
 * recompra agrega no banco e nao passa pelo `.or()`, entao quem a chama precisa
 * decidir sozinho qual vendedor entra — e para isso precisa saber quem esta
 * logado. `null` quando o escopo esta desligado: nao ha decisao a tomar.
 */
export async function resolverEscopoDeVendas(): Promise<EscopoResolvido> {
  if (!scopeAtivo()) return { ok: true, escopo: null, user: null };

  try {
    const atual = await getCurrentUser();
    const user: SalesScopeUser = {
      userId: atual.userId,
      email: atual.email,
      role: atual.role,
    };
    return { ok: true, escopo: salesScopeFilter(user, true), user };
  } catch (err) {
    const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }
}
