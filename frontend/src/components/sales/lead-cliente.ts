/**
 * Dados do lead de que a venda e o topo da conversa precisam (P4 da call de
 * 01/10): o cadastro para pré-preencher o contato do Bling e o "Já é cliente?".
 *
 * A busca é POR ID, direto no Supabase do browser (RLS
 * `leads_select_authenticated`, o mesmo caminho de `use-realtime-leads` e
 * `lead-selector`): não existe `GET /api/leads/[id]`, e a lista `/api/leads`
 * inteira bate no teto de 1.000 linhas do PostgREST. Era por depender dessa
 * lista que o modal aberto pela conversa nascia com o cadastro vazio.
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { createClient } from "@/lib/supabase/client";
import type { ContactForm } from "@/lib/bling-contact-form";
import { docDigits } from "@/lib/documento";

export type FonteJaEraCliente = "auto" | "vendedor";

/** O que o cadastro do contato no Bling aproveita do lead. */
export interface DadosDeContato {
  name?: string | null;
  phone?: string | null;
  email?: string | null;
  cnpj?: string | null;
  razao_social?: string | null;
}

export interface LeadCliente extends DadosDeContato {
  id: string;
  /**
   * `null` = o sistema não sabe — o vendedor precisa responder.
   * `undefined` = a coluna ainda não existe no banco (migração 20261006 não
   * aplicada): nada é bloqueado por causa dela.
   */
  ja_era_cliente?: boolean | null;
  ja_era_cliente_fonte?: FonteJaEraCliente | null;
}

const COLUNAS_BASE = "id, name, phone, email, cnpj, razao_social";
const COLUNAS_CLIENTE = `${COLUNAS_BASE}, ja_era_cliente, ja_era_cliente_fonte`;

/**
 * Coluna inexistente: `42703` vem do Postgres (select de coluna que não
 * existe); `PGRST204` é o PostgREST sem a coluna no cache do esquema.
 */
const COLUNA_INEXISTENTE = new Set(["42703", "PGRST204"]);

function erroDoSupabase(e: { message?: string } | null): Error {
  return new Error(e?.message || "Não foi possível carregar o lead.");
}

export async function buscarLeadCliente(leadId: string): Promise<LeadCliente | null> {
  const sb = createClient();
  const completo = await sb
    .from("leads")
    .select(COLUNAS_CLIENTE)
    .eq("id", leadId)
    .maybeSingle();
  if (!completo.error) return (completo.data as unknown as LeadCliente | null) ?? null;

  // Sem a migração do P0 as colunas novas não existem e o select inteiro
  // falha. O cadastro continua valendo para o pré-preenchimento; só o "Já é
  // cliente?" fica indisponível (undefined) em vez de travar a venda.
  // SÓ nesse caso: qualquer outro erro (rede, timeout, RLS) propaga — tratá-lo
  // como "sem a coluna" deixaria a venda passar sem a pergunta obrigatória.
  if (!COLUNA_INEXISTENTE.has(String((completo.error as { code?: string }).code ?? ""))) {
    throw erroDoSupabase(completo.error);
  }
  const base = await sb.from("leads").select(COLUNAS_BASE).eq("id", leadId).maybeSingle();
  if (base.error) throw erroDoSupabase(base.error);
  return (base.data as unknown as LeadCliente | null) ?? null;
}

/** Pré-preenchimento do cadastro do contato no Bling (resolvedor do 409). */
export function defaultsDoContato(
  lead: DadosDeContato | null | undefined,
): Partial<ContactForm> {
  if (!lead) return {};
  const telefone = (lead.phone ?? "").trim();
  return {
    // O cadastro do Bling pede "Nome / Razão social" como deve sair na nota:
    // para empresa é a razão social; sem ela (pessoa física), o nome.
    nome: (lead.razao_social || lead.name || "").trim(),
    documento: docDigits(lead.cnpj) ?? "",
    email: (lead.email ?? "").trim(),
    // `bling-<id>` é o telefone sintético dos leads criados pelo webhook do
    // Bling — não é número de ninguém.
    telefone: telefone.startsWith("bling-") ? "" : telefone,
  };
}

/** Corpo do PATCH em `/api/leads/{id}` quando o vendedor responde. */
export function corpoJaEraCliente(
  valor: boolean,
  por: string | null | undefined,
  agora: Date = new Date(),
) {
  return {
    ja_era_cliente: valor,
    ja_era_cliente_fonte: "vendedor" as const,
    ja_era_cliente_por: por || null,
    ja_era_cliente_em: agora.toISOString(),
  };
}

