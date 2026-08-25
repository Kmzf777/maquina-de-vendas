import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { resolverEscopoDeOrcamentos } from "@/lib/quotes/quotes-scope-route";
import { contarAprovacoes, taxaDeAprovacao } from "@/lib/quotes/quote-display";

/**
 * Os quatro indicadores de /orcamento: quantidade, valor total proposto, taxa de
 * aprovacao e ticket medio.
 *
 * Os QUATRO saem da MESMA consulta, com os MESMOS filtros — e essa e a licao do
 * commit 85598b89, onde o filtro "Vendedor" de /painel-vendas movia a tabela e
 * deixava os quatro numeros ao lado falando da operacao inteira. Aqui isso e
 * estrutural, nao disciplina: nao existe um caminho alternativo por onde um card
 * possa escapar do recorte, porque nao ha agregacao separada.
 *
 * O que /painel-vendas tem e aqui NAO existe: a RPC `get_avg_repurchase_cycle_days`,
 * que agrega no banco por fora do filtro `or` e por isso precisa do
 * `vendedorDaRecompra` para decidir a quem os dados pertencem. Nenhum indicador
 * de orcamento agrega fora do `.or(escopo)`, entao nao ha o vazamento de
 * agregado que aquela funcao existe para impedir — e nao ha um gemeo dela aqui
 * de proposito.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const createdBy = searchParams.get("created_by");
  const status = searchParams.get("status");

  const supabase = await getServiceSupabase();

  const escopoRes = await resolverEscopoDeOrcamentos();
  if (!escopoRes.ok) return escopoRes.resposta;
  const escopo = escopoRes.escopo;

  let query = supabase.from("quotes").select("total, status");
  // `quoted_at` e `date`: comparacao com "YYYY-MM-DD" cru, sem sufixo de hora.
  if (from) query = query.gte("quoted_at", from);
  if (to) query = query.lte("quoted_at", to);
  if (createdBy) query = query.eq("created_by", createdBy);
  // O filtro de situacao tambem move os cards. Filtrar por "Enviado" e ver uma
  // taxa de aprovacao de 62% ao lado de uma lista onde nada foi aprovado seria
  // exatamente o defeito que 85598b89 corrigiu, so que numa coluna diferente.
  if (status) query = query.eq("status", status);
  // AND com tudo acima: os filtros da URL restringem, o escopo delimita.
  if (escopo) query = query.or(escopo);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const linhas = data ?? [];
  const count = linhas.length;
  // `Number()` explicito: `numeric(12,2)` chega como string pelo PostgREST e
  // `soma + "1500.00"` concatenaria em vez de somar.
  const total_value = linhas.reduce((soma, q) => soma + Number(q.total ?? 0), 0);
  const avg_value = count > 0 ? total_value / count : 0;

  // Numerador e denominador viajam junto com a taxa: o card desenha a barra com
  // eles e o "3 de 5" que explica o 60%. Uma porcentagem sozinha esconde que ela
  // pode ter saido de uma amostra de dois orcamentos.
  const tally = contarAprovacoes(linhas.map((q) => String(q.status ?? "")));

  return NextResponse.json({
    count,
    total_value,
    avg_value,
    approval_rate: taxaDeAprovacao(tally),
    approved_count: tally.approved,
    decided_count: tally.decided,
  });
}
