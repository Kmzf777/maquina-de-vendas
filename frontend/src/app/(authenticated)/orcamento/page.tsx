"use client";

import { useEffect, useState } from "react";
import { QuotesMetricsCards, type QuotesMetrics } from "@/components/quotes/quotes-metrics-cards";
import { QuotesFiltersBar } from "@/components/quotes/quotes-filters";
import { QuotesTable } from "@/components/quotes/quotes-table";
import { QuoteCreateModal } from "@/components/quotes/quote-create-modal";
import { useQuotes, type QuotesFilters } from "@/hooks/use-quotes";
import { useCurrentUserEmail } from "@/hooks/use-current-user";
import type { Quote } from "@/lib/types";

function startOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * /orcamento — a lista de propostas comerciais do CRM.
 *
 * Casca de renderizacao: tudo que decide alguma coisa (quem ve o que, quais
 * acoes cada situacao permite, como a taxa de aprovacao trata denominador zero)
 * mora em `lib/quotes` e e testado la, porque a suite do frontend nao tem runner
 * de DOM e uma regra escrita dentro do JSX e uma regra que nunca sera verificada.
 */
export default function OrcamentoPage() {
  const [filters, setFilters] = useState<QuotesFilters>({
    from: startOfMonth(),
    to: today(),
    page: 1,
  });
  const [metrics, setMetrics] = useState<QuotesMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  // Contador de recarga. Os cards nao dependem do objeto `filters` (as
  // dependencias do efeito sao os CAMPOS, para nao refazer a chamada a cada
  // render), entao aprovar um orcamento nao mudaria nada nas deps e a taxa de
  // aprovacao ficaria congelada ao lado de uma tabela ja atualizada — o mesmo
  // desencontro entre cards e lista que 85598b89 corrigiu, por outro caminho.
  const [versao, setVersao] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [editingQuote, setEditingQuote] = useState<Quote | null>(null);
  // Linhas com uma chamada em voo. O clique fica bloqueado durante a espera —
  // converter e irreversivel e cria pedido no ERP; um duplo-clique impaciente
  // nao pode virar uma segunda tentativa antes de a primeira responder.
  const [emCurso, setEmCurso] = useState<Set<string>>(new Set());

  const { quotes, count, loading, refetch } = useQuotes(filters);
  const currentUserEmail = useCurrentUserEmail();

  // Os QUATRO cards levam os MESMOS filtros da tabela — a licao do commit
  // 85598b89, onde escolher um vendedor movia a lista e deixava os quatro
  // numeros ao lado falando da operacao inteira. `page` fica de fora de
  // proposito: os indicadores sao do PERIODO, nao da pagina visivel, e
  // recalcula-los a cada "Próxima" faria os numeros piscarem sem mudar.
  useEffect(() => {
    // Guarda de corrida. Trocar de vendedor duas vezes seguidas dispara duas
    // chamadas e nada garante que voltem na ordem em que sairam: sem isto, a
    // resposta da PRIMEIRA pode chegar por ultimo e deixar os cards falando do
    // filtro anterior ao lado de uma tabela ja correta — que e exatamente a
    // classe de bug que /conversas ja teve com um fetch sem cancelamento.
    let atual = true;
    setMetricsLoading(true);
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    if (filters.createdBy) params.set("created_by", filters.createdBy);
    if (filters.status) params.set("status", filters.status);
    fetch(`/api/quotes/metrics?${params}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!atual) return;
        setMetrics(data);
        setMetricsLoading(false);
      })
      .catch(() => {
        if (!atual) return;
        // `metrics` fica nulo e os cards mostram zero em vez de ficarem presos
        // no esqueleto — uma tela carregando para sempre nao diz que falhou.
        setMetrics(null);
        setMetricsLoading(false);
      });
    return () => {
      atual = false;
    };
  }, [filters.from, filters.to, filters.createdBy, filters.status, versao]);

  /** Recarrega lista e cards juntos: uma acao muda os dois. */
  function recarregar() {
    refetch();
    setVersao((v) => v + 1);
  }

  function ocupar(id: string, ocupado: boolean) {
    setEmCurso((atual) => {
      const proximo = new Set(atual);
      if (ocupado) proximo.add(id);
      else proximo.delete(id);
      return proximo;
    });
  }

  async function handleStatusChange(quote: Quote, status: "aprovado" | "nao_aprovado") {
    if (emCurso.has(quote.id)) return;
    ocupar(quote.id, true);
    try {
      const res = await fetch(`/api/quotes/${quote.id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        alert(body.error || "Não foi possível alterar a situação do orçamento.");
        return;
      }
      // O CRM gravou e o Bling recusou: o vendedor precisa saber que os dois
      // lados discordam, senao ele confia na tela e o ERP fica com a situacao
      // velha sem ninguem perceber.
      if (body.situacao_sync === false) {
        alert(
          "Situação alterada no CRM, mas o Bling não confirmou a mudança. " +
            "Confira a proposta no ERP.",
        );
      }
      recarregar();
    } catch {
      alert("Erro de conexão ao alterar a situação.");
    } finally {
      ocupar(quote.id, false);
    }
  }

  async function handleConvert(quote: Quote) {
    if (emCurso.has(quote.id)) return;
    // Confirmacao porque nao ha volta: cria o pedido no Bling, gera a venda e
    // TRAVA o orcamento para edicao. O texto diz as tres consequencias em vez de
    // perguntar "tem certeza?", que nao informa nada.
    const ok = window.confirm(
      `Converter o orçamento ${quote.bling_proposal_number ? `#${quote.bling_proposal_number}` : ""} em venda?\n\n` +
        "Isso cria o pedido de venda no Bling e trava o orçamento: depois disso ele não pode mais ser editado.",
    );
    if (!ok) return;

    ocupar(quote.id, true);
    try {
      const res = await fetch(`/api/quotes/${quote.id}/convert`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        // 409 `already_converted` acontece de verdade com duas abas abertas: a
        // outra ja converteu. Recarregar mostra a linha no estado certo, entao
        // o vendedor ve o que aconteceu em vez de so uma mensagem.
        alert(
          body.error === "already_converted"
            ? "Este orçamento já foi convertido em venda."
            : body.error || "Não foi possível converter o orçamento.",
        );
        recarregar();
        return;
      }
      // A venda existe; so o espelho da situacao no Bling falhou. Nao e erro —
      // desfazer a venda seria pior que a proposta ficar com a situacao velha.
      if (body.situacao_sync === false) {
        alert(
          "Venda criada, mas o Bling não confirmou a mudança de situação da proposta. " +
            "Confira no ERP.",
        );
      }
      recarregar();
    } catch {
      // Sem retry automatico: o POST pode ter criado o pedido antes de a
      // conexao cair, e repetir produziria um segundo pedido no ERP.
      alert(
        "Erro de conexão ao converter. Confira no Bling se o pedido foi criado antes de tentar de novo.",
      );
    } finally {
      ocupar(quote.id, false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[#faf9f6]">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Orçamentos</h1>
            <p className="text-[13px] text-[#7b7b78] mt-0.5">
              Propostas comerciais, PDF para o cliente e conversão em venda
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-[4px] bg-[#111111] text-white text-[14px] font-medium transition-transform hover:scale-110 active:scale-[0.85] shrink-0"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
            Novo Orçamento
          </button>
        </div>

        <QuotesMetricsCards metrics={metrics} loading={metricsLoading} />

        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
          <QuotesFiltersBar filters={filters} onChange={setFilters} />
          <QuotesTable
            quotes={quotes}
            loading={loading}
            count={count}
            page={filters.page ?? 1}
            onPageChange={(p) => setFilters((f) => ({ ...f, page: p }))}
            onEdit={(q) => setEditingQuote(q)}
            onStatusChange={handleStatusChange}
            onConvert={handleConvert}
            busyIds={emCurso}
          />
        </div>
      </div>

      {(showCreate || editingQuote) && (
        <QuoteCreateModal
          // `pickLead` só na criação: na edição o lead já está no orçamento e
          // deixar o campo aberto convidaria a trocar o cliente de uma proposta
          // que já foi ao Bling.
          pickLead={!editingQuote}
          editingQuote={editingQuote}
          // Sem isto o orçamento nasce com `created_by` nulo e, com o escopo por
          // vendedor ligado, some da tela de quem acabou de criá-lo — a regra de
          // `quotes` não tem a exceção de `origin='bling'` que salvaria a venda
          // no caso equivalente.
          currentUserEmail={currentUserEmail}
          onClose={() => {
            setShowCreate(false);
            setEditingQuote(null);
          }}
          onSaved={() => {
            recarregar();
            setShowCreate(false);
            setEditingQuote(null);
          }}
        />
      )}
    </div>
  );
}
