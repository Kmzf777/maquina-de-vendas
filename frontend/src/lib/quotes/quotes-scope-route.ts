import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { getServiceSupabase } from "@/lib/supabase/api";
import {
  quotesScopeFilter,
  podeVerOrcamento,
  scopeAtivo,
  QuotesScopeError,
  type QuotesScopeUser,
} from "@/lib/quotes/quotes-scope";

/**
 * Resolve o escopo de orcamentos para uma rota, ou devolve o 401 pronto.
 *
 * Gemeo de `resolverEscopoDeVendas` e separado de `quotes-scope.ts` pelo mesmo
 * motivo que `sales-scope-route.ts` e separado de `sales-scope.ts`: este arquivo
 * importa `next/server` e, por tabela, `next/headers` — nada disso carrega no
 * runner `node` do vitest. Manter a decisao testavel em `quotes-scope.ts` e a
 * ligacao com o request aqui e o que permite testar a regra de escopo sem um
 * servidor Next de pe.
 *
 * Diferenca para o de vendas: aqui nao ha `user` na resposta. Ele existe la
 * porque a RPC de recompra agrega no banco por fora do filtro `or` e precisa
 * decidir sozinha qual vendedor entra. Os quatro indicadores de /orcamento saem
 * todos da MESMA consulta ja filtrada por `.or(escopo)`, entao nao ha nenhum
 * agregado escapando do escopo e nada para decidir — devolver o usuario aqui
 * seria oferecer uma alavanca que ninguem deve puxar.
 */
export type EscopoDeOrcamentos =
  | { ok: true; escopo: string | null }
  | { ok: false; resposta: NextResponse };

export async function resolverEscopoDeOrcamentos(): Promise<EscopoDeOrcamentos> {
  if (!scopeAtivo()) return { ok: true, escopo: null };

  try {
    const atual = await getCurrentUser();
    const user: QuotesScopeUser = {
      userId: atual.userId,
      email: atual.email,
      role: atual.role,
    };
    return { ok: true, escopo: quotesScopeFilter(user, true) };
  } catch (err) {
    const msg = err instanceof QuotesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }
}

/**
 * Guarda de propriedade das rotas que recebem o id na URL.
 *
 * `resolverEscopoDeOrcamentos` acima protege a LISTAGEM, onde o filtro entra na
 * consulta. Ele nao alcanca `/api/quotes/[id]`, `[id]/pdf`, `[id]/status` e
 * `[id]/convert`, que sao proxy para o FastAPI e nunca chegam a montar filtro
 * nenhum. Sem esta funcao, qualquer usuario autenticado de posse de um UUID lia,
 * editava, convertia em venda e baixava o PDF de orcamento alheio.
 *
 * O gemeo em vendas (`guardaDeVenda`, em /api/sales/[id]) ja existia; a falta
 * aqui era assimetria, nao decisao. Nota-se especialmente na CONVERSAO: ela cria
 * um pedido de venda no Bling. Sem guarda, um vendedor fecharia negocio no ERP a
 * partir da proposta de outro.
 *
 * Devolve **404**, nao 403, para orcamento que existe mas nao e seu — mesmo
 * criterio de `guardaDeVenda`. 403 confirmaria a existencia do registro e
 * transformaria a rota num oraculo de "este UUID e valido".
 */
export type GuardaDeOrcamento =
  | { ok: true }
  | { ok: false; resposta: NextResponse };

export async function guardaDeOrcamento(id: string): Promise<GuardaDeOrcamento> {
  if (!scopeAtivo()) return { ok: true };

  let user: QuotesScopeUser;
  try {
    const atual = await getCurrentUser();
    user = { userId: atual.userId, email: atual.email, role: atual.role };
  } catch (err) {
    const msg = err instanceof QuotesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }

  const supabase = await getServiceSupabase();
  const { data: linha, error } = await supabase
    .from("quotes")
    .select("created_by")
    .eq("id", id)
    .maybeSingle();
  if (error) {
    return { ok: false, resposta: NextResponse.json({ error: error.message }, { status: 500 }) };
  }
  // Orcamento inexistente devolve o MESMO 404 do alheio, de proposito: os dois
  // casos tem que ser indistinguiveis de fora.
  if (!linha) {
    return {
      ok: false,
      resposta: NextResponse.json({ error: "Orçamento não encontrado." }, { status: 404 }),
    };
  }

  try {
    if (!podeVerOrcamento(linha, user, true)) {
      return {
        ok: false,
        resposta: NextResponse.json({ error: "Orçamento não encontrado." }, { status: 404 }),
      };
    }
    return { ok: true };
  } catch (err) {
    // E-mail ausente ou com curinga do PostgREST: 401, nao 404. O problema esta
    // em quem pergunta, nao no que foi perguntado.
    const msg = err instanceof QuotesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }
}
