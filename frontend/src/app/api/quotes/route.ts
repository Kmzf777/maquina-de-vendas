import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { resolverEscopoDeOrcamentos } from "@/lib/quotes/quotes-scope-route";
import { backendUrl } from "@/lib/quotes/backend";

/**
 * Listagem de /orcamento.
 *
 * Ao contrario do POST logo abaixo, esta metade NAO passa pelo FastAPI: consulta
 * o Supabase direto, no mesmo padrao de `/api/sales`. O motivo e o escopo — a
 * regra de quem ve o que mora aqui (`quotes-scope.ts`), junto da sessao do Next,
 * e o embed de `quote_items` que o formulario de edicao precisa vem de graca no
 * mesmo select. Mandar a listagem para o backend obrigaria a repassar a
 * identidade do usuario por um canal proprio so para reimplementar o mesmo
 * filtro do outro lado.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const leadId = searchParams.get("lead_id");
  const createdBy = searchParams.get("created_by");
  const status = searchParams.get("status");
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const search = searchParams.get("search");
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const limit = Math.min(100, Math.max(1, parseInt(searchParams.get("limit") ?? "25", 10) || 25));
  const offset = (page - 1) * limit;

  const supabase = await getServiceSupabase();

  const escopoRes = await resolverEscopoDeOrcamentos();
  if (!escopoRes.ok) return escopoRes.resposta;
  const escopo = escopoRes.escopo;

  let query = supabase
    .from("quotes")
    // `leads!inner` e o que permite filtrar o ORCAMENTO pelo nome do cliente: um
    // embed comum filtraria so o conteudo do embed e devolveria a linha do
    // orcamento com `leads: null`, dando uma lista cheia de resultados vazios em
    // vez de uma lista curta. O inner join nao descarta nada quando nao ha busca,
    // porque `quotes.lead_id` e NOT NULL com FK — toda linha tem lead.
    //
    // `quote_items` embutido pelo mesmo motivo de `sale_items` em /api/sales: a
    // edicao reabre o formulario com estes itens, e o PUT em
    // /propostas-comerciais/{id} SUBSTITUI os itens da proposta pelo que estiver
    // no formulario — sem eles, salvar uma mudanca de frete apagaria os itens no
    // ERP. A coluna "Itens" da tabela tambem sai daqui.
    .select(
      "*, leads!inner(id, name, phone, company), deals(id, title), quote_items(*)",
      { count: "exact" },
    )
    .order("quoted_at", { ascending: false })
    // Desempate estavel: `quoted_at` e `date`, sem hora, entao um dia com varios
    // orcamentos tem empate garantido — e sem segundo criterio a paginacao pode
    // repetir ou pular linhas entre duas paginas da MESMA consulta.
    .order("created_at", { ascending: false })
    .order("ordem", { foreignTable: "quote_items", ascending: true })
    .range(offset, offset + limit - 1);

  if (leadId) query = query.eq("lead_id", leadId);
  if (createdBy) query = query.eq("created_by", createdBy);
  if (status) query = query.eq("status", status);
  // `quoted_at` e `date`, nao `timestamptz`: comparar com "YYYY-MM-DD" cru esta
  // certo e o sufixo de hora que /api/sales precisa causaria erro de cast aqui.
  if (from) query = query.gte("quoted_at", from);
  if (to) query = query.lte("quoted_at", to);
  // `ilike` com o termo como VALOR de um parametro proprio, nao concatenado num
  // `or=(...)`: o texto vem da caixa de busca e um `,` ou `(` digitado ali
  // quebraria a sintaxe do filtro. Curinga no meio do termo so alarga a BUSCA,
  // nunca o escopo, porque o `.or(escopo)` abaixo entra com AND.
  if (search) query = query.ilike("leads.name", `%${search}%`);

  // O escopo e um parametro `or` separado, que o PostgREST combina com os
  // filtros acima usando AND. Por isso `created_by` vindo da query string so
  // consegue RESTRINGIR o conjunto ja permitido — um vendedor que digitasse o
  // e-mail de outro receberia lista vazia, nao a lista alheia.
  if (escopo) query = query.or(escopo);

  const { data, error, count } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: data ?? [], count: count ?? 0 });
}

/**
 * Criacao — proxy para o FastAPI, que e quem fala com o Bling.
 *
 * O status volta TAL QUAL porque o modal distingue cada um: 201 (criado),
 * 409 `contact_unresolved` (abre o formulario de contato) e 422 (validacao do
 * Bling). Colapsar tudo num 500 tiraria do vendedor a unica tela que resolve o
 * 409 sozinha.
 */
export async function POST(request: NextRequest) {
  const body = await request.json();
  try {
    const resp = await fetch(`${backendUrl()}/api/quotes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return NextResponse.json(await resp.json(), { status: resp.status });
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