export async function salvarJaEraCliente(
  leadId: string,
  valor: boolean,
  por: string | null | undefined,
): Promise<void> {
  const res = await fetch(`/api/leads/${leadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpoJaEraCliente(valor, por)),
  }).catch(() => null);
  if (!res || !res.ok) {
    const corpo = res ? await res.json().catch(() => ({})) : {};
    throw new Error(
      (corpo as { error?: string }).error ??
        "Não foi possível salvar a resposta de “Já é cliente?”.",
    );
  }
}

/**
 * A venda só exige a resposta quando o banco diz que não sabe (`null`). O
 * sistema nunca marca "não" sozinho (decisão de 06/10) — por isso `false`
 * também não pergunta: foi um humano que respondeu.
 */
export function precisaPerguntarJaEraCliente(
  lead: LeadCliente | null | undefined,
): boolean {
  return !!lead && lead.ja_era_cliente === null;
}

// ── fonte única por lead ────────────────────────────────────────────────────
// Cabeçalho da conversa e painel de venda mostram o MESMO "Já é cliente?". Com
// um estado por componente, responder num não mudava o outro: o painel seguia
// exigindo a resposta já dada no topo. Aqui o lead fica num armazém por id,
// fora do React, e todo `useLeadCliente` do mesmo id lê a mesma entrada.
//
// Não é TanStack Query de propósito: o `QueryClientProvider` só existe na tela
// de conversas, e os painéis também abrem em /painel-vendas, /orcamento, no
// card do funil e no modal do lead — lá o `useQuery` quebraria.

interface EntradaLead {
  lead: LeadCliente | null;
  erro: string | null;
  carregando: boolean;
}

const entradas = new Map<string, EntradaLead>();
/** Conta as mudanças locais por lead, para a leitura em voo não atropelá-las. */
const versoes = new Map<string, number>();
const emVoo = new Set<string>();
const ouvintes = new Set<() => void>();

function publicar(id: string, entrada: EntradaLead) {
  entradas.set(id, entrada);
  for (const ouvir of ouvintes) ouvir();
}

function assinar(ouvir: () => void) {
  ouvintes.add(ouvir);
  return () => {
    ouvintes.delete(ouvir);
  };
}

/** (Re)lê o lead do banco. Uma leitura por id de cada vez. */
function carregarLeadCliente(id: string) {
  if (emVoo.has(id)) return;
  emVoo.add(id);
  const versao = versoes.get(id) ?? 0;
  publicar(id, { lead: entradas.get(id)?.lead ?? null, erro: null, carregando: true });
  buscarLeadCliente(id)
    .then(
      (lead) => ({ lead, erro: null }),
      (e: unknown) => ({
        lead: null,
        erro: e instanceof Error ? e.message : "Não foi possível carregar o lead.",
      }),
    )
    .then(({ lead, erro }) => {
      emVoo.delete(id);
      const local = entradas.get(id)?.lead;
      if ((versoes.get(id) ?? 0) !== versao && local) {
        // O vendedor respondeu enquanto a leitura viajava: o banco devolveu o
        // estado de ANTES da resposta. O cadastro vem do banco; o "Já é
        // cliente?" fica com a resposta local, que é a mais nova.
        publicar(id, {
          lead: {
            ...(lead ?? local),
            ja_era_cliente: local.ja_era_cliente,
            ja_era_cliente_fonte: local.ja_era_cliente_fonte,
          },
          erro: null,
          carregando: false,
        });
        return;
      }
      publicar(id, { lead, erro, carregando: false });
    });
}

/** Mudança local no lead (ex.: resposta gravada), vista por todos os leitores. */
export function atualizarLeadCliente(id: string, patch: Partial<LeadCliente>) {
  const atual = entradas.get(id);
  if (!atual?.lead) return;
  versoes.set(id, (versoes.get(id) ?? 0) + 1);
  publicar(id, { ...atual, lead: { ...atual.lead, ...patch } });
}

/**
 * Lead por id, relido do banco a cada montagem e quando o id muda.
 * `atualizar` aplica uma mudança local (ex.: depois de gravar o "Já é
 * cliente?") sem nova ida ao banco — e SEMPRE no lead deste hook no momento
 * do render: uma resposta que chega depois da troca de lead corrige o lead
 * certo, não o que está na tela.
 */
export function useLeadCliente(leadId: string | null | undefined) {
  const entrada = useSyncExternalStore(
    assinar,
    () => (leadId ? entradas.get(leadId) : undefined),
    () => undefined,
  );

  useEffect(() => {
    if (leadId) carregarLeadCliente(leadId);
  }, [leadId]);

  const atualizar = useCallback(
    (patch: Partial<LeadCliente>) => {
      if (leadId) atualizarLeadCliente(leadId, patch);
    },
    [leadId],
  );

  const lead = (leadId && entrada?.lead) || null;
  const erro = (leadId && entrada?.erro) || null;
  const carregando = !!leadId && (!entrada || entrada.carregando);
  return { lead, carregando, erro, atualizar };
}
