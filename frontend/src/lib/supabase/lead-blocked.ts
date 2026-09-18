import type { getServiceSupabase } from "@/lib/supabase/api";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;

/**
 * Funil Blacklist. Mesma constante de `BLACKLIST_PIPELINE_ID`
 * (`backend/app/leads/service.py:1544`) — se ela mudar lá, muda aqui.
 */
export const BLACKLIST_PIPELINE_ID = "8988e852-2836-4add-b023-4db4d6cd0e6e";

/**
 * Texto único do 403 devolvido pelas rotas de envio manual. Fica aqui para as
 * quatro rotas não divergirem na grafia — o chat mostra este texto cru ao operador.
 */
export const MENSAGEM_LEAD_BLOQUEADO =
  "Lead bloqueado — desbloqueie para voltar a conversar.";

/**
 * Por que este helper existe: as rotas Next de envio montam o POST para
 * `graph.facebook.com` com o access_token lido do Supabase — não passam pelo
 * FastAPI nem pelo `MetaCloudClient`. Nenhum guard de backend as cobre, então o
 * critério de bloqueio precisa existir também deste lado.
 *
 * Critério idêntico ao de `is_lead_blacklisted` (`backend/app/leads/service.py:381`):
 *   - `leads.opt_out IS TRUE` (canônico), OU
 *   - o lead tem QUALQUER deal no funil Blacklist (defesa em profundidade: cobre o
 *     lead arrastado para a Blacklist no Kanban sem o flag).
 *
 * NÃO inclui `stage = 'perdido'`: aquilo é rejeição SOFT e reativável; tratá-la como
 * bloqueio mataria campanhas de reativação.
 *
 * **Fail-open**: erro de consulta devolve `false` (com `console.warn`) — igual ao
 * backend. Um envio não pode ser travado por um soluço da checagem; a proteção vem
 * das camadas somadas (filtro na origem + guard no envio + gate inbound), não de
 * fail-closed.
 *
 * @param optOutConhecido `opt_out` já trazido pelo `select` da rota (`leads(id, phone,
 *   opt_out)`), para não gastar uma ida extra ao Supabase no caminho de envio.
 *   `true` encerra na hora; `false`/`null` (valor conhecido do banco) pula só a
 *   consulta em `leads`; `undefined` (campo não selecionado) consulta as duas tabelas.
 */
export async function isLeadBlocked(
  supabase: ServiceSupabase,
  leadId: string | null | undefined,
  optOutConhecido?: boolean | null,
): Promise<boolean> {
  if (!leadId) return false;
  if (optOutConhecido === true) return true;

  try {
    if (optOutConhecido === undefined) {
      const { data: lead, error } = await supabase
        .from("leads")
        .select("opt_out")
        .eq("id", leadId)
        .limit(1)
        .maybeSingle();
      if (error) throw error;
      if (lead?.opt_out) return true;
    }

    const { data: deals, error: dealsError } = await supabase
      .from("deals")
      .select("id")
      .eq("lead_id", leadId)
      .eq("pipeline_id", BLACKLIST_PIPELINE_ID)
      .limit(1);
    if (dealsError) throw dealsError;
    return Array.isArray(deals) && deals.length > 0;
  } catch (err) {
    console.warn(
      `[lead-blocked] checagem falhou p/ lead ${leadId} — fail-open (envio segue):`,
      err instanceof Error ? err.message : err,
    );
    return false;
  }
}

/**
 * Tamanho do lote do `.in(...)`. Um `in` com centenas de UUIDs vira uma query string
 * gigante e o PostgREST recusa a URL — por isso fatiamos.
 */
const TAMANHO_DO_LOTE = 100;

/**
 * Versão em lote do mesmo critério, para quem checa uma LISTA de leads (atribuição de
 * disparo). Fazer `isLeadBlocked` num laço custaria 2 idas ao Supabase por lead — com
 * algumas centenas de leads a rota estoura o tempo antes de inserir qualquer coisa.
 *
 * Devolve o conjunto dos `lead_id` BLOQUEADOS. **Fail-open** pelo mesmo motivo do
 * `isLeadBlocked`: erro de consulta devolve conjunto vazio (ninguém filtrado) em vez
 * de barrar o disparo inteiro por causa da checagem.
 */
export async function blockedLeadIds(
  supabase: ServiceSupabase,
  leadIds: string[],
): Promise<Set<string>> {
  const bloqueados = new Set<string>();
  const ids = [...new Set(leadIds.filter(Boolean))];
  if (ids.length === 0) return bloqueados;

  try {
    for (let i = 0; i < ids.length; i += TAMANHO_DO_LOTE) {
      const lote = ids.slice(i, i + TAMANHO_DO_LOTE);

      const { data: leads, error: leadsError } = await supabase
        .from("leads")
        .select("id")
        .in("id", lote)
        .eq("opt_out", true);
      if (leadsError) throw leadsError;
      for (const l of leads ?? []) bloqueados.add((l as { id: string }).id);

      const { data: deals, error: dealsError } = await supabase
        .from("deals")
        .select("lead_id")
        .in("lead_id", lote)
        .eq("pipeline_id", BLACKLIST_PIPELINE_ID);
      if (dealsError) throw dealsError;
      for (const d of deals ?? []) bloqueados.add((d as { lead_id: string }).lead_id);
    }
  } catch (err) {
    console.warn(
      "[lead-blocked] checagem em lote falhou — fail-open (disparo segue):",
      err instanceof Error ? err.message : err,
    );
    return new Set<string>();
  }

  return bloqueados;
}
